# ReClip Onboarding

> Practical onboarding for engineers working on the `retrune` fork of ReClip, a small self-hosted media downloader built with Flask and a single-file frontend.

## What This Repo Is

This repository is a lightweight web app for downloading media through `yt-dlp` and `ffmpeg`. The app serves one HTML page, exposes a small JSON API, and stores active job state in memory while downloads run in background threads.

This fork currently tracks the upstream ReClip project shape closely:

- `origin`: `https://github.com/stevensyp/retrune.git`
- `upstream`: `https://github.com/averygan/reclip.git`

## Quick Start

### Prerequisites

| Tool | Notes |
|------|-------|
| `python3` | Required for local runs and `reclip.sh` |
| `yt-dlp` | Required for metadata fetches and downloads |
| `ffmpeg` | Required for audio extraction and media merging |
| Docker | Optional, for containerized runs |

### Fastest Local Setup

```bash
brew install yt-dlp ffmpeg
./reclip.sh
```

`reclip.sh` checks for `python3`, `yt-dlp`, and `ffmpeg`, creates `venv/` on first run, installs `flask` and `yt-dlp`, and starts the Flask server on port `8899`.

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
3. Paste a supported URL and click `Fetch`.
4. Confirm the page renders a card with title, thumbnail, and format options.

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
  +-> `POST /api/info` -> runs `yt-dlp -j` for metadata
  +-> `POST /api/download` -> starts background download thread
  +-> `GET /api/status/<job_id>` -> polls in-memory job state
  +-> `GET /api/file/<job_id>` -> serves final file from `downloads/`
```

### Runtime Model

- The backend is a single Flask process in [`app.py`](/Users/steven/Library/Mobile%20Documents/com~apple~CloudDocs/Developer/retrune/app.py).
- Download jobs are tracked in a module-level `jobs` dictionary.
- Each download runs in a daemon thread created by `/api/download`.
- Files are written to `downloads/`, which is created at startup and ignored by Git.
- There is no database, queue, authentication layer, or persistent job history.

### Main Request Flow

1. The user pastes one or more URLs into the page served from [`templates/index.html`](/Users/steven/Library/Mobile%20Documents/com~apple~CloudDocs/Developer/retrune/templates/index.html).
2. Frontend JavaScript calls `POST /api/info` to fetch metadata and available resolutions.
3. When the user clicks download, the frontend calls `POST /api/download`.
4. The backend spawns a thread that runs `yt-dlp` and optionally `ffmpeg`.
5. The frontend polls `GET /api/status/<job_id>` until the job is `done`.
6. The browser downloads the file from `GET /api/file/<job_id>`.

## Tech Stack

| Layer | Technology | Notes |
|------|------------|-------|
| Backend | Flask | Single app file, no blueprints |
| Frontend | Vanilla HTML/CSS/JS | Embedded in one template |
| Media engine | `yt-dlp` + `ffmpeg` | External system dependencies |
| Packaging | `venv` script + Docker | No build pipeline |
| Assets | Static image/video previews | Marketing/demo only |

## Key Files

| Path | Purpose |
|------|---------|
| [`app.py`](/Users/steven/Library/Mobile%20Documents/com~apple~CloudDocs/Developer/retrune/app.py) | Flask app, API routes, download orchestration |
| [`templates/index.html`](/Users/steven/Library/Mobile%20Documents/com~apple~CloudDocs/Developer/retrune/templates/index.html) | Entire UI, styling, and client-side logic |
| [`reclip.sh`](/Users/steven/Library/Mobile%20Documents/com~apple~CloudDocs/Developer/retrune/reclip.sh) | Local bootstrap script for first-run setup |
| [`requirements.txt`](/Users/steven/Library/Mobile%20Documents/com~apple~CloudDocs/Developer/retrune/requirements.txt) | Python dependencies |
| [`Dockerfile`](/Users/steven/Library/Mobile%20Documents/com~apple~CloudDocs/Developer/retrune/Dockerfile) | Containerized runtime |
| [`static/favicon.svg`](/Users/steven/Library/Mobile%20Documents/com~apple~CloudDocs/Developer/retrune/static/favicon.svg) | Favicon asset |
| [`assets/`](/Users/steven/Library/Mobile%20Documents/com~apple~CloudDocs/Developer/retrune/assets) | README/demo assets |

## Common Developer Tasks

### Change download behavior

Edit [`app.py`](/Users/steven/Library/Mobile%20Documents/com~apple~CloudDocs/Developer/retrune/app.py) in:

- `run_download(...)` for format selection, output naming, and cleanup behavior
- `get_info()` for metadata parsing and resolution filtering

### Change the UI

Edit [`templates/index.html`](/Users/steven/Library/Mobile%20Documents/com~apple~CloudDocs/Developer/retrune/templates/index.html). The template contains:

- the page markup
- all CSS styles
- all browser-side fetch, render, and polling logic

There is no frontend build step, so refresh-based iteration is enough.

### Change local startup behavior

Edit [`reclip.sh`](/Users/steven/Library/Mobile%20Documents/com~apple~CloudDocs/Developer/retrune/reclip.sh) if you need to:

- add prerequisite checks
- change first-run dependency installation
- change the default port export

### Change container behavior

Edit [`Dockerfile`](/Users/steven/Library/Mobile%20Documents/com~apple~CloudDocs/Developer/retrune/Dockerfile) if you need to:

- install extra system packages
- change the base Python image
- expose different runtime defaults

## Debugging Guide

### Common Failure Modes

- `yt-dlp: command not found`
  Install `yt-dlp` locally, or use the Docker image.

- `ffmpeg: command not found`
  Install `ffmpeg`; MP3 extraction and merged video downloads depend on it.

- Fetch succeeds but download fails
  Check the final stderr line returned by `yt-dlp` in the UI error state.

- Job disappears after restart
  Expected: job state only lives in the in-memory `jobs` dict.

- File is downloaded with an odd name
  Filename generation is derived from the title and trimmed aggressively for safety.

### Useful Places To Inspect

- Backend logs: the terminal running Flask
- API behavior: browser devtools network tab
- Generated files: `downloads/`

### Quick Syntax Checks

```bash
python3 -m py_compile app.py
bash -n reclip.sh
```

These are lightweight checks when you want confidence without adding test infrastructure.

## Contribution Guardrails

### What To Preserve

- Keep the no-build, low-dependency shape unless there is a strong reason to expand it.
- Preserve the simple request flow between the single template and the small Flask API.
- Treat external command execution as the main failure surface and handle errors clearly.

### Review Checklist

- Local startup still works through `./reclip.sh` or Docker.
- The homepage still loads on `localhost:8899`.
- Metadata fetch still returns title, thumbnail, and format choices.
- Download completion still yields a real file in `downloads/`.

## Audience Notes

### Junior Engineers

- Start with [`app.py`](/Users/steven/Library/Mobile%20Documents/com~apple~CloudDocs/Developer/retrune/app.py) first; most backend behavior lives there.
- Read the fetch and polling calls in [`templates/index.html`](/Users/steven/Library/Mobile%20Documents/com~apple~CloudDocs/Developer/retrune/templates/index.html) after that so the end-to-end flow is clear.

### Senior Engineers

- The main architectural constraint is intentional simplicity: no persistence, no queue, no auth, no build system.
- The main operational risks are external process management, temporary file handling, and in-memory state.

### Contractors

- Favor scoped edits in either `app.py` or `templates/index.html` rather than broad restructuring.
- If you need to introduce new moving parts, document the reason because this repo is optimized for minimalism.
