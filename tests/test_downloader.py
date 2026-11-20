from __future__ import annotations

from pathlib import Path

from yt_download.auth import AuthConfig
from yt_download.config import AuthMode, QualityPreset
from yt_download.downloader import DownloadOptions, _summarize_formats, build_ydl_opts


def test_build_ydl_opts_best_video_with_subs(tmp_path: Path) -> None:
    opts = build_ydl_opts(
        DownloadOptions(
            url="https://www.youtube.com/watch?v=3zgm60bXmQk",
            preset=QualityPreset.BEST,
            output_dir=tmp_path,
            subtitles=True,
            auto_subtitles=True,
            subtitle_langs=["zh-Hant", "en"],
            embed_subtitles=True,
            allow_playlist=False,
            auth=AuthConfig(mode=AuthMode.NONE),
        )
    )
    assert opts["format"] == "bv*+ba/b"
    assert opts["merge_output_format"] == "mp4"
    assert opts["noplaylist"] is True
    assert opts["writesubtitles"] is True
    assert opts["writeautomaticsub"] is True
    assert opts["subtitleslangs"] == ["zh-Hant", "en"]
    assert opts["embedsubtitles"] is True


def test_build_ydl_opts_audio_mp3(tmp_path: Path) -> None:
    opts = build_ydl_opts(
        DownloadOptions(
            url="https://www.youtube.com/watch?v=3zgm60bXmQk",
            preset=QualityPreset.AUDIO_MP3,
            output_dir=tmp_path,
            auth=AuthConfig(mode=AuthMode.NONE),
        )
    )
    assert opts["format"] == "ba/b"
    assert "merge_output_format" not in opts
    pp_keys = [pp["key"] for pp in opts["postprocessors"]]
    assert "FFmpegExtractAudio" in pp_keys


def test_build_ydl_opts_playlist(tmp_path: Path) -> None:
    opts = build_ydl_opts(
        DownloadOptions(
            url="https://www.youtube.com/playlist?list=PL123",
            allow_playlist=True,
            playlist_items="1-3",
            output_dir=tmp_path,
            auth=AuthConfig(mode=AuthMode.NONE),
        )
    )
    assert opts["noplaylist"] is False
    assert opts["playlist_items"] == "1-3"
    assert "%(playlist_title|Playlist)s" in opts["outtmpl"]


def test_summarize_formats_detects_premium() -> None:
    raw = [
        {
            "format_id": "616",
            "ext": "mp4",
            "height": 1080,
            "fps": 30,
            "vcodec": "vp09.00.40.08",
            "acodec": "none",
            "tbr": 4500.0,
            "format_note": "1080p Premium",
        },
        {
            "format_id": "248",
            "ext": "webm",
            "height": 1080,
            "fps": 30,
            "vcodec": "vp9",
            "acodec": "none",
            "tbr": 2200.0,
            "format_note": "1080p",
        },
        {
            "format_id": "251",
            "ext": "webm",
            "vcodec": "none",
            "acodec": "opus",
            "abr": 160.0,
        },
    ]
    summarized = _summarize_formats(raw)
    assert summarized[0]["format_id"] == "616"
    assert summarized[0]["is_premium"] is True
    assert "Premium" in summarized[0]["label"]
    assert any(f["type"] == "audio" and f["format_id"] == "251" for f in summarized)
