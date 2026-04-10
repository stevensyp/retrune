# ReClip Onboarding

> Practical onboarding for engineers working on `retrune`, a self-hosted media download and export web app built with Flask and a single-file frontend.

## What This Repo Is

This repository is a lightweight web app for downloading and exporting media through `yt-dlp` and `ffmpeg`. The app serves one HTML page, exposes a JSON job API, and stores active job state in memory while downloads and exports run in background threads.

This fork currently tracks the upstream ReClip project shape while adding a richer Python export engine:

- `origin`: `https://github.com/stevensyp/retrune.git`
- `upstream`: `https://github.com/averygan/reclip.git`

## Quick Start

### Prerequisites

| Tool | Notes |
|------|-------|
| `python3` | Required for local runs and `reclip.sh` |
| `yt-dlp` | Required for metadata fetches and downloads |
| `ffmpeg` | Required for audio extraction, clipping, and media conversion |
| Docker | Optional, for containerized runs |
| AssemblyAI key | Optional, enables transcript fallback beyond YouTube captions |
| Gemini key | Optional, enables Gemini cleanup for YouTube auto captions |

### Fastest Local Setup

```bash
brew install yt-dlp ffmpeg
./reclip.sh
```

`reclip.sh` checks for `python3`, `yt-dlp`, and `ffmpeg`, creates `venv/` on first run, installs `flask` and `yt-dlp`, and starts the Flask server on port `8899`.

Optional server-side environment variables:

```bash
export ASSEMBLYAI_API_KEY=...
export GEMINI_API_FREE_KEY=...
export YTDLP_BIN=yt-dlp
export FFMPEG_BIN=ffmpeg
```

### Manual Local Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 app.py
```

By default the app binds to `127.0.0.1:8899`.

### Docker Setup

```bash
docker build -t reclip .
docker run -p 8899:8899 reclip
```

The Docker image installs `ffmpeg`, copies the app into `/app`, sets `HOST=0.0.0.0`, and starts `python app.py`.

### Verify It Works

1. Start the app with either `./reclip.sh`, `python3 app.py`, or Docker.
2. Open `http://127.0.0.1:8899`.
3. Paste a supported media URL and click `Analyze Input`.
4. Confirm the page renders a preview card with title, thumbnail, and format options.
5. Start an export and confirm individual artifacts or a ZIP are available when complete.

There is no automated test suite in this repo today, so manual verification is the main check.

## Architecture

### System Overview

```text
Browser
  |
  v
Flask app (`app.py`)
  |
  +-> `GET /` -> renders `templates/index.html`
  +-> `POST /api/resolve` -> detects input and previews media/channel data
  +-> `POST /api/jobs` -> starts a background export job
  +-> `GET /api/jobs/<job_id>` -> polls in-memory job state
  +-> `GET /api/jobs/<job_id>/artifacts/<artifact_id>` -> serves one artifact
  +-> `GET /api/jobs/<job_id>/zip` -> serves packaged export ZIP
  +-> legacy `/api/info`, `/api/download`, `/api/status`, `/api/file`
```

### Runtime Model

- The Flask routes live in [`app.py`](/Users/steven/Library/Mobile%20Documents/com~apple~CloudDocs/Developer/retrune/app.py).
- Export orchestration, `yt-dlp`, `ffmpeg`, AssemblyAI, Gemini, transcript, metadata, and ZIP behavior lives in [`export_engine.py`](/Users/steven/Library/Mobile%20Documents/com~apple~CloudDocs/Developer/retrune/export_engine.py).
- Jobs are tracked in memory by `JobStore`.
- Each export runs in a daemon thread created by `/api/jobs`.
- Files are written to `downloads/jobs/<job-id>/`, which is ignored by Git.
- There is no database, queue, authentication layer, or persistent job history.

### Main Request Flow

1. The user pastes URLs, a YouTube handle, a channel ID, or a video ID into [`templates/index.html`](/Users/steven/Library/Mobile%20Documents/com~apple~CloudDocs/Developer/retrune/templates/index.html).
2. Frontend JavaScript calls `POST /api/resolve` to detect generic, bulk, YouTube video, or YouTube channel input.
3. The UI reveals only relevant export controls.
4. When the user starts an export, the frontend calls `POST /api/jobs`.
5. The backend runs `yt-dlp`, `ffmpeg`, optional AssemblyAI, optional Gemini, metadata writing, and ZIP packaging through `export_engine.py`.
6. The frontend polls `GET /api/jobs/<job_id>` and exposes individual artifacts plus a ZIP.

## Tech Stack

| Layer | Technology | Notes |
|------|------------|-------|
| Backend | Flask | Thin route layer over export services |
| Frontend | Vanilla HTML/CSS/JS | Embedded in one template |
| Media engine | `yt-dlp` + `ffmpeg` | External system dependencies |
| Transcription | YouTube captions + AssemblyAI | AssemblyAI is optional and env-gated |
| Caption cleanup | Gemini | Optional and env-gated |
| Packaging | `venv` script + Docker | No build pipeline |
| Assets | Static image/video previews | Marketing/demo only |

