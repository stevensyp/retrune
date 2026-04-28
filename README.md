# ReClip / Retrune

A self-hosted media export console for downloading videos, audio, transcripts, metadata, and ZIP bundles from YouTube and other sites supported by `yt-dlp`.

This fork is a Flask app with a no-build frontend, an in-memory job store, optional password protection, and experimental Cloudflare deployment wiring.

## Features

- Download media from YouTube and 1000+ `yt-dlp` supported sites
- Quick MP4/MP3 exports
- YouTube video, channel, handle, and bare video ID detection
- Bulk URL input with deduplication
- Per-video format selection
- Transcript exports as TXT, Markdown, or JSON
- Audio exports as MP3 or WAV
- Video exports as MP4 or MKV
- Optional single-video clipping
- Optional metadata artifacts
- ZIP packaging for completed jobs
- Optional AssemblyAI transcript fallback
- Optional Gemini cleanup for YouTube auto captions
- Optional private login gate with server-side password and lockout

## Local Start

Install system tools:

```bash
brew install yt-dlp ffmpeg
```

Run the app:

```bash
./reclip.sh
```

Open [http://localhost:8899](http://localhost:8899).

For local UI work with auto-reload:

```bash
./reclip.sh --dev
```

Manual setup:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 app.py
```

## Password Protection

Auth is disabled unless a password env var is set.

Use a raw password:

```bash
export RECLIP_PASSWORD='change-me'
export SECRET_KEY="$(openssl rand -hex 32)"
export RECLIP_AUTH_REQUIRED=1
python3 app.py
```

Or use a SHA-256 digest instead of passing the raw password to the process:

```bash
export RECLIP_PASSWORD_SHA256="$(printf '%s' 'change-me' | shasum -a 256 | awk '{print $1}')"
export SECRET_KEY="$(openssl rand -hex 32)"
export RECLIP_AUTH_REQUIRED=1
python3 app.py
```

Relevant auth variables:

- `RECLIP_PASSWORD`: enables login with a server-side password
- `RECLIP_PASSWORD_SHA256`: enables login with a SHA-256 password digest
- `RECLIP_AUTH_REQUIRED=1`: fail closed if no password is configured
- `SECRET_KEY`: signs Flask sessions; required when `RECLIP_AUTH_REQUIRED=1`
- `RECLIP_COOKIE_SECURE=1`: mark session cookies HTTPS-only
- `RECLIP_SESSION_HOURS`: browser session lifetime, default `720`

Do not commit passwords, API keys, `.env*`, or Cloudflare local state.

## Optional Integrations

- `ASSEMBLYAI_API_KEY`: enables AssemblyAI transcript fallback
- `GOOGLE_API_FREE`: enables Gemini caption cleanup
- `GEMINI_MODEL`: overrides the Gemini model
- `YTDLP_BIN`: overrides the `yt-dlp` executable
- `FFMPEG_BIN`: overrides the `ffmpeg` executable
- `PORT`: local port, default `8899`
- `HOST`: bind host, default `127.0.0.1`

## Docker

The Docker image includes `ffmpeg` and installs Python requirements:

```bash
docker build -t retrune .
docker run -p 8899:8899 \
  -e HOST=0.0.0.0 \
  -e RECLIP_PASSWORD='change-me' \
  -e SECRET_KEY="$(openssl rand -hex 32)" \
  -e RECLIP_AUTH_REQUIRED=1 \
  retrune
```

`.dockerignore` excludes runtime and local development directories such as `downloads/`, `venv/`, `node_modules/`, and `.wrangler/`.

## Cloudflare

There are two Cloudflare-related paths in the current project.

### Worker Proxy

A deployed Worker can proxy requests to a running Flask origin. This is the shape currently used for the live `workers.dev` URL. The Worker itself does not run `yt-dlp` or `ffmpeg`; it forwards traffic to a Flask process.

The proxy source used for this project is intentionally tiny: it rewrites the request to an `ORIGIN_URL` and lets Flask handle auth, API routes, downloads, and jobs.

### Cloudflare Containers

The repo includes experimental Cloudflare Containers config:

- [wrangler.jsonc](wrangler.jsonc)
- [src/index.js](src/index.js)
- [Dockerfile](Dockerfile)
- [package.json](package.json)

The intended command is:

```bash
npm install
npx wrangler deploy
```

This builds the Docker image, pushes it to Cloudflare's container registry, and deploys a Worker that forwards traffic to the containerized Flask app.

Current known blocker: Cloudflare returned `Unauthorized` for the Containers API on this account during deployment, even though the Worker upload and local Docker build succeeded. Until Containers access is enabled for the account/token, use local Docker, direct Flask hosting, or a Worker proxy to a reachable Flask origin.

## Runtime Model

- Flask routes live in [app.py](app.py)
- Export logic lives in [export_engine.py](export_engine.py)
- The whole frontend lives in [templates/index.html](templates/index.html)
- Login page lives in [templates/login.html](templates/login.html)
- Jobs are stored in memory by `JobStore`
- Artifacts are written to `downloads/jobs/<job-id>/`
- Restarting Flask clears in-memory job status, even if files remain on disk

Main flow:

```text
POST /api/resolve
POST /api/jobs
GET  /api/jobs/<job_id>
GET  /api/jobs/<job_id>/artifacts/<artifact_id>
GET  /api/jobs/<job_id>/zip
```

Legacy routes are still present:

```text
POST /api/info
POST /api/download
GET  /api/status/<job_id>
GET  /api/file/<job_id>
```

## Verification

Use these checks before pushing:

```bash
venv/bin/python -m py_compile app.py export_engine.py
bash -n reclip.sh
tmpfile=$(mktemp /tmp/retrune-inline-js.XXXXXX.js)
awk '/<script>/{in_script=1; next} /<\\/script>/{in_script=0} in_script{print}' templates/index.html > "$tmpfile"
node --check "$tmpfile"
rm -f "$tmpfile"
git diff --check
```

There is no committed automated test suite. Prefer smoke checks or Flask's test client for route changes rather than adding unit-test infrastructure by default.

## Security Notes

- Keep API keys and login passwords server-side.
- Do not add browser fields for AssemblyAI, Gemini, or login secrets.
- The login gate is a lightweight private-access layer, not multi-user identity management.
- Failed login attempts are locked out progressively per client IP in memory.
- Use `RECLIP_COOKIE_SECURE=1` only behind HTTPS.

## Disclaimer

This tool is intended for personal use. Respect copyright law and the terms of service of the platforms you access. The developers are not responsible for misuse.

## License

[MIT](LICENSE)
