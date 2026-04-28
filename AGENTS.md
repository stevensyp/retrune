# AGENTS.md

## Scope
- Work from the current Flask app, `README.md`, and `docs/ONBOARDING.md`; ignore `CLAUDE.md` if present.
- Do not touch generated/runtime state: `venv/`, `downloads/`, `__pycache__/`, `.DS_Store`, or `.env*`.
- Preserve the self-hosted, no-build frontend shape unless the task explicitly changes that direction.

## Architecture
- Keep `app.py` as the thin Flask layer: route parsing, JSON responses, artifact serving, dev reload, and legacy API wrappers.
- Put reusable media behavior in `export_engine.py`: input detection, `yt-dlp`/`ffmpeg`, jobs, transcripts, metadata, AssemblyAI, Gemini, and ZIP packaging.
- Treat `templates/index.html` as the entire web UI: markup, CSS, state, resolve/start/poll logic, and artifact links all live there.
- Runtime exports are written to `downloads/jobs/<job-id>/` with `files/`, `.tmp/`, artifacts, and `export.zip`.
- `JobStore` is in-memory only; restarting Flask loses job status even when files remain on disk.

## API And Data Flow
- Preserve the main flow: `POST /api/resolve` -> `POST /api/jobs` -> poll `GET /api/jobs/<job_id>` -> download artifact/ZIP routes.
- Keep legacy wrappers `/api/info`, `/api/download`, `/api/status/<job_id>`, and `/api/file/<job_id>` unless intentionally migrating clients.
- Support both generic `yt-dlp` URLs and YouTube-specific inputs: URLs, handles, channel IDs, bare 11-character video IDs, and channel exports.
- Keep bulk input deduplication, quick MP4/MP3 jobs, per-item video format selection, clipping, transcripts, metadata artifacts, and ZIP packaging working together.

## Environment And Integrations
- `YTDLP_BIN` and `FFMPEG_BIN` override external executable names; otherwise `yt-dlp` and `ffmpeg` must be on `PATH`.
- `ASSEMBLYAI_API_KEY` enables AssemblyAI transcript fallback; `MAX_ASSEMBLYAI_JOBS = 5` caps concurrent AssemblyAI work.
- `GOOGLE_API_FREE` enables Gemini caption cleanup; `GEMINI_MODEL` defaults in `export_engine.py`.
- Keep API keys server-side. Do not add browser fields or persisted client state for AssemblyAI or Google credentials.
- `PORT` controls the local port, `HOST` controls binding, and Docker sets `HOST=0.0.0.0`.

## Developer Workflow
- Start locally with `./reclip.sh`; it checks `python3`, `yt-dlp`, `ffmpeg`, creates/activates `venv/`, installs Flask/yt-dlp, and runs `python3 app.py`.
- For UI work, use `./reclip.sh --dev`; it sets `RECLIP_DEV_RELOAD=1`, stops an existing listener on `PORT`, opens `http://localhost:8899`, and enables browser auto-refresh for `app.py`, `export_engine.py`, `templates/`, and `static/`.
- Manual setup: `python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt && python3 app.py`.
- Docker path: `docker build -t reclip . && docker run -p 8899:8899 reclip`.
- There is no committed automated test suite; use smoke checks or Flask’s test client for route changes rather than adding test infrastructure by default.

## Verification
- Python syntax: `venv/bin/python -m py_compile app.py export_engine.py`.
- Shell syntax: `bash -n reclip.sh`.
- Inline UI script: extract `<script>` blocks from `templates/index.html` and run `node --check` when Node is available.
- Use `git diff --check` before committing; do not commit downloads, venv files, bytecode, or secrets.

## Editing Guidance
- Keep route handlers small and move reusable behavior to `export_engine.py` so future CLI/API entrypoints can share the engine.
- Edit `templates/index.html` directly for UI changes; there is no bundler, package manager, or generated frontend asset pipeline.
- Update `README.md` and `docs/ONBOARDING.md` when changing commands, env vars, output layout, artifact names, or user-facing options.
- Treat external command failures as expected user-facing errors; preserve concise messages from `yt-dlp`, `ffmpeg`, AssemblyAI, and Gemini paths.
