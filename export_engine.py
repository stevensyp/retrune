import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
import zipfile
from html import unescape
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib import error as urlerror
from urllib import parse, request


YTDLP_BIN = os.environ.get("YTDLP_BIN", "yt-dlp")
FFMPEG_BIN = os.environ.get("FFMPEG_BIN", "ffmpeg")
ASSEMBLYAI_API_KEY = os.environ.get("ASSEMBLYAI_API_KEY", "").strip()
GOOGLE_API_FREE = os.environ.get("GOOGLE_API_FREE", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite-preview-09-2025")

MAX_ASSEMBLYAI_JOBS = 5
DEFAULT_CHANNEL_LIMIT = 5

assemblyai_sem = threading.Semaphore(MAX_ASSEMBLYAI_JOBS)


class ResolveError(Exception):
    pass


class CommandError(Exception):
    pass


def split_inputs(raw_input: str) -> List[str]:
    values = [part.strip() for part in re.split(r"[\s,]+", raw_input or "") if part.strip()]
    seen = set()
    deduped = []
    for value in values:
        key = value.rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        deduped.append(value)
    return deduped


def looks_like_video_id(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_-]{11}", value.strip()))


def remove_prefix(value: str, prefix: str) -> str:
    if value.startswith(prefix):
        return value[len(prefix) :]
    return value


def youtube_video_id(raw: str) -> Optional[str]:
    raw = (raw or "").strip()
    if looks_like_video_id(raw):
        return raw
    try:
        parsed = parse.urlparse(raw)
    except ValueError:
        return None
    host = parsed.hostname or ""
    host = remove_prefix(host.lower(), "www.")
    path = parsed.path.strip("/")
    if host == "youtu.be" and path:
        return path.split("/")[0]
    if host in {"youtube.com", "m.youtube.com"}:
        parts = path.split("/") if path else []
        if parsed.path == "/watch":
            return parse.parse_qs(parsed.query).get("v", [""])[0] or None
        if parts and parts[0] in {"shorts", "live", "embed"} and len(parts) > 1:
            return parts[1] or None
    return None


def normalize_youtube_input(raw: str) -> str:
    trimmed = (raw or "").strip()
    if not trimmed:
        return ""
    if looks_like_video_id(trimmed):
        return f"https://www.youtube.com/watch?v={trimmed}"
    if trimmed.startswith(("http://", "https://")):
        return trimmed
    if trimmed.startswith("@"):
        return "https://www.youtube.com/" + trimmed
    if trimmed.startswith("UC"):
        return "https://www.youtube.com/channel/" + trimmed
    return "https://www.youtube.com/" + trimmed.strip("/")


def looks_like_youtube_channel(raw: str) -> bool:
    trimmed = (raw or "").strip()
    if not trimmed or youtube_video_id(trimmed):
        return False
    if trimmed.startswith("@") or trimmed.startswith("UC"):
        return True
    normalized = normalize_youtube_input(trimmed)
    try:
        parsed = parse.urlparse(normalized)
    except ValueError:
        return False
    host = remove_prefix((parsed.hostname or "").lower(), "www.")
    if host not in {"youtube.com", "m.youtube.com"}:
        return False
    parts = parsed.path.strip("/").split("/") if parsed.path.strip("/") else []
    if not parts:
        return False
    if parts[0].startswith("@"):
        return True
    if parts[0] in {"channel", "c", "user"}:
        return True
    return parts[0] not in {"watch", "shorts", "live", "embed"} and len(parts) == 1


def slug(value: str, fallback: str = "export") -> str:
    value = (value or "").lower().strip()
    value = re.sub(r"^https?://", "", value)
    value = re.sub(r"^(www\.)?youtube\.com/", "", value)
    value = remove_prefix(remove_prefix(value, "@"), "channel/")
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value[:80] or fallback


def safe_filename(title: str, ext: str, fallback: str) -> str:
    clean = re.sub(r'[\\/:*?"<>|]+', "", title or "").strip()
    clean = re.sub(r"\s+", " ", clean)[:80].strip()
    if not clean:
        clean = fallback
    return clean + ext


def run_cmd(args: List[str], timeout: int = 300) -> str:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as err:
        raise CommandError(f"Command timed out after {timeout}s") from err
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "Command failed").strip()
        message = message.splitlines()[-1] if message else "Command failed"
        raise CommandError(message)
    return result.stdout


