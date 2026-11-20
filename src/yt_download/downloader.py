from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yt_dlp

from yt_download.auth import AuthConfig, apply_auth_to_ydl_opts, classify_yt_error
from yt_download.config import (
    DEFAULT_SUBTITLE_LANGS,
    DOWNLOADS_DIR,
    QualityPreset,
    detect_environment,
)


class DownloadCancelledError(Exception):
    """使用者主動取消下載時拋出。"""


@dataclass
class DownloadOptions:
    url: str
    preset: QualityPreset = QualityPreset.BEST
    format_id: str | None = None
    output_dir: Path = DOWNLOADS_DIR
    subtitles: bool = False
    auto_subtitles: bool = True
    subtitle_langs: list[str] = field(default_factory=lambda: list(DEFAULT_SUBTITLE_LANGS))
    embed_subtitles: bool = False
    allow_playlist: bool = False
    playlist_items: str | None = None
    auth: AuthConfig = field(default_factory=AuthConfig)


def _format_selector_for_preset(preset: QualityPreset, format_id: str | None = None) -> str:
    if format_id and format_id.strip():
        fid = format_id.strip()
        # 若使用者選了純視訊 format_id，自動補上最佳音訊合併
        return f"{fid}+ba/{fid}/bv*+ba/b"

    mapping = {
        QualityPreset.BEST: "bv*+ba/b",
        QualityPreset.UHD_4K: "bv*[height<=2160]+ba/b[height<=2160]/bv*+ba/b",
        QualityPreset.FHD_1080P: "bv*[height<=1080]+ba/b[height<=1080]/bv*+ba/b",
        QualityPreset.HD_720P: "bv*[height<=720]+ba/b[height<=720]/bv*+ba/b",
        QualityPreset.AUDIO_MP3: "ba/b",
        QualityPreset.AUDIO_M4A: "ba[ext=m4a]/ba/b",
    }
    return mapping[preset]


def _base_ydl_opts(auth: AuthConfig) -> dict[str, Any]:
    env = detect_environment()
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "retries": 10,
        "fragment_retries": 10,
        "file_access_retries": 15,
        "retry_sleep_functions": {
            "http": lambda n: min(2.0 * n, 10.0),
            "fragment": lambda n: min(2.0 * n, 10.0),
            "file_access": lambda n: min(1.0 * n, 5.0),
        },
        "nopart": True,
        "overwrites": True,
        "http_chunk_size": 10 * 1024 * 1024,  # 10MB 分塊下載，避免企業 Proxy 截斷或限速
        "windowsfilenames": True,
        # 單連線循序下載對企業網路/Proxy 較穩定，減少 WinError 10054 斷線與限速
        "concurrent_fragment_downloads": 1,
    }
    # 啟用 Node.js / Deno 作為 yt-dlp JS runtime，以穩定解析 YouTube 簽章
    js_runtimes: dict[str, dict[str, Any]] = {}
    if env["node_available"]:
        js_runtimes["node"] = {}
    if env["deno_available"]:
        js_runtimes["deno"] = {}
    if js_runtimes:
        opts["js_runtimes"] = js_runtimes

    return apply_auth_to_ydl_opts(opts, auth)


