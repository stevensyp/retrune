# ReClip

A self-hosted, open-source media export console with a clean web UI. Paste links from YouTube, TikTok, Instagram, Twitter/X, and 1000+ other sites — download quick MP4/MP3 files, or run richer YouTube video/channel exports with transcripts and metadata.

![Python](https://img.shields.io/badge/python-3.8+-blue)
![License](https://img.shields.io/badge/license-MIT-green)

https://github.com/user-attachments/assets/419d3e50-c933-444b-8cab-a9724986ba05

![ReClip MP3 Mode](assets/preview-mp3.png)

## Features

- Download videos from 1000+ supported sites (via [yt-dlp](https://github.com/yt-dlp/yt-dlp))
- MP4 video or MP3 audio extraction for quick downloads
- YouTube channel, handle, video URL, and bare video ID detection
- Transcript exports as TXT, Markdown, or JSON
- Audio exports as MP3 or WAV
- Video exports as MP4 or MKV
- Optional single-video clipping
- Optional video and channel metadata artifacts
- Optional AssemblyAI transcript fallback when server credentials are configured
- Optional Gemini cleanup for YouTube auto captions when server credentials are configured
- Per-item quality/resolution picker
- Bulk downloads and channel exports
- Automatic URL deduplication
- Clean, responsive UI — no frameworks, no build step
- Python service-layer backend with Flask routes

## Quick Start

```bash
brew install yt-dlp ffmpeg    # or apt install ffmpeg && pip install yt-dlp
git clone https://github.com/averygan/reclip.git
cd reclip
./reclip.sh
```

Open **http://localhost:8899**.

For UI development with automatic server restart and browser refresh:

```bash
./reclip.sh --dev
```

Or with Docker:

```bash
docker build -t reclip . && docker run -p 8899:8899 reclip
```

## Usage

1. Paste one or more media URLs, a YouTube handle, a channel ID, or a video ID
2. Click **Analyze Input** to detect the workflow and load preview cards
3. Choose video, audio, or transcript export options
4. Start a full export or export an individual preview card
5. Download individual artifacts or the packaged ZIP when the job completes

## Supported Sites

Anything [yt-dlp supports](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md), including:

YouTube, TikTok, Instagram, Twitter/X, Reddit, Facebook, Vimeo, Twitch, Dailymotion, SoundCloud, Loom, Streamable, Pinterest, Tumblr, Threads, LinkedIn, and many more.

## Stack

- **Backend:** Python + Flask service layer
- **Frontend:** Vanilla HTML/CSS/JS (single file, no build step)
- **Download engine:** [yt-dlp](https://github.com/yt-dlp/yt-dlp) + [ffmpeg](https://ffmpeg.org/)
- **Dependencies:** 2 (Flask, yt-dlp)

Optional server-side environment variables:

- `RECLIP_PASSWORD` enables the private login page with a server-side password
- `RECLIP_PASSWORD_SHA256` enables the same login using a SHA-256 password digest instead of a raw password
- `RECLIP_AUTH_REQUIRED=1` makes production fail closed when no ReClip password is configured
- `SECRET_KEY` signs Flask sessions and is required when `RECLIP_AUTH_REQUIRED=1`
- `RECLIP_COOKIE_SECURE=1` marks auth cookies as HTTPS-only for production deployments
- `RECLIP_SESSION_HOURS` controls how long a browser stays signed in, defaulting to `720`
- `ASSEMBLYAI_API_KEY` enables transcript fallback beyond YouTube captions
- `GOOGLE_API_FREE` enables Gemini cleanup for YouTube auto captions
- `YTDLP_BIN` overrides the `yt-dlp` executable
- `FFMPEG_BIN` overrides the `ffmpeg` executable

## Engineering Notes

- [Onboarding guide](docs/ONBOARDING.md) for setup, architecture, and contribution guardrails

## Disclaimer

This tool is intended for personal use only. Please respect copyright laws and the terms of service of the platforms you download from. The developers are not responsible for any misuse of this tool.

## License

[MIT](LICENSE)