def run_json(args: List[str], timeout: int = 120) -> Dict:
    output = run_cmd(args, timeout=timeout)
    try:
        return json.loads(output)
    except json.JSONDecodeError as err:
        raise CommandError("yt-dlp returned invalid JSON") from err


def media_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def best_formats(info: Dict) -> List[Dict]:
    best_by_height = {}
    for fmt in info.get("formats", []):
        height = fmt.get("height")
        if not height or fmt.get("vcodec", "none") == "none":
            continue
        tbr = fmt.get("tbr") or 0
        if height not in best_by_height or tbr > (best_by_height[height].get("tbr") or 0):
            best_by_height[height] = fmt
    formats = [
        {"id": fmt["format_id"], "label": f"{height}p", "height": height}
        for height, fmt in best_by_height.items()
    ]
    formats.sort(key=lambda item: item["height"], reverse=True)
    return formats


def item_from_info(info: Dict, source: str) -> Dict:
    video_id = info.get("id") or youtube_video_id(source) or uuid.uuid4().hex[:8]
    return {
        "id": video_id,
        "url": info.get("webpage_url") or source,
        "title": info.get("title") or "Untitled",
        "thumbnail": info.get("thumbnail") or last_thumbnail(info),
        "duration": info.get("duration"),
        "uploader": info.get("uploader") or info.get("channel") or "",
        "upload_date": info.get("upload_date") or "",
        "view_count": info.get("view_count") or 0,
        "formats": best_formats(info),
        "has_manual_subtitles": bool(info.get("subtitles")),
        "has_auto_subtitles": bool(info.get("automatic_captions")),
        "metadata": compact_metadata(info),
    }


def compact_metadata(info: Dict) -> Dict:
    keys = [
        "id",
        "title",
        "channel",
        "channel_id",
        "webpage_url",
        "upload_date",
        "duration",
        "description",
        "tags",
        "categories",
        "view_count",
        "like_count",
        "comment_count",
        "availability",
        "live_status",
        "thumbnail",
        "uploader",
        "uploader_url",
        "channel_url",
    ]
    return {key: info.get(key) for key in keys if info.get(key) not in (None, "", [])}


def last_thumbnail(info: Dict) -> str:
    thumbnails = info.get("thumbnails") or []
    if thumbnails:
        return thumbnails[-1].get("url", "")
    return ""


def fetch_video_info(raw: str) -> Dict:
    normalized = normalize_youtube_input(raw) if youtube_video_id(raw) else raw
    info = run_json([YTDLP_BIN, "--no-playlist", "--dump-single-json", "--no-warnings", normalized])
    return item_from_info(info, normalized)


def channel_videos_url(raw: str) -> str:
    normalized = normalize_youtube_input(raw).rstrip("/")
    if not normalized.endswith("/videos"):
        normalized += "/videos"
    return normalized


def resolve_channel(raw: str, limit: int = 12, fetch_details: bool = False, order: str = "date") -> Tuple[Dict, List[Dict]]:
    args = [
        YTDLP_BIN,
        "--flat-playlist",
        "--dump-single-json",
        "--no-warnings",
    ]
    if limit > 0:
        args += ["--playlist-end", str(limit)]
    args.append(channel_videos_url(raw))
    payload = run_json(args, timeout=120)
    channel = {
        "id": payload.get("channel_id") or payload.get("id") or "",
        "title": payload.get("channel") or payload.get("uploader") or payload.get("title") or raw,
        "handle": payload.get("uploader_id") or "",
        "url": payload.get("channel_url") or normalize_youtube_input(raw),
        "description": payload.get("description") or "",
        "follower_count": payload.get("channel_follower_count"),
        "video_count": len(payload.get("entries") or []),
    }
    candidates = []
    for entry in payload.get("entries") or []:
        video_id = entry.get("id")
        if not video_id:
            continue
        candidates.append(
            {
                "id": video_id,
                "url": entry.get("url") or media_url(video_id),
                "title": entry.get("title") or video_id,
                "upload_date": entry.get("upload_date") or "",
                "view_count": entry.get("view_count") or 0,
            }
        )
    if order == "popularity":
        candidates.sort(key=lambda item: (item.get("view_count") or 0, item.get("upload_date") or ""), reverse=True)
    else:
        candidates.sort(key=lambda item: item.get("upload_date") or "", reverse=True)

    if fetch_details:
        detailed = []
        for candidate in candidates:
            try:
                detailed.append(fetch_video_info(candidate["url"]))
            except Exception:
                detailed.append(candidate)
        return channel, detailed
    return channel, candidates


