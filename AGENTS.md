# AGENTS.md

## Scope
- Work from the current Flask/Python code, `README.md`, and `docs/ONBOARDING.md`.
- Ignore generated runtime state: `venv/`, `downloads/`, `__pycache__/`, `.DS_Store`, and any `.env*` files.
- Keep the app self-hosted and no-build on the frontend unless the task explicitly changes that direction.

## Architecture
- `app.py` is the thin Flask route layer. Keep request parsing, response shaping, and compatibility wrappers there.
- `export_engine.py` owns media behavior: input detection, `yt-dlp`/`ffmpeg` commands, job state, transcripts, metadata, AssemblyAI, Gemini cleanup, and ZIP packaging.
- `templates/index.html` is the entire web UI: markup, CSS, and browser-side resolve/start/poll/download logic.
- Runtime exports live under `downloads/jobs/<job-id>/` with `files/`, `.tmp/`, artifacts, and `export.zip`.
- `JobStore` is in-memory only. Restarting the Flask process loses job status even if files remain on disk.

## API Behavior To Preserve
- New UI/API flow uses `POST /api/resolve`, `POST /api/jobs`, `GET /api/jobs/<job_id>`, artifact downloads, and ZIP downloads.
- Legacy endpoints `/api/info`, `/api/download`, `/api/status/<job_id>`, and `/api/file/<job_id>` are compatibility wrappers; do not remove them casually.
- Generic `yt-dlp` URLs, bulk URL deduplication, quick MP4/MP3 downloads, and per-item quality selection must continue to work.
- YouTube-specific flows support handles, channel URLs/IDs, video URLs, bare 11-char video IDs, transcripts, clipping, metadata, and channel exports.

## Environment And Integrations
- `YTDLP_BIN` and `FFMPEG_BIN` override executable names; otherwise `yt-dlp` and `ffmpeg` are expected on `PATH`.
- `ASSEMBLYAI_API_KEY` enables transcript fallback beyond YouTube captions.
- `GOOGLE_API_FREE` enables Gemini cleanup for YouTube auto captions.
- Keep API keys server-side. Do not add UI fields that collect AssemblyAI or Google keys from users.
- AssemblyAI concurrency is capped by `MAX_ASSEMBLYAI_JOBS = 5` in `export_engine.py`.

## Developer Workflow
- Run locally with `./reclip.sh`; it creates/activates `venv/`, installs Flask and yt-dlp, then starts `python3 app.py`.
- Manual setup: `python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt && python3 app.py`.
- Docker path: `docker build -t reclip . && docker run -p 8899:8899 reclip`.
- Lightweight checks: `venv/bin/python -m py_compile app.py export_engine.py`, `bash -n reclip.sh`, and extract/check the inline script in `templates/index.html` with `node --check` when Node is available.
- There is no committed automated test suite. Prefer smoke checks through Flask’s test client for route changes.

## Repo-Specific Editing Guidance
- Put reusable behavior in `export_engine.py`; keep Flask routes thin so future CLI/API entrypoints can reuse the engine.
- When changing frontend behavior, update `templates/index.html` directly; there is no bundler, package manager, or generated asset pipeline.
- When changing output layout, artifact names, env vars, or user-facing options, update both `README.md` and `docs/ONBOARDING.md`.
- Treat external command failures as normal user-facing errors. Preserve concise messages from `yt-dlp`, `ffmpeg`, AssemblyAI, and Gemini paths.
- Do not commit generated downloads, local virtualenvs, Python bytecode, or secrets.
