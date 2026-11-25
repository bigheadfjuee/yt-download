from __future__ import annotations

from pathlib import Path

import pytest

from yt_download import downloader
from yt_download.auth import AuthConfig
from yt_download.config import AuthMode, QualityPreset
from yt_download.downloader import DownloadOptions, _summarize_formats, build_ydl_opts, download_media


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


def test_default_subtitles_enabled() -> None:
    opts = DownloadOptions(url="https://www.youtube.com/watch?v=3zgm60bXmQk")
    assert opts.subtitles is True


def test_build_ydl_opts_subtitles_only(tmp_path: Path) -> None:
    opts = build_ydl_opts(
        DownloadOptions(
            url="https://www.youtube.com/watch?v=3zgm60bXmQk",
            preset=QualityPreset.SUBTITLES_ONLY,
            output_dir=tmp_path,
            subtitles=False,  # 即使傳 False，純字幕模式仍應強制啟用字幕下載
            auto_subtitles=True,
            subtitle_langs=["zh-Hant", "en"],
            embed_subtitles=True,  # 純字幕模式不應內嵌字幕
            auth=AuthConfig(mode=AuthMode.NONE),
        )
    )
    assert opts["skip_download"] is True
    assert "format" not in opts
    assert "merge_output_format" not in opts
    assert opts["writesubtitles"] is True
    assert opts["writeautomaticsub"] is True
    assert opts["subtitleslangs"] == ["zh-Hant", "en"]
    assert "embedsubtitles" not in opts
    pp_keys = [pp["key"] for pp in opts["postprocessors"]]
    assert pp_keys == ["FFmpegSubtitlesConvertor"]


def test_download_media_subtitles_only_collects_srt_files(tmp_path: Path, monkeypatch) -> None:
    srt_file = tmp_path / "Sample [abc123].zh-Hant.srt"
    srt_file.write_text("1\n00:00:00,000 --> 00:00:02,000\nHello\n", encoding="utf-8")

    class FakeYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extract_info(self, url, download=True):
            return {
                "title": "Sample",
                "__files_to_move": {"/tmp/Sample [abc123].zh-Hant.srt": str(srt_file)},
                "requested_subtitles": {"zh-Hant": {"filepath": "/tmp/Sample [abc123].zh-Hant.srt"}},
            }

    monkeypatch.setattr(downloader.yt_dlp, "YoutubeDL", FakeYDL)

    result = download_media(
        DownloadOptions(
            url="https://www.youtube.com/watch?v=abc123",
            preset=QualityPreset.SUBTITLES_ONLY,
            output_dir=tmp_path,
            auth=AuthConfig(mode=AuthMode.NONE),
        )
    )
    assert result["title"] == "Sample"
    assert result["files"] == [str(srt_file)]


def test_download_media_subtitles_only_raises_when_no_subtitles_found(tmp_path: Path, monkeypatch) -> None:
    class FakeYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extract_info(self, url, download=True):
            return {"title": "No Subs Video", "requested_subtitles": {}}

    monkeypatch.setattr(downloader.yt_dlp, "YoutubeDL", FakeYDL)

    with pytest.raises(RuntimeError, match="找不到符合語系"):
        download_media(
            DownloadOptions(
                url="https://www.youtube.com/watch?v=nosub123",
                preset=QualityPreset.SUBTITLES_ONLY,
                output_dir=tmp_path,
                subtitle_langs=["zh-Hant"],
                auth=AuthConfig(mode=AuthMode.NONE),
            )
        )