def resolve_input(raw_input: str) -> Dict:
    values = split_inputs(raw_input)
    if not values:
        raise ResolveError("Paste at least one URL, YouTube handle, channel ID, or video ID")

    capabilities = capabilities_payload()
    if len(values) == 1 and looks_like_youtube_channel(values[0]):
        try:
            channel, items = resolve_channel(values[0], limit=12)
        except CommandError as err:
            raise ResolveError(str(err))
        return {
            "kind": "channel",
            "input": values[0],
            "channel": channel,
            "items": items,
            "capabilities": capabilities,
        }

    items = []
    errors = []
    for value in values:
        try:
            items.append(fetch_video_info(value))
        except Exception as err:
            errors.append({"input": value, "error": str(err)})
    if not items and errors:
        raise ResolveError(errors[0]["error"])

    kind = "video" if len(items) == 1 and youtube_video_id(values[0]) else "bulk"
    return {
        "kind": kind,
        "input": raw_input,
        "items": items,
        "errors": errors,
        "capabilities": capabilities,
    }


def capabilities_payload() -> Dict:
    return {
        "assemblyai": bool(ASSEMBLYAI_API_KEY),
        "gemini": bool(GOOGLE_API_FREE),
        "formats": {
            "text": ["txt", "md", "json"],
            "audio": ["mp3", "wav"],
            "video": ["mp4", "mkv"],
        },
        "qualities": ["optimized", "highest", "compressed"],
    }


def parse_clock(raw: str) -> int:
    raw = (raw or "").strip()
    if not raw:
        return 0
    parts = raw.split(":")
    if len(parts) not in (2, 3):
        raise ValueError("time must use mm:ss or hh:mm:ss")
    try:
        nums = [int(part) for part in parts]
    except ValueError as err:
        raise ValueError("time must contain only numbers") from err
    if any(num < 0 for num in nums):
        raise ValueError("time values must be positive")
    if len(nums) == 2:
        minutes, seconds = nums
        hours = 0
    else:
        hours, minutes, seconds = nums
    if minutes > 59 or seconds > 59:
        raise ValueError("minutes and seconds must be below 60")
    return hours * 3600 + minutes * 60 + seconds


