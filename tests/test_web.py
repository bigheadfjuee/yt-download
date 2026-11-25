from __future__ import annotations

import time

from fastapi.testclient import TestClient

from yt_download import web

client = TestClient(web.app)


def test_index_and_status() -> None:
    res = client.get("/")
    assert res.status_code == 200
    assert "YT-Download" in res.text
    assert 'id="authCard"' in res.text
    assert 'id="authCardBody"' in res.text
    assert 'id="toggleAuthCardBtn"' in res.text
    assert '<option value="720p" selected>' in res.text
    assert 'id="subtitlesCheck" checked' in res.text
    assert 'value="subtitles_only"' in res.text
    assert 'id="downloadSubtitlesBtn"' in res.text
    assert 'id="clearTasksBtn"' in res.text

    status = client.get("/api/status")
    assert status.status_code == 200
    data = status.json()
    assert "environment" in data
    assert "cookies" in data
    assert len(data["presets"]) >= 7
    assert any(p["value"] == "subtitles_only" for p in data["presets"])


def test_download_request_defaults() -> None:
    req = web.DownloadRequest(url="https://www.youtube.com/watch?v=3zgm60bXmQk")
    assert req.subtitles is True
    assert "en-US" in req.subtitle_langs


def test_clear_all_downloads() -> None:
    t1 = web.DownloadTask(id="t1", url="https://youtu.be/1", preset="720p", status="completed")
    t2 = web.DownloadTask(id="t2", url="https://youtu.be/2", preset="720p", status="downloading")
    with web._tasks_lock:
        web._tasks.clear()
        web._tasks[t1.id] = t1
        web._tasks[t2.id] = t2

    res = client.delete("/api/downloads")
    assert res.status_code == 200
    assert res.json() == {"cleared": 2}
    assert t2.cancel_event.is_set() is True

    list_res = client.get("/api/downloads")
    assert list_res.status_code == 200
    assert list_res.json() == []


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
