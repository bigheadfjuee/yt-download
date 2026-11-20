from __future__ import annotations

import time

from fastapi.testclient import TestClient

from yt_download import web

client = TestClient(web.app)


def test_index_and_status() -> None:
    res = client.get("/")
    assert res.status_code == 200
    assert "YT-Download" in res.text

    status = client.get("/api/status")
    assert status.status_code == 200
    data = status.json()
    assert "environment" in data
    assert "cookies" in data
    assert len(data["presets"]) >= 6


def test_cookies_text_upload_and_delete(tmp_path, monkeypatch) -> None:
    test_cookie_file = tmp_path / "cookies.txt"
    monkeypatch.setattr(web, "DEFAULT_COOKIES_FILE", test_cookie_file)

    future = int(time.time()) + 3600
    payload = f".youtube.com\tTRUE\t/\tTRUE\t{future}\tSAPISID\ttesttoken\n"
    res = client.post("/api/auth/cookies/text", json={"content": payload})
    assert res.status_code == 200
    data = res.json()
    assert data["has_auth_cookies"] is True

    del_res = client.delete("/api/auth/cookies")
    assert del_res.status_code == 200
    assert del_res.json()["exists"] is False


def test_file_download_blocks_path_traversal() -> None:
    res = client.get("/api/files/download", params={"path": "../pyproject.toml"})
    assert res.status_code == 403