class JobStore:
    def __init__(self, root_dir: str):
        self.root_dir = Path(root_dir)
        self.jobs_dir = self.root_dir / "jobs"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.jobs = {}
        self.lock = threading.Lock()

    def capabilities(self) -> Dict:
        return capabilities_payload()

    def create(self, config: Dict) -> Dict:
        raw_input = (config.get("input") or config.get("url") or "").strip()
        if not raw_input:
            raise ValueError("input is required")
        job_id = uuid.uuid4().hex[:10]
        job_dir = self.jobs_dir / job_id
        files_dir = job_dir / "files"
        tmp_dir = job_dir / ".tmp"
        files_dir.mkdir(parents=True, exist_ok=True)
        tmp_dir.mkdir(parents=True, exist_ok=True)
        job = {
            "id": job_id,
            "status": "queued",
            "stage": "Queued",
            "message": "Waiting to start",
            "progress": 0,
            "config": normalize_config(config),
            "items": [],
            "artifacts": [],
            "error": None,
            "job_dir": str(job_dir),
            "files_dir": str(files_dir),
            "tmp_dir": str(tmp_dir),
            "zip_path": None,
            "created_at": time.time(),
        }
        with self.lock:
            self.jobs[job_id] = job
        thread = threading.Thread(target=self._run_job, args=(job_id,), daemon=True)
        thread.start()
        return job

    def public(self, job_id: str) -> Optional[Dict]:
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return None
            return {
                "id": job["id"],
                "status": job["status"],
                "stage": job["stage"],
                "message": job["message"],
                "progress": job["progress"],
                "items": list(job["items"]),
                "artifacts": [
                    {
                        "id": artifact["id"],
                        "label": artifact["label"],
                        "filename": artifact["filename"],
                        "kind": artifact["kind"],
                        "item_id": artifact.get("item_id"),
                    }
                    for artifact in job["artifacts"]
                ],
                "error": job["error"],
                "zip_available": bool(job.get("zip_path")),
                "capabilities": capabilities_payload(),
            }

    def artifact(self, job_id: str, artifact_id: str) -> Optional[Dict]:
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return None
            for artifact in job["artifacts"]:
                if artifact["id"] == artifact_id and os.path.exists(artifact["path"]):
                    return artifact
        return None

    def zip_path(self, job_id: str) -> Optional[str]:
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return None
            zip_path = job.get("zip_path")
            if zip_path and os.path.exists(zip_path):
                return zip_path
        return None

    def _run_job(self, job_id: str) -> None:
        job = self.jobs[job_id]
        try:
            self._update(job, status="resolving", stage="Resolving", message="Resolving input")
            run_export(job, self._update, self._add_artifact)
            final_status = "partial" if any(item.get("status") == "error" for item in job["items"]) else "done"
            if job["artifacts"]:
                self._package_zip(job)
            self._update(job, status=final_status, stage="Complete", message="Export complete", progress=100)
        except Exception as err:
            self._update(job, status="error", stage="Error", message=str(err), error=str(err), progress=100)

    def _update(self, job: Dict, **updates) -> None:
        with self.lock:
            job.update(updates)

    def _add_artifact(self, job: Dict, path: Path, label: str, kind: str, item_id: Optional[str] = None) -> Dict:
        artifact = {
            "id": uuid.uuid4().hex[:8],
            "label": label,
            "kind": kind,
            "item_id": item_id,
            "path": str(path),
            "filename": path.name,
        }
        with self.lock:
            job["artifacts"].append(artifact)
        return artifact

    def _package_zip(self, job: Dict) -> None:
        zip_path = Path(job["job_dir"]) / "export.zip"
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for artifact in job["artifacts"]:
                path = Path(artifact["path"])
                if path.exists() and path != zip_path:
                    archive.write(path, path.relative_to(Path(job["files_dir"])))
        with self.lock:
            job["zip_path"] = str(zip_path)


def normalize_config(config: Dict) -> Dict:
    normalized = {
        "input": (config.get("input") or config.get("url") or "").strip(),
        "mode": config.get("mode") or "export",
        "output_format": config.get("output_format") or config.get("format") or "video",
        "text_extension": config.get("text_extension") or "txt",
        "audio_extension": config.get("audio_extension") or "mp3",
        "video_extension": config.get("video_extension") or "mp4",
        "quality": config.get("quality") or "optimized",
        "transcription": bool(config.get("transcription")),
        "transcription_format": config.get("transcription_format") or "txt",
        "transcript_fallback": config.get("transcript_fallback") or "auto_captions",
        "gemini_cleanup": bool(config.get("gemini_cleanup")),
        "video_metadata": bool(config.get("video_metadata")),
        "channel_metadata": bool(config.get("channel_metadata")),
        "order": config.get("order") or "date",
        "max_videos": int(config.get("max_videos") or DEFAULT_CHANNEL_LIMIT),
        "quick_format_id": config.get("quick_format_id"),
        "format_ids": config.get("format_ids") or {},
        "title": config.get("title") or "",
    }
    normalized["clip_start_seconds"] = int(config.get("clip_start_seconds") or parse_clock(config.get("clip_start") or ""))
    normalized["clip_end_seconds"] = int(config.get("clip_end_seconds") or parse_clock(config.get("clip_end") or ""))
    if normalized["clip_end_seconds"] and normalized["clip_start_seconds"] >= normalized["clip_end_seconds"]:
        raise ValueError("clip start must be earlier than clip end")
    if normalized["output_format"] == "audio":
        normalized["audio_extension"] = normalized["audio_extension"] if normalized["audio_extension"] in {"mp3", "wav"} else "mp3"
    if normalized["output_format"] == "video":
        normalized["video_extension"] = normalized["video_extension"] if normalized["video_extension"] in {"mp4", "mkv"} else "mp4"
    if normalized["output_format"] == "text":
        normalized["transcription"] = False
    return normalized


