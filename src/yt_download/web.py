from __future__ import annotations

import asyncio
import json
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from yt_download.auth import AuthConfig, validate_cookies_file
from yt_download.config import (
    DEFAULT_COOKIES_FILE,
    DEFAULT_SUBTITLE_LANGS,
    DOWNLOADS_DIR,
    PRESET_LABELS,
    SUPPORTED_BROWSERS,
    AuthMode,
    QualityPreset,
    detect_environment,
    ensure_runtime_dirs,
)
from yt_download.downloader import (
    DownloadCancelledError,
    DownloadOptions,
    download_media,
    probe_url,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"

ensure_runtime_dirs()

app = FastAPI(title="YouTube 影片下載器", version="0.1.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------
class AuthPayload(BaseModel):
    mode: AuthMode = AuthMode.NONE
    browser: str | None = None
    browser_profile: str | None = None


class ProbeRequest(BaseModel):
    url: str = Field(..., min_length=5)
    allow_playlist: bool = False
    auth: AuthPayload = Field(default_factory=AuthPayload)


class DownloadRequest(BaseModel):
    url: str = Field(..., min_length=5)
    preset: QualityPreset = QualityPreset.BEST
    format_id: str | None = None
    subtitles: bool = False
    auto_subtitles: bool = True
    subtitle_langs: list[str] = Field(default_factory=lambda: list(DEFAULT_SUBTITLE_LANGS))
    embed_subtitles: bool = False
    allow_playlist: bool = False
    playlist_items: str | None = None
    auth: AuthPayload = Field(default_factory=AuthPayload)


class CookiesTextPayload(BaseModel):
    content: str = Field(..., min_length=10)


# ---------------------------------------------------------------------------
# In-memory Task Manager
# ---------------------------------------------------------------------------
@dataclass
class DownloadTask:
    id: str
    url: str
    preset: str
    status: str = "queued"  # queued | downloading | postprocessing | completed | failed | cancelled
    title: str = "準備中..."
    percent: float = 0.0
    downloaded_bytes: int = 0
    total_bytes: int = 0
    speed: float | None = None
    eta: int | None = None
    stage_text: str = "排隊中..."
    playlist_index: int | None = None
    playlist_count: int | None = None
    files: list[str] = field(default_factory=list)
    error: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "url": self.url,
            "preset": self.preset,
            "status": self.status,
            "title": self.title,
            "percent": self.percent,
            "downloaded_bytes": self.downloaded_bytes,
            "total_bytes": self.total_bytes,
            "speed": self.speed,
            "eta": self.eta,
            "stage_text": self.stage_text,
            "playlist_index": self.playlist_index,
            "playlist_count": self.playlist_count,
            "files": self.files,
            "error": self.error,
            "created_at": self.created_at,
        }


_tasks_lock = threading.Lock()
_tasks: dict[str, DownloadTask] = {}


def _to_auth_config(payload: AuthPayload) -> AuthConfig:
    if payload.mode == AuthMode.COOKIES_FILE:
        return AuthConfig(mode=AuthMode.COOKIES_FILE, cookies_file=DEFAULT_COOKIES_FILE)
    if payload.mode == AuthMode.BROWSER:
        return AuthConfig(
            mode=AuthMode.BROWSER,
            browser=payload.browser or "chrome",
            browser_profile=payload.browser_profile,
        )
    return AuthConfig(mode=AuthMode.NONE)


def _run_download_task(task: DownloadTask, options: DownloadOptions) -> None:
    task.status = "downloading"
    task.stage_text = "正在連線並解析串流..."

    def on_progress(info: dict[str, Any]) -> None:
        stage = info.get("stage")
        if info.get("title"):
            task.title = str(info["title"])
        if info.get("playlist_index"):
            task.playlist_index = info.get("playlist_index")
            task.playlist_count = info.get("playlist_count")

        if stage == "downloading":
            task.status = "downloading"
            if info.get("percent") is not None:
                task.percent = float(info["percent"])
            task.downloaded_bytes = int(info.get("downloaded_bytes") or 0)
            task.total_bytes = int(info.get("total_bytes") or 0)
            task.speed = info.get("speed")
            task.eta = info.get("eta")
            if task.playlist_index and task.playlist_count:
                task.stage_text = f"下載中 ({task.playlist_index}/{task.playlist_count})..."
            else:
                task.stage_text = "下載中..."
        elif stage == "postprocessing":
            task.status = "postprocessing"
            pp = info.get("postprocessor") or "FFmpeg"
            task.percent = 99.0 if info.get("status") != "finished" else 100.0
            task.stage_text = f"後處理合併/轉檔中 ({pp})..."

    try:
        result = download_media(
            options,
            progress_callback=on_progress,
            cancel_event=task.cancel_event,
        )
        task.title = result.get("title") or task.title
        # 轉為相對於 downloads/ 的路徑，方便 Web UI 提供下載連結
        rel_files: list[str] = []
        base = DOWNLOADS_DIR.resolve()
        for fp in result.get("files") or []:
            p = Path(fp).resolve()
            try:
                rel_files.append(p.relative_to(base).as_posix())
            except ValueError:
                rel_files.append(p.name)
        task.files = rel_files
        task.percent = 100.0
        task.status = "completed"
        task.stage_text = "下載完成"
    except DownloadCancelledError:
        task.status = "cancelled"
        task.stage_text = "已取消"
        task.error = "下載已取消"
    except Exception as exc:
        task.status = "failed"
        task.stage_text = "下載失敗"
        task.error = str(exc)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html)