def build_ydl_opts(
    options: DownloadOptions,
    progress_hook: Callable[[dict[str, Any]], None] | None = None,
    postprocessor_hook: Callable[[dict[str, Any]], None] | None = None,
    temp_dir: Path | None = None,
) -> dict[str, Any]:
    """根據下載設定組裝完整的 yt-dlp options。"""
    output_dir = Path(options.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    opts = _base_ydl_opts(options.auth)
    opts["format"] = _format_selector_for_preset(options.preset, options.format_id)
    opts["noplaylist"] = not options.allow_playlist

    paths: dict[str, str] = {"home": str(output_dir)}
    if temp_dir is not None:
        Path(temp_dir).mkdir(parents=True, exist_ok=True)
        paths["temp"] = str(temp_dir)
    opts["paths"] = paths

    if options.allow_playlist:
        opts["outtmpl"] = "%(playlist_title|Playlist)s/%(playlist_index|00)02d - %(title).150s [%(id)s].%(ext)s"
        if options.playlist_items and options.playlist_items.strip():
            opts["playlist_items"] = options.playlist_items.strip()
    else:
        opts["outtmpl"] = "%(title).150s [%(id)s].%(ext)s"

    postprocessors: list[dict[str, Any]] = []

    if options.preset == QualityPreset.AUDIO_MP3:
        postprocessors.append(
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "0",
            }
        )
        postprocessors.append({"key": "FFmpegMetadata"})
    elif options.preset == QualityPreset.AUDIO_M4A:
        postprocessors.append(
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "m4a",
                "preferredquality": "0",
            }
        )
        postprocessors.append({"key": "FFmpegMetadata"})
    else:
        opts["merge_output_format"] = "mp4"
        # 優先順序：解析度 > FPS > 位元率（確保 1080p Premium 與高碼率 H.264 優先於低碼率 AV1）> H.264/VP9 > AAC/M4A
        opts["format_sort"] = ["res", "fps", "tbr", "vcodec:h264,vp9", "acodec:aac,m4a"]
        postprocessors.append({"key": "FFmpegMetadata"})

    # 字幕設定（純音訊模式不嵌入字幕，但若勾選仍可下載 .srt）
    if options.subtitles:
        langs = options.subtitle_langs or list(DEFAULT_SUBTITLE_LANGS)
        opts["writesubtitles"] = True
        opts["writeautomaticsub"] = bool(options.auto_subtitles)
        opts["subtitleslangs"] = langs
        opts["subtitlesformat"] = "srt/vtt/best"
        postprocessors.append(
            {
                "key": "FFmpegSubtitlesConvertor",
                "format": "srt",
            }
        )
        if options.embed_subtitles and options.preset not in (
            QualityPreset.AUDIO_MP3,
            QualityPreset.AUDIO_M4A,
        ):
            opts["embedsubtitles"] = True

    if postprocessors:
        opts["postprocessors"] = postprocessors

    if progress_hook:
        opts["progress_hooks"] = [progress_hook]
    if postprocessor_hook:
        opts["postprocessor_hooks"] = [postprocessor_hook]

    return opts