def run_export(job: Dict, update, add_artifact) -> None:
    cfg = job["config"]
    values = split_inputs(cfg["input"])
    if len(values) == 1 and looks_like_youtube_channel(values[0]):
        channel, items = resolve_channel(
            values[0],
            limit=max(cfg["max_videos"], 1),
            fetch_details=True,
            order=cfg["order"],
        )
        if cfg["channel_metadata"]:
            channel_path = Path(job["files_dir"]) / "channel.json"
            write_json(channel_path, channel)
            add_artifact(job, channel_path, "Channel metadata", "metadata")
    else:
        items = [fetch_video_info(value) for value in values]

    if not items:
        raise ValueError("No media items were found")

    job["items"] = [public_item(item, "queued") for item in items]

    for index, item in enumerate(items):
        update(
            job,
            status="processing",
            stage="Processing",
            message=f"Processing {index + 1}/{len(items)}: {item.get('title', item.get('id'))}",
            progress=int((index / max(len(items), 1)) * 90),
        )
        try:
            process_item(job, cfg, item, add_artifact)
            job["items"][index] = public_item(item, "done")
        except Exception as err:
            failed = public_item(item, "error")
            failed["error"] = str(err)
            job["items"][index] = failed
    update(job, status="packaging", stage="Packaging", message="Packaging results", progress=95)


def public_item(item: Dict, status: str) -> Dict:
    return {
        "id": item.get("id"),
        "url": item.get("url"),
        "title": item.get("title") or item.get("id"),
        "thumbnail": item.get("thumbnail", ""),
        "duration": item.get("duration"),
        "uploader": item.get("uploader", ""),
        "status": status,
    }


def process_item(job: Dict, cfg: Dict, item: Dict, add_artifact) -> None:
    files_dir = Path(job["files_dir"])
    tmp_dir = Path(job["tmp_dir"]) / item["id"]
    tmp_dir.mkdir(parents=True, exist_ok=True)
    base_dir = files_dir / f"{item.get('upload_date') or 'unknown-date'}-{item['id']}-{slug(item.get('title'), item['id'])}"
    base_dir.mkdir(parents=True, exist_ok=True)

    source_audio = None
    transcript_text = None
    transcript_source = "none"

    if needs_transcript(cfg):
        transcript_source, transcript_text, source_audio = produce_transcript(cfg, item, tmp_dir, source_audio)
        ext = cfg["text_extension"] if cfg["output_format"] == "text" else cfg["transcription_format"]
        transcript_path = base_dir / f"transcript.{ext}"
        write_transcript(transcript_path, ext, item, transcript_source, transcript_text)
        add_artifact(job, transcript_path, "Transcript", "transcript", item["id"])

    if cfg["output_format"] == "audio":
        source_audio = source_audio or download_best_audio(item, tmp_dir)
        audio_ext = cfg["audio_extension"]
        audio_filename = safe_filename(item.get("title", ""), f".{audio_ext}", "audio") if cfg.get("mode") == "quick" else f"audio.{audio_ext}"
        audio_path = base_dir / audio_filename
        convert_audio(source_audio, audio_path, cfg)
        add_artifact(job, audio_path, "Audio", "audio", item["id"])

    if cfg["output_format"] == "video":
        source_video = download_best_video(item, tmp_dir, cfg.get("format_ids", {}).get(item["id"]) or cfg.get("quick_format_id"))
        video_ext = cfg["video_extension"]
        video_filename = safe_filename(item.get("title", ""), f".{video_ext}", "video") if cfg.get("mode") == "quick" else f"video.{video_ext}"
        video_path = base_dir / video_filename
        convert_video(source_video, video_path, cfg)
        add_artifact(job, video_path, "Video", "video", item["id"])

    if cfg["video_metadata"]:
        metadata = item.get("metadata") or {}
        metadata = dict(metadata)
        metadata.update({"transcript_source": transcript_source})
        metadata_path = base_dir / "metadata.json"
        write_json(metadata_path, metadata)
        add_artifact(job, metadata_path, "Video metadata", "metadata", item["id"])

    shutil.rmtree(tmp_dir, ignore_errors=True)