@app.get("/api/status")
async def get_status() -> dict[str, Any]:
    ensure_runtime_dirs()
    cookie_status = validate_cookies_file(DEFAULT_COOKIES_FILE).to_dict()
    return {
        "environment": detect_environment(),
        "cookies": cookie_status,
        "supported_browsers": list(SUPPORTED_BROWSERS),
        "presets": [
            {"value": preset.value, "label": label}
            for preset, label in PRESET_LABELS.items()
        ],
        "downloads_dir": str(DOWNLOADS_DIR.resolve()),
    }


@app.post("/api/auth/cookies")
async def upload_cookies_file(file: UploadFile = File(...)) -> dict[str, Any]:
    ensure_runtime_dirs()
    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="cookies.txt 檔案過大（上限 5MB）。")
    DEFAULT_COOKIES_FILE.write_bytes(content)
    validation = validate_cookies_file(DEFAULT_COOKIES_FILE)
    if not validation.valid_format:
        DEFAULT_COOKIES_FILE.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=validation.message)
    return validation.to_dict()


@app.post("/api/auth/cookies/text")
async def upload_cookies_text(payload: CookiesTextPayload) -> dict[str, Any]:
    ensure_runtime_dirs()
    DEFAULT_COOKIES_FILE.write_text(payload.content, encoding="utf-8")
    validation = validate_cookies_file(DEFAULT_COOKIES_FILE)
    if not validation.valid_format:
        DEFAULT_COOKIES_FILE.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=validation.message)
    return validation.to_dict()


@app.delete("/api/auth/cookies")
async def delete_cookies() -> dict[str, Any]:
    DEFAULT_COOKIES_FILE.unlink(missing_ok=True)
    return validate_cookies_file(DEFAULT_COOKIES_FILE).to_dict()


@app.post("/api/probe")
async def api_probe(req: ProbeRequest) -> dict[str, Any]:
    auth = _to_auth_config(req.auth)
    try:
        return await asyncio.to_thread(probe_url, req.url.strip(), auth, req.allow_playlist)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/downloads")
