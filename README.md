# Feedscript

A local-first desktop app that pulls a creator's top-performing short videos and turns them into a single searchable JSON of transcripts + metadata. Runs entirely on your own machine — no API keys, no cloud, no data leaving your computer.

Built for people who need to *read* a creator's content to analyze it, not watch hours of it: marketers, researchers, content strategists.

## Download

**macOS** — one-line install (skips the Gatekeeper prompt):
```bash
curl -fsSL https://raw.githubusercontent.com/smhammad/feedscript/main/install.sh | bash
```

Or grab the build directly from the [releases page](https://github.com/smhammad/feedscript/releases/latest):

- [`Feedscript-macOS.zip`](https://github.com/smhammad/feedscript/releases/latest/download/Feedscript-macOS.zip) — see first-launch instructions below
- [`Feedscript.exe`](https://github.com/smhammad/feedscript/releases/latest/download/Feedscript.exe) — Windows 10/11, double-click to run

Both builds are fully self-contained. First launch installs any missing system tools (ffmpeg) and downloads the Whisper transcription model (~460 MB, one-time).

## What it does

1. You log in with a throwaway account (cookies JSON or username+password).
2. Enter a target username. Set filters — date range, minimum likes / comments / views, sort order.
3. The app streams that account's videos into a table as they load.
4. Pick your top N. Click Transcribe.
5. While video 1 transcribes, video 2 is already downloading — a bounded queue keeps both phases running in parallel.
6. Output: one `<run_name>.json` containing every clip's caption, likes, comments, views, timestamp, and full transcript.

Ships as a native Mac app (`Feedscript.app`) and a Windows executable (`Feedscript.exe`) built from the same codebase.

## Why it's worth looking at

- **Runs entirely offline.** `openai-whisper` for transcription, `yt-dlp` for video download, `ffprobe` for the no-audio edge case. No external APIs. No tokens.
- **Real desktop app**, not a terminal tool. pywebview wraps a FastAPI server in a native WKWebView window on Mac / WebView2 on Windows. A setup wizard detects missing dependencies and installs them with live-streamed logs.
- **Pipelined download + transcribe.** A `queue.Queue(maxsize=3)` sits between a downloader thread and a transcriber thread so Whisper starts on clip 1 the instant it's on disk — roughly halving run time vs. sequential.
- **Minimal interface, ruthless scope.** Greyscale, no feature bloat. Filters work on streamed-in posts as they arrive. Single JSON output. A library tab with copy / export / delete / reveal-in-Finder actions.

## Install — macOS

### One-line install (recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/smhammad/feedscript/main/install.sh | bash
```

This downloads the latest release, strips the macOS quarantine attribute, and installs `Feedscript.app` into `/Applications` — no Gatekeeper prompt. Re-run the same command to update to a new release.

You can inspect the script first at [install.sh](install.sh) if you'd rather not pipe to `bash` blind — it's 40 lines.

### Homebrew tap

If you prefer the `brew` flow, a Homebrew Cask is available in this repo under [Casks/feedscript.rb](Casks/feedscript.rb). Homebrew doesn't install casks from raw URLs, so either clone this repo and point `brew install --cask` at the local file, or ask me to publish a proper `homebrew-feedscript` tap.

### Manual download

1. Download `Feedscript-macOS.zip` from the [latest release](https://github.com/smhammad/feedscript/releases/latest) and unzip it.
2. Drag `Feedscript.app` into `/Applications`.
3. **First-launch Gatekeeper step** — because the app isn't signed with a paid Apple Developer certificate, macOS refuses to open it until you remove the quarantine attribute. Run this once in Terminal:
   ```bash
   xattr -dr com.apple.quarantine /Applications/Feedscript.app
   ```
4. Double-click the app.

The setup wizard installs ffmpeg (via Homebrew) and the Whisper model (~460 MB, one-time). Subsequent launches open in about 2 seconds.

Alternative for developers: clone the repo and use `./start.command` for a terminal-based launcher.

## Install — Windows

Grab `Feedscript.exe` from the latest [release](https://github.com/smhammad/feedscript/releases/latest). The `.exe` bundles Python and every app component; the only one-time download is the Whisper model.

ffmpeg is installed via `winget` if missing — the setup wizard does it for you.

Alternative: clone the repo, install Python 3.11+, double-click `Feedscript.bat`.

## How it's wired

```
┌──────────────────────┐    JS bridge    ┌─────────────────┐
│  WKWebView / WebView2│ ──────────────> │   launcher.py   │
│   (pywebview window) │                 │   (Python)      │
└──────────────────────┘                 └────────┬────────┘
         │                                        │ spawns / imports
         ▼                                        ▼
┌──────────────────────┐                 ┌─────────────────┐
│  FastAPI server      │ ◄───────────────│   uvicorn       │
│  localhost:8765      │       SSE       │                 │
└──────────┬───────────┘                 └─────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────┐
│  Download thread  ──►  Queue(maxsize=3)  ──►  Whisper    │
│  (yt-dlp + cookies)                           (threaded) │
└──────────────────────────────────────────────────────────┘
```

- When running from source, `launcher.py` spawns uvicorn as a subprocess.
- When running from the PyInstaller `.exe`, uvicorn runs in-process on a background thread (no Python interpreter exists inside the bundle to subprocess to).
- Downloads stay in `output/<target>/_tmp_<run>/` and are deleted once transcribed.
- Instaloader session cookies are exported to a Netscape-format `cookies.txt` so yt-dlp can resolve URLs that require login.

## Responsible use

Feedscript downloads publicly-visible posts from platforms that may restrict automated access in their terms of service. Use it on content you have the right to analyze. Don't redistribute scraped media. I'm not responsible for how you use it.

## Stack

Python 3.11 · FastAPI · uvicorn · pywebview · instaloader · yt-dlp · openai-whisper · Pillow (icon gen) · PyInstaller (Windows builds)

## License

MIT — see [LICENSE](LICENSE).

## Contact

Shahzada Hammad — [LinkedIn](https://www.linkedin.com/in/shahzada-hammad/)