def needs_transcript(cfg: Dict) -> bool:
    return cfg["output_format"] == "text" or (
        cfg["output_format"] in {"audio", "video"} and cfg.get("transcription")
    )


def produce_transcript(cfg: Dict, item: Dict, tmp_dir: Path, source_audio: Optional[str]) -> Tuple[str, str, Optional[str]]:
    has_clip = cfg.get("clip_start_seconds", 0) > 0 or cfg.get("clip_end_seconds", 0) > 0
    if has_clip:
        source_audio = source_audio or download_best_audio(item, tmp_dir)
        clipped_audio = tmp_dir / "transcript-segment.mp3"
        convert_audio(source_audio, clipped_audio, cfg, force_mp3=True)
        return "assemblyai", transcribe_with_assemblyai(str(clipped_audio)), source_audio

    fallback = cfg.get("transcript_fallback", "auto_captions")
    sources = []
    if item.get("has_manual_subtitles"):
        sources.append("youtube_manual")
    if fallback != "assemblyai_transcripts" and item.get("has_auto_subtitles"):
        sources.append("youtube_auto")

    for source in sources:
        try:
            text = download_youtube_transcript(item, tmp_dir, source == "youtube_auto")
            if source == "youtube_auto" and cfg.get("gemini_cleanup") and GOOGLE_API_FREE:
                text = cleanup_with_gemini(item, source, text)
            return source, text, source_audio
        except Exception:
            continue

    source_audio = source_audio or download_best_audio(item, tmp_dir)
    return "assemblyai", transcribe_with_assemblyai(source_audio), source_audio


def download_best_audio(item: Dict, tmp_dir: Path) -> str:
    out_template = str(tmp_dir / "%(id)s.%(ext)s")
    run_cmd(
        [
            YTDLP_BIN,
            "--no-playlist",
            "-f",
            "bestaudio/best",
            "-o",
            out_template,
            item["url"],
        ],
        timeout=600,
    )
    files = sorted(tmp_dir.glob(f"{item['id']}.*"))
    if not files:
        files = sorted(tmp_dir.iterdir())
    if not files:
        raise CommandError("audio download completed but no file was found")
    return str(files[0])


def download_best_video(item: Dict, tmp_dir: Path, format_id: Optional[str] = None) -> str:
    out_template = str(tmp_dir / "%(id)s.%(ext)s")
    fmt = f"{format_id}+bestaudio/best" if format_id else "bestvideo+bestaudio/best"
    run_cmd(
        [
            YTDLP_BIN,
            "--no-playlist",
            "-f",
            fmt,
            "--merge-output-format",
            "mp4",
            "-o",
            out_template,
            item["url"],
        ],
        timeout=900,
    )
    mp4s = sorted(tmp_dir.glob(f"{item['id']}*.mp4"))
    files = mp4s or sorted(tmp_dir.glob(f"{item['id']}.*")) or sorted(tmp_dir.iterdir())
    if not files:
        raise CommandError("video download completed but no file was found")
    return str(files[0])


def quality_profile(cfg: Dict) -> Dict:
    quality = cfg.get("quality", "optimized")
    profiles = {
        "highest": {"audio_bitrate": "320k", "video_crf": "18", "height": 2160},
        "compressed": {"audio_bitrate": "96k", "video_crf": "30", "height": 720},
        "optimized": {"audio_bitrate": "192k", "video_crf": "24", "height": 1080},
    }
    return profiles.get(quality, profiles["optimized"])