async def create_download(req: DownloadRequest) -> dict[str, Any]:
    ensure_runtime_dirs()
    auth = _to_auth_config(req.auth)

    # 先驗證 cookies.txt 存在與否，避免背景執行才立刻失敗
    if auth.mode == AuthMode.COOKIES_FILE and not DEFAULT_COOKIES_FILE.exists():
        raise HTTPException(status_code=400, detail="尚未匯入 cookies.txt，請先於上方設定付費帳號 Cookies。")

    # 避免同一網址重複同時下載造成檔案鎖定衝突
    normalized_url = req.url.strip()
    with _tasks_lock:
        for existing in _tasks.values():
            if existing.url == normalized_url and existing.status in (
                "queued",
                "downloading",
                "postprocessing",
            ):
                raise HTTPException(
                    status_code=409,
                    detail="此網址目前正在下載中，請等待現有任務完成或先取消後再重試。",
                )

    task_id = uuid.uuid4().hex[:10]
    task = DownloadTask(
        id=task_id,
        url=normalized_url,
        preset=req.format_id or req.preset.value,
    )
    with _tasks_lock:
        _tasks[task_id] = task

    options = DownloadOptions(
        url=req.url.strip(),
        preset=req.preset,
        format_id=req.format_id,
        output_dir=DOWNLOADS_DIR,
        subtitles=req.subtitles,
        auto_subtitles=req.auto_subtitles,
        subtitle_langs=req.subtitle_langs or list(DEFAULT_SUBTITLE_LANGS),
        embed_subtitles=req.embed_subtitles,
        allow_playlist=req.allow_playlist,
        playlist_items=req.playlist_items,
        auth=auth,
    )

    worker = threading.Thread(
        target=_run_download_task,
        args=(task, options),
        daemon=True,
    )
    worker.start()
    return task.to_dict()


@app.get("/api/downloads")
async def list_downloads() -> list[dict[str, Any]]:
    with _tasks_lock:
        items = [t.to_dict() for t in _tasks.values()]
    items.reverse()
    return items


@app.get("/api/downloads/{task_id}")
async def get_download(task_id: str) -> dict[str, Any]:
    with _tasks_lock:
        task = _tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="找不到此下載任務。")
    return task.to_dict()


@app.post("/api/downloads/{task_id}/cancel")
async def cancel_download(task_id: str) -> dict[str, Any]:
    with _tasks_lock:
        task = _tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="找不到此下載任務。")
    task.cancel_event.set()
    if task.status in ("queued", "downloading", "postprocessing"):
        task.stage_text = "正在取消..."
    return task.to_dict()


@app.get("/api/downloads/{task_id}/events")
async def stream_download_events(task_id: str) -> StreamingResponse:
    with _tasks_lock:
        if task_id not in _tasks:
            raise HTTPException(status_code=404, detail="找不到此下載任務。")

    async def event_generator():
        last_payload = ""
        while True:
            with _tasks_lock:
                task = _tasks.get(task_id)
            if not task:
                break
            data = task.to_dict()
            serialized = json.dumps(data, ensure_ascii=False)
            if serialized != last_payload:
                yield f"data: {serialized}\n\n"
                last_payload = serialized
            if data["status"] in ("completed", "failed", "cancelled"):
                break
            await asyncio.sleep(0.4)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/files")
async def list_downloaded_files() -> list[dict[str, Any]]:
    ensure_runtime_dirs()
    base = DOWNLOADS_DIR.resolve()
    files: list[dict[str, Any]] = []
    for p in base.rglob("*"):
        if ".tmp" in p.parts:
            continue
        if p.is_file() and not p.name.endswith(".part"):
            stat = p.stat()
            files.append(
                {
                    "name": p.name,
                    "path": p.relative_to(base).as_posix(),
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                }
            )
    files.sort(key=lambda x: x["modified"], reverse=True)
    return files


@app.get("/api/files/download")
async def download_saved_file(path: str = Query(..., min_length=1)) -> FileResponse:
    base = DOWNLOADS_DIR.resolve()
    target = (base / path).resolve()
    # 防止路徑遍歷攻擊
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="不允許存取下載目錄以外的檔案。") from exc

    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="檔案不存在。")

    return FileResponse(path=str(target), filename=target.name)
