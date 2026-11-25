# YT-Download — High-Quality YouTube Downloader with Paid-Account Support

[繁體中文](README.md) | **English**

Download YouTube videos, audio, subtitles, and playlists with **YouTube Premium / Channel Membership** authentication support. Available in both **Local Web UI** and **CLI** modes.

## Features

- **Dual Authentication Modes for Paid Accounts**:
  - **Import `cookies.txt` (Recommended)**: Automatic Netscape-format validation (checks for valid `SAPISID` / `LOGIN_INFO` cookies and expiration), bypassing Windows Chrome / Edge DPAPI App-Bound Encryption locks.
  - **Read from Local Browser**: Directly reads logged-in sessions from Firefox / Chrome / Edge / Brave / Opera / Vivaldi.
- **High-Quality Video**: Automatic detection and tagging of 4K / 1080p Premium (enhanced bitrate) streams, merged to MP4 via FFmpeg (Web UI defaults to 720p HD space-saving MP4).
- **Audio-Only Downloads**: Convert to highest-quality MP3 or lossless-remuxed M4A.
- **Subtitles (SRT)**: Enabled by default for Traditional Chinese & English (`zh-Hant, zh-TW, zh-HK, en, en-US`), supporting auto-generated/auto-translated captions, embedding into MP4, and **subtitles-only downloads**.
- **Playlist Batch Downloads**: Automatically organizes playlists into subfolders and supports custom item ranges (e.g. `1-5` or `1,3,5`).

---

## Requirements & Installation

This project requires Python 3.11+, [`uv`](https://docs.astral.sh/uv/), FFmpeg (for merging high-res streams and MP3 conversion), and Node.js / Deno (for YouTube signature solving):

```powershell
# Install dependencies
uv sync

# Check environment tools and cookies.txt status
uv run yt-dl check-auth
```

---

## Option 1: Launch Web UI (Recommended)

Run directly:

```powershell
uv run yt-dl web
```

Or use the one-click PowerShell script:

```powershell
.\start_web.ps1
```

The server listens only on `127.0.0.1` (default port `18000`, automatically falling back if unavailable) and opens your browser automatically so your cookies and downloads stay strictly local.

---

## Option 2: CLI Usage Examples

### 1. Inspect Available Formats (with 1080p Premium Detection)

```powershell
# Use default data/cookies.txt (if imported via Web UI)
uv run yt-dl info "https://www.youtube.com/watch?v=3zgm60bXmQk"

# Specify a custom cookies.txt file
uv run yt-dl info "https://www.youtube.com/watch?v=3zgm60bXmQk" -c .\cookies.txt

# Read cookies directly from a local browser
uv run yt-dl info "https://www.youtube.com/watch?v=3zgm60bXmQk" -b firefox
```

### 2. Download Video / Audio / Subtitles / Playlists

```powershell
# Best quality (4K / 1080p Premium) + SRT subtitles (subtitles enabled by default)
uv run yt-dl download "https://www.youtube.com/watch?v=3zgm60bXmQk" -p best

# Download subtitles only (SRT), without video or audio
uv run yt-dl download "https://www.youtube.com/watch?v=3zgm60bXmQk" --subtitles-only

# 1080p (preferring 1080p Premium) with embedded subtitles
uv run yt-dl download "https://www.youtube.com/watch?v=3zgm60bXmQk" -p 1080p --embed-subs

# Audio-only MP3
uv run yt-dl download "https://www.youtube.com/watch?v=3zgm60bXmQk" -p audio_mp3

# Download items 1 to 5 of a playlist
uv run yt-dl download "https://www.youtube.com/playlist?list=XXXX" --playlist --playlist-items 1-5
```

---

## How to Safely Export `cookies.txt`

Since Chrome / Edge v127 on Windows enables App-Bound Encryption, direct browser database extraction often fails. Exporting `cookies.txt` is recommended:

1. Install the open-source browser extension **Get cookies.txt LOCALLY**.
2. Sign in to your YouTube Premium / member account and open `https://www.youtube.com`.
3. Click the extension icon → click **Export** to save `youtube.com_cookies.txt`.
4. Upload it in the Web UI under **1. Paid Account Authentication**, or pass `-c youtube.com_cookies.txt` in the CLI.

> **Security Note**: `cookies.txt`, `data/`, and `downloads/` are excluded via `.gitignore`. Never commit your `cookies.txt` to Git or share it with others.

> **DRM Note**: YouTube Premium (1080p Enhanced Bitrate), channel-member videos, age-restricted, and private videos are supported with valid account cookies. Widevine DRM-protected "YouTube Movies & TV" rentals/purchases cannot be decrypted by `yt-dlp`.

---

## License

This project is licensed under the [MIT License](LICENSE).
