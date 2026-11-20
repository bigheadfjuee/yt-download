from __future__ import annotations

import time
from pathlib import Path

import pytest

from yt_download.auth import (
    AuthConfig,
    apply_auth_to_ydl_opts,
    classify_yt_error,
    validate_cookies_file,
)
from yt_download.config import AuthMode


def test_validate_cookies_missing(tmp_path: Path) -> None:
    res = validate_cookies_file(tmp_path / "missing.txt")
    assert not res.exists
    assert not res.valid_format
    assert not res.has_auth_cookies


def test_validate_cookies_valid_with_auth(tmp_path: Path) -> None:
    future = int(time.time()) + 86400
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text(
        "# Netscape HTTP Cookie File\n"
        f".youtube.com\tTRUE\t/\tTRUE\t{future}\tSAPISID\tabc123456\n"
        f"#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t{future}\tLOGIN_INFO\txyz789\n",
        encoding="utf-8",
    )
    res = validate_cookies_file(cookie_file)
    assert res.exists
    assert res.valid_format
    assert res.youtube_cookie_count == 2
    assert res.has_auth_cookies
    assert "SAPISID" in res.found_auth_keys
    assert "LOGIN_INFO" in res.found_auth_keys


def test_validate_cookies_expired(tmp_path: Path) -> None:
    past = int(time.time()) - 3600
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text(
        f".youtube.com\tTRUE\t/\tTRUE\t{past}\tSAPISID\tabc123456\n",
        encoding="utf-8",
    )
    res = validate_cookies_file(cookie_file)
    assert res.valid_format
    assert not res.has_auth_cookies
    assert "SAPISID" in res.expired_auth_keys


def test_apply_auth_browser() -> None:
    auth = AuthConfig(mode=AuthMode.BROWSER, browser="firefox", browser_profile="default-release")
    opts = apply_auth_to_ydl_opts({}, auth)
    assert opts["cookiesfrombrowser"] == ("firefox", "default-release")


def test_apply_auth_invalid_browser() -> None:
    auth = AuthConfig(mode=AuthMode.BROWSER, browser="unknown_browser")
    with pytest.raises(ValueError):
        apply_auth_to_ydl_opts({}, auth)


def test_classify_yt_errors() -> None:
    assert "DRM" in classify_yt_error("ERROR: This video is DRM protected")
    assert "cookies.txt" in classify_yt_error("ERROR: Failed to decrypt with DPAPI")
    assert "頻道會員" in classify_yt_error("Join this channel to get access to members-only content")
