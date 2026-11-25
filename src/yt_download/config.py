from __future__ import annotations

import shutil
from enum import Enum
from pathlib import Path

# 專案根目錄（src/yt_download/config.py -> 往上 3 層）
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DOWNLOADS_DIR = PROJECT_ROOT / "downloads"
DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_COOKIES_FILE = DATA_DIR / "cookies.txt"

SUPPORTED_BROWSERS = ("chrome", "edge", "firefox", "brave", "opera", "vivaldi")
DEFAULT_SUBTITLE_LANGS = ["zh-Hant", "zh-TW", "zh-HK", "en"]


class AuthMode(str, Enum):
    COOKIES_FILE = "cookies_file"
    BROWSER = "browser"
    NONE = "none"


class QualityPreset(str, Enum):
    BEST = "best"
    UHD_4K = "4k"
    FHD_1080P = "1080p"
    HD_720P = "720p"
    AUDIO_MP3 = "audio_mp3"
    AUDIO_M4A = "audio_m4a"
    SUBTITLES_ONLY = "subtitles_only"


PRESET_LABELS: dict[QualityPreset, str] = {
    QualityPreset.BEST: "最高畫質（自動含 4K / 1080p Premium，合併 MP4）",
    QualityPreset.UHD_4K: "4K 2160p（若無則自動降階，合併 MP4）",
    QualityPreset.FHD_1080P: "1080p Full HD（優先 1080p Premium 高位元率）",
    QualityPreset.HD_720P: "720p HD（省空間 MP4）",
    QualityPreset.AUDIO_MP3: "純音訊 MP3（最高音質）",
    QualityPreset.AUDIO_M4A: "純音訊 M4A（原音質封裝）",
    QualityPreset.SUBTITLES_ONLY: "純字幕 SRT（僅下載字幕，不下載影片）",
}


def ensure_runtime_dirs() -> None:
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def detect_environment() -> dict[str, str | bool | None]:
    ffmpeg_path = shutil.which("ffmpeg")
    node_path = shutil.which("node")
    deno_path = shutil.which("deno")
    return {
        "ffmpeg_available": bool(ffmpeg_path),
        "ffmpeg_path": ffmpeg_path,
        "node_available": bool(node_path),
        "node_path": node_path,
        "deno_available": bool(deno_path),
        "deno_path": deno_path,
    }