def clip_args(cfg: Dict) -> List[str]:
    args = []
    if cfg.get("clip_start_seconds", 0) > 0:
        args += ["-ss", str(cfg["clip_start_seconds"])]
    if cfg.get("clip_end_seconds", 0) > 0:
        duration = cfg["clip_end_seconds"] - cfg.get("clip_start_seconds", 0)
        if duration > 0:
            args += ["-t", str(duration)]
    return args


def convert_audio(input_path: str, output_path: Path, cfg: Dict, force_mp3: bool = False) -> None:
    profile = quality_profile(cfg)
    ext = "mp3" if force_mp3 else output_path.suffix.lstrip(".")
    args = [FFMPEG_BIN, "-y"] + clip_args(cfg) + ["-i", input_path, "-vn"]
    if ext == "wav":
        args += ["-c:a", "pcm_s16le"]
    else:
        args += ["-c:a", "libmp3lame", "-b:a", profile["audio_bitrate"]]
    args.append(str(output_path))
    run_cmd(args, timeout=600)


def convert_video(input_path: str, output_path: Path, cfg: Dict) -> None:
    profile = quality_profile(cfg)
    scale = f"scale=-2:min({profile['height']}\\,ih)"
    args = [
        FFMPEG_BIN,
        "-y",
    ] + clip_args(cfg) + [
        "-i",
        input_path,
        "-vf",
        scale,
        "-c:v",
        "libx264",
        "-crf",
        profile["video_crf"],
        "-preset",
        "medium",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        str(output_path),
    ]
    run_cmd(args, timeout=900)


def parse_subtitle_languages(output: str, automatic: bool) -> List[str]:
    wanted = "Available automatic captions" if automatic else "Available subtitles"
    other = "Available subtitles" if automatic else "Available automatic captions"
    in_section = False
    languages = []
    for line in output.splitlines():
        trimmed = line.strip()
        if wanted in trimmed:
            in_section = True
            continue
        if other in trimmed and in_section:
            break
        if not in_section or not trimmed or trimmed.startswith("Language"):
            continue
        code = trimmed.split()[0]
        if re.fullmatch(r"[A-Za-z0-9_.-]+", code) and code not in languages:
            languages.append(code)
    return languages


def select_subtitle_language(languages: List[str]) -> str:
    for preferred in ("en", "en-US", "en-GB"):
        if preferred in languages:
            return preferred
    for lang in languages:
        if lang.startswith("en"):
            return lang
    return languages[0] if languages else ""


def download_youtube_transcript(item: Dict, tmp_dir: Path, automatic: bool) -> str:
    output = run_cmd([YTDLP_BIN, "--list-subs", "--no-warnings", "--no-playlist", item["url"]], timeout=120)
    language = select_subtitle_language(parse_subtitle_languages(output, automatic))
    if not language:
        raise CommandError("No matching subtitles found")
    out_template = str(tmp_dir / "subtitle.%(ext)s")
    args = [
        YTDLP_BIN,
        "--skip-download",
        "--no-playlist",
        "--sub-langs",
        language,
        "--sub-format",
        "vtt",
        "-o",
        out_template,
    ]
    args.append("--write-auto-subs" if automatic else "--write-subs")
    args.append(item["url"])
    run_cmd(args, timeout=180)
    matches = sorted(tmp_dir.glob("subtitle*.vtt"))
    if not matches:
        raise CommandError("Subtitle download completed but no VTT file was found")
    return vtt_to_text(matches[0])