def _summarize_formats(raw_formats: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """整理可用的高畫質視訊與音訊格式清單，標記 1080p Premium 等付費串流。"""
    video_items: list[dict[str, Any]] = []
    audio_items: list[dict[str, Any]] = []

    for fmt in raw_formats:
        vcodec = fmt.get("vcodec") or "none"
        acodec = fmt.get("acodec") or "none"
        format_id = str(fmt.get("format_id") or "")
        ext = fmt.get("ext") or ""
        note = fmt.get("format_note") or ""
        height = fmt.get("height")
        fps = fmt.get("fps")
        tbr = fmt.get("tbr")
        filesize = fmt.get("filesize") or fmt.get("filesize_approx")

        is_premium = "premium" in note.lower()

        if vcodec != "none" and height:
            video_items.append(
                {
                    "format_id": format_id,
                    "type": "video",
                    "ext": ext,
                    "height": height,
                    "fps": fps,
                    "vcodec": vcodec.split(".")[0],
                    "tbr": round(tbr, 1) if isinstance(tbr, (int, float)) else None,
                    "filesize": filesize,
                    "note": note,
                    "is_premium": is_premium,
                    "label": (
                        f"{height}p{f'{int(fps)}' if fps and fps > 30 else ''}"
                        f"{' ★ Premium' if is_premium else ''} "
                        f"({ext}, {vcodec.split('.')[0]}"
                        f"{f', {round(tbr)}kbps' if isinstance(tbr, (int, float)) else ''})"
                    ),
                }
            )
        elif vcodec == "none" and acodec != "none":
            abr = fmt.get("abr") or tbr
            audio_items.append(
                {
                    "format_id": format_id,
                    "type": "audio",
                    "ext": ext,
                    "acodec": acodec.split(".")[0],
                    "abr": round(abr, 1) if isinstance(abr, (int, float)) else None,
                    "filesize": filesize,
                    "note": note,
                    "is_premium": False,
                    "label": (
                        f"音訊 ({ext}, {acodec.split('.')[0]}"
                        f"{f', {round(abr)}kbps' if isinstance(abr, (int, float)) else ''})"
                    ),
                }
            )

    # 依解析度、Premium 優先、位元率排序，並去重保留每個解析度+編碼最佳串流
    video_items.sort(
        key=lambda x: (
            x["height"] or 0,
            1 if x["is_premium"] else 0,
            x["fps"] or 0,
            x["tbr"] or 0,
        ),
        reverse=True,
    )
    dedup_videos: list[dict[str, Any]] = []
    seen_video_keys: set[tuple[Any, ...]] = set()
    for item in video_items:
        key = (item["height"], item["is_premium"], item["vcodec"])
        if key not in seen_video_keys:
            seen_video_keys.add(key)
            dedup_videos.append(item)
        if len(dedup_videos) >= 12:
            break

    audio_items.sort(key=lambda x: x["abr"] or 0, reverse=True)
    return dedup_videos + audio_items[:4]


def probe_url(url: str, auth: AuthConfig, allow_playlist: bool = False) -> dict[str, Any]:
    """解析 YouTube 網址，回傳影片/播放清單資訊、可用畫質（含 Premium 標記）與字幕語系。"""
    opts = _base_ydl_opts(auth)
    opts["noplaylist"] = not allow_playlist
    if allow_playlist:
        opts["extract_flat"] = "in_playlist"

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        raise RuntimeError(classify_yt_error(str(exc))) from exc

    if not info:
        raise RuntimeError("無法解析此網址的影片資訊。")

    is_playlist = info.get("_type") == "playlist" or "entries" in info
    if is_playlist:
        entries_raw = [e for e in (info.get("entries") or []) if e]
        entries = [
            {
                "index": idx + 1,
                "id": entry.get("id"),
                "title": entry.get("title") or f"影片 #{idx + 1}",
                "duration": entry.get("duration"),
                "url": entry.get("url") or entry.get("webpage_url"),
            }
            for idx, entry in enumerate(entries_raw[:100])
        ]
        return {
            "is_playlist": True,
            "id": info.get("id"),
            "title": info.get("title") or "未命名播放清單",
            "uploader": info.get("uploader") or info.get("channel") or "",
            "webpage_url": info.get("webpage_url") or url,
            "thumbnail": info.get("thumbnail"),
            "entry_count": len(entries_raw),
            "entries": entries,
            "formats": [],
            "has_premium_format": False,
            "subtitles": [],
            "auto_subtitles": [],
            "availability": info.get("availability"),
        }

    formats = _summarize_formats(info.get("formats") or [])
    has_premium = any(f.get("is_premium") for f in formats)
    manual_subs = sorted((info.get("subtitles") or {}).keys())
    auto_subs = sorted((info.get("automatic_captions") or {}).keys())

    return {
        "is_playlist": False,
        "id": info.get("id"),
        "title": info.get("title") or "未命名影片",
        "uploader": info.get("uploader") or info.get("channel") or "",
        "duration": info.get("duration"),
        "view_count": info.get("view_count"),
        "webpage_url": info.get("webpage_url") or url,
        "thumbnail": info.get("thumbnail"),
        "availability": info.get("availability"),
        "has_premium_format": has_premium,
        "formats": formats,
        "subtitles": manual_subs,
        "auto_subtitles": auto_subs[:30],
    }


def download_media(
    options: DownloadOptions,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    """執行下載，支援進度回呼與取消事件，並回傳已下載檔案清單。"""
    downloaded_files: list[str] = []
    last_info: dict[str, Any] = {}

    def _check_cancel() -> None:
        if cancel_event and cancel_event.is_set():
            raise DownloadCancelledError("下載已由使用者取消。")

    def _progress_hook(d: dict[str, Any]) -> None:
        _check_cancel()
        status = d.get("status")
        total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
        downloaded = d.get("downloaded_bytes") or 0
        percent = round((downloaded / total) * 100, 1) if total > 0 else None

        info_dict = d.get("info_dict") or {}
        if info_dict.get("title"):
            last_info["title"] = info_dict.get("title")
        if info_dict.get("playlist_index") and info_dict.get("n_entries"):
            last_info["playlist_index"] = info_dict.get("playlist_index")
            last_info["playlist_count"] = info_dict.get("n_entries")

        if status == "finished" and d.get("filename"):
            fname = str(d["filename"])
            if fname not in downloaded_files:
                downloaded_files.append(fname)

        if progress_callback:
            progress_callback(
                {
                    "stage": "downloading" if status == "downloading" else "processing",
                    "status": status,
                    "percent": percent,
                    "downloaded_bytes": downloaded,
                    "total_bytes": total,
                    "speed": d.get("speed"),
                    "eta": d.get("eta"),
                    "filename": Path(d["filename"]).name if d.get("filename") else None,
                    "title": last_info.get("title"),
                    "playlist_index": last_info.get("playlist_index"),
                    "playlist_count": last_info.get("playlist_count"),
                }
            )

    def _postprocessor_hook(d: dict[str, Any]) -> None:
        _check_cancel()
        status = d.get("status")
        pp_name = d.get("postprocessor") or ""
        info_dict = d.get("info_dict") or {}
        filepath = info_dict.get("filepath") or info_dict.get("_filename")

        if status == "finished" and filepath:
            fpath = str(filepath)
            if fpath not in downloaded_files:
                downloaded_files.append(fpath)

        if progress_callback:
            progress_callback(
                {
                    "stage": "postprocessing",
                    "status": status,
                    "postprocessor": pp_name,
                    "percent": 100.0 if status == "finished" else 99.0,
                    "title": last_info.get("title"),
                    "playlist_index": last_info.get("playlist_index"),
                    "playlist_count": last_info.get("playlist_count"),
                }
            )

    temp_root = Path(options.output_dir) / ".tmp"
    temp_root.mkdir(parents=True, exist_ok=True)
    task_temp_dir = Path(tempfile.mkdtemp(prefix="ytdl_", dir=str(temp_root)))

    opts = build_ydl_opts(
        options,
        progress_hook=_progress_hook,
        postprocessor_hook=_postprocessor_hook,
        temp_dir=task_temp_dir,
    )

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(options.url, download=True)
    except DownloadCancelledError:
        raise
    except Exception as exc:
        raise RuntimeError(classify_yt_error(str(exc))) from exc
    finally:
        shutil.rmtree(task_temp_dir, ignore_errors=True)

    # 整理最終實際存在於磁碟的輸出檔案
    final_files: list[str] = []
    if info:
        if "entries" in info and info["entries"]:
            for entry in info["entries"]:
                if not entry:
                    continue
                for req in entry.get("requested_downloads") or []:
                    fp = req.get("filepath")
                    if fp and Path(fp).exists() and fp not in final_files:
                        final_files.append(fp)
        else:
            for req in info.get("requested_downloads") or []:
                fp = req.get("filepath")
                if fp and Path(fp).exists() and fp not in final_files:
                    final_files.append(fp)

    for fp in downloaded_files:
        if Path(fp).exists() and fp not in final_files:
            final_files.append(fp)

    # 驗證輸出影片檔的影音長度是否一致（偵測 Proxy 截斷導致畫面提前卡住）
    if options.preset not in (QualityPreset.AUDIO_MP3, QualityPreset.AUDIO_M4A):
        for fp in final_files:
            if Path(fp).suffix.lower() in (".mp4", ".mkv", ".webm"):
                _verify_video_integrity(Path(fp))

    return {
        "title": (info or {}).get("title") or last_info.get("title") or "下載完成",
        "files": final_files,
        "output_dir": str(Path(options.output_dir).resolve()),
    }


def _verify_video_integrity(video_path: Path) -> None:
    """使用 ffprobe 檢查合併後的影片視訊與音訊長度是否異常落差。"""
    ffprobe_bin = shutil.which("ffprobe")
    if not ffprobe_bin or not video_path.exists():
        return
    try:
        proc = subprocess.run(
            [
                ffprobe_bin,
                "-v",
                "error",
                "-show_entries",
                "stream=codec_type,duration",
                "-of",
                "json",
                str(video_path),
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if proc.returncode != 0:
            return
        data = json.loads(proc.stdout or "{}")
        streams = data.get("streams") or []
        v_durations = [
            float(s["duration"])
            for s in streams
            if s.get("codec_type") == "video" and s.get("duration") not in (None, "N/A")
        ]
        a_durations = [
            float(s["duration"])
            for s in streams
            if s.get("codec_type") == "audio" and s.get("duration") not in (None, "N/A")
        ]
        if v_durations and a_durations:
            v_dur = max(v_durations)
            a_dur = max(a_durations)
            if a_dur > 15 and (a_dur - v_dur) > max(5.0, a_dur * 0.05):
                raise RuntimeError(
                    f"偵測到下載的影片視訊串流不完整（視訊僅 {v_dur:.1f} 秒，音訊 {a_dur:.1f} 秒），"
                    "可能因網路中斷或代理截斷導致畫面後半段卡住。請重新下載或更換較穩定的串流格式。"
                )
    except RuntimeError:
        raise
    except Exception:
        return