## Key Files

| Path | Purpose |
|------|---------|
| [`app.py`](/Users/steven/Library/Mobile%20Documents/com~apple~CloudDocs/Developer/retrune/app.py) | Flask app and API routes |
| [`export_engine.py`](/Users/steven/Library/Mobile%20Documents/com~apple~CloudDocs/Developer/retrune/export_engine.py) | Export orchestration, integrations, transcripts, metadata, ZIP packaging |
| [`templates/index.html`](/Users/steven/Library/Mobile%20Documents/com~apple~CloudDocs/Developer/retrune/templates/index.html) | Entire UI, styling, and client-side logic |
| [`reclip.sh`](/Users/steven/Library/Mobile%20Documents/com~apple~CloudDocs/Developer/retrune/reclip.sh) | Local bootstrap script for first-run setup |
| [`requirements.txt`](/Users/steven/Library/Mobile%20Documents/com~apple~CloudDocs/Developer/retrune/requirements.txt) | Python dependencies |
| [`Dockerfile`](/Users/steven/Library/Mobile%20Documents/com~apple~CloudDocs/Developer/retrune/Dockerfile) | Containerized runtime |

## Common Developer Tasks

### Change Download Or Export Behavior

Edit [`export_engine.py`](/Users/steven/Library/Mobile%20Documents/com~apple~CloudDocs/Developer/retrune/export_engine.py):

- `resolve_input(...)` for input detection and preview behavior
- `process_item(...)` for per-item export behavior
- `produce_transcript(...)` for transcript policy
- `convert_audio(...)` and `convert_video(...)` for `ffmpeg` behavior

### Change API Behavior

Edit [`app.py`](/Users/steven/Library/Mobile%20Documents/com~apple~CloudDocs/Developer/retrune/app.py). Keep routes thin and push reusable behavior into `export_engine.py` so future CLI/API entrypoints can share it.

### Change The UI

Edit [`templates/index.html`](/Users/steven/Library/Mobile%20Documents/com~apple~CloudDocs/Developer/retrune/templates/index.html). The template contains:

- the page markup
- all CSS styles
- all browser-side resolve, start-job, polling, and artifact-link logic

There is no frontend build step, so refresh-based iteration is enough.

## Debugging Guide

### Common Failure Modes

- `yt-dlp: command not found`
  Install `yt-dlp`, use the Docker image, or set `YTDLP_BIN`.

- `ffmpeg: command not found`
  Install `ffmpeg`, use the Docker image, or set `FFMPEG_BIN`.

- Fetch succeeds but download fails
  Check the final stderr line returned by `yt-dlp` in the UI error state.

- Job disappears after restart
  Expected: job state only lives in the in-memory `JobStore`.

- Transcript fallback fails
  `ASSEMBLYAI_API_KEY` must be configured when YouTube captions are unavailable or AssemblyAI-first fallback is selected.

### Useful Places To Inspect

- Backend logs: the terminal running Flask
- API behavior: browser devtools network tab
- Generated files: `downloads/jobs/`

### Quick Syntax Checks

```bash
python3 -m py_compile app.py export_engine.py
bash -n reclip.sh
```

These are lightweight checks when you want confidence without adding test infrastructure.

## Contribution Guardrails

### What To Preserve

- Keep the no-build, low-dependency shape unless there is a strong reason to expand it.
- Preserve the simple request flow between the single template, Flask API, and reusable Python export engine.
- Treat external command execution as the main failure surface and handle errors clearly.
- Keep optional AI integrations server-side; never collect API keys in the browser.

### Review Checklist

- Local startup still works through `./reclip.sh` or Docker.
- The homepage still loads on `localhost:8899`.
- Analyze still returns title, thumbnail, and format choices for generic URLs.
- Export completion yields individual artifacts and a ZIP under `downloads/jobs/`.

## Audience Notes

### Junior Engineers

- Start with [`app.py`](/Users/steven/Library/Mobile%20Documents/com~apple~CloudDocs/Developer/retrune/app.py) for routes, then [`export_engine.py`](/Users/steven/Library/Mobile%20Documents/com~apple~CloudDocs/Developer/retrune/export_engine.py) for behavior.
- Read the resolve, start-job, polling, and artifact-link logic in [`templates/index.html`](/Users/steven/Library/Mobile%20Documents/com~apple~CloudDocs/Developer/retrune/templates/index.html) after that so the end-to-end flow is clear.

### Senior Engineers

- The main architectural constraint is intentional simplicity: no persistence, no queue, no auth, no frontend build system.
- The main operational risks are external process management, temporary file handling, in-memory state, and server-side API key configuration.

### Contractors

- Favor scoped edits in `export_engine.py`, `app.py`, or `templates/index.html` rather than broad restructuring.
- If you need to introduce new moving parts, document the reason because this repo is optimized for minimalism.