def vtt_to_text(path: Path) -> str:
    lines = []
    for raw_line in path.read_text(errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line == "WEBVTT" or line.startswith(("Kind:", "Language:", "NOTE")):
            continue
        if "-->" in line or re.fullmatch(r"\d+", line):
            continue
        line = re.sub(r"<[^>]+>", "", line)
        line = unescape(line)
        line = re.sub(r"\s+", " ", line).strip()
        if line and (not lines or lines[-1] != line):
            lines.append(line)
    return clean_transcript("\n".join(lines))


def clean_transcript(text: str) -> str:
    text = re.sub(r"\s+([,.;:!?])", r"\1", text or "")
    paragraphs = []
    current = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        current.append(line)
        if len(" ".join(current)) > 420 or line.endswith((".", "!", "?")):
            paragraphs.append(" ".join(current))
            current = []
    if current:
        paragraphs.append(" ".join(current))
    return "\n\n".join(paragraphs).strip()


def write_transcript(path: Path, ext: str, item: Dict, source: str, text: str) -> None:
    if ext == "json":
        write_json(
            path,
            {
                "id": item.get("id"),
                "title": item.get("title"),
                "url": item.get("url"),
                "transcript_source": source,
                "transcript": text,
            },
        )
    elif ext == "md":
        path.write_text(
            f"# {item.get('title', 'Untitled')}\n\n"
            f"- URL: {item.get('url')}\n"
            f"- Transcript source: {source}\n\n{text}\n",
        )
    else:
        path.write_text(text + "\n")


def write_json(path: Path, value: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def transcribe_with_assemblyai(audio_path: str) -> str:
    if not ASSEMBLYAI_API_KEY:
        raise CommandError("ASSEMBLYAI_API_KEY is not set")
    with assemblyai_sem:
        upload_url = assemblyai_upload(audio_path)
        transcript_id = assemblyai_submit(upload_url)
        return assemblyai_poll(transcript_id)


def assemblyai_request(method: str, url: str, body: Optional[bytes] = None, content_type: str = "application/json") -> Dict:
    headers = {"authorization": ASSEMBLYAI_API_KEY}
    if content_type:
        headers["content-type"] = content_type
    req = request.Request(url, data=body, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=60) as response:
            data = response.read()
    except urlerror.HTTPError as err:
        raise CommandError(f"AssemblyAI error: {err.code}") from err
    return json.loads(data.decode("utf-8"))


def assemblyai_upload(audio_path: str) -> str:
    with open(audio_path, "rb") as handle:
        body = handle.read()
    payload = assemblyai_request("POST", "https://api.assemblyai.com/v2/upload", body, "application/octet-stream")
    upload_url = payload.get("upload_url")
    if not upload_url:
        raise CommandError("AssemblyAI upload did not return an upload URL")
    return upload_url


def assemblyai_submit(upload_url: str) -> str:
    body = json.dumps({"audio_url": upload_url}).encode("utf-8")
    payload = assemblyai_request("POST", "https://api.assemblyai.com/v2/transcript", body)
    transcript_id = payload.get("id")
    if not transcript_id:
        raise CommandError("AssemblyAI did not return a transcript ID")
    return transcript_id


def assemblyai_poll(transcript_id: str) -> str:
    url = f"https://api.assemblyai.com/v2/transcript/{transcript_id}"
    for _ in range(180):
        payload = assemblyai_request("GET", url, None, "")
        status = payload.get("status")
        if status == "completed":
            return payload.get("text") or ""
        if status == "error":
            raise CommandError(payload.get("error") or "AssemblyAI transcription failed")
        time.sleep(3)
    raise CommandError("AssemblyAI transcription timed out")


def cleanup_with_gemini(item: Dict, source: str, text: str) -> str:
    prompt = (
        "Clean these YouTube auto-generated captions.\n\n"
        "Keep the original meaning and all audio tags such as [Music], [Laughing], [Applause]. "
        "Do not summarize, paraphrase, or formalize. Return plain text only.\n\n"
        f"Video title: {item.get('title')}\n"
        f"Transcript source: {source}\n\n"
        f"Raw captions:\n{text}"
    )
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={parse.quote(GOOGLE_API_FREE)}"
    )
    body = json.dumps(
        {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0},
        }
    ).encode("utf-8")
    req = request.Request(url, data=body, headers={"content-type": "application/json"}, method="POST")
    try:
        with request.urlopen(req, timeout=90) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return text
    for candidate in payload.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            cleaned = (part.get("text") or "").strip()
            if cleaned:
                return cleaned
    return text
