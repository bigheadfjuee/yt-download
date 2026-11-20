from __future__ import annotations

import socket
import webbrowser
from pathlib import Path
from typing import Optional

import typer
import uvicorn
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)
from rich.table import Table

from yt_download.auth import AuthConfig, validate_cookies_file
from yt_download.config import (
    DEFAULT_COOKIES_FILE,
    DEFAULT_SUBTITLE_LANGS,
    DOWNLOADS_DIR,
    AuthMode,
    QualityPreset,
    detect_environment,
    ensure_runtime_dirs,
)
from yt_download.downloader import DownloadOptions, download_media, probe_url

app = typer.Typer(
    name="yt-dl",
    help="YouTube 影片下載工具（支援付費帳號 Cookies、4K / 1080p Premium、音訊、字幕、播放清單）",
    no_args_is_help=True,
)
console = Console()


def _resolve_auth(
    cookies: Optional[Path],
    browser: Optional[str],
    browser_profile: Optional[str],
    no_auth: bool,
) -> AuthConfig:
    if no_auth:
        return AuthConfig(mode=AuthMode.NONE)
    if cookies:
        return AuthConfig(mode=AuthMode.COOKIES_FILE, cookies_file=cookies)
    if browser:
        return AuthConfig(
            mode=AuthMode.BROWSER,
            browser=browser,
            browser_profile=browser_profile,
        )
    if DEFAULT_COOKIES_FILE.exists():
        return AuthConfig(mode=AuthMode.COOKIES_FILE, cookies_file=DEFAULT_COOKIES_FILE)
    return AuthConfig(mode=AuthMode.NONE)


def _format_duration(seconds: Optional[int | float]) -> str:
    if not seconds:
        return "--:--"
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


@app.command("check-auth")
def check_auth(
    cookies: Optional[Path] = typer.Option(
        None, "--cookies", "-c", help="指定要檢查的 cookies.txt 路徑（預設為 data/cookies.txt）"
    ),
) -> None:
    """檢查環境工具（ffmpeg / Node.js）與 cookies.txt 付費帳號登入狀態。"""
    ensure_runtime_dirs()
    env = detect_environment()
    cookie_path = cookies or DEFAULT_COOKIES_FILE
    result = validate_cookies_file(cookie_path)

    table = Table(title="系統環境與驗證狀態", show_header=True)
    table.add_column("項目", style="cyan")
    table.add_column("狀態")
    table.add_column("說明")

    table.add_row(
        "FFmpeg",
        "[green]可用[/green]" if env["ffmpeg_available"] else "[red]未安裝[/red]",
        str(env["ffmpeg_path"] or "合併 1080p/4K 與轉檔 MP3 需要 ffmpeg"),
    )
    table.add_row(
        "JS Runtime (Node / Deno)",
        "[green]可用[/green]" if (env["node_available"] or env["deno_available"]) else "[yellow]未偵測[/yellow]",
        str(env["node_path"] or env["deno_path"] or "建議安裝 Node.js 以穩定解析 YouTube 簽章"),
    )
    cookie_status = (
        "[green]已驗證[/green]"
        if result.has_auth_cookies
        else ("[yellow]未登入/過期[/yellow]" if result.exists else "[dim]未設定[/dim]")
    )
    table.add_row("cookies.txt", cookie_status, result.message)
    console.print(table)


@app.command("info")
def info_cmd(
    url: str = typer.Argument(..., help="YouTube 影片或播放清單網址"),
    cookies: Optional[Path] = typer.Option(None, "--cookies", "-c", help="cookies.txt 檔案路徑"),
    browser: Optional[str] = typer.Option(None, "--browser", "-b", help="從瀏覽器讀取登入狀態 (chrome/edge/firefox/brave)"),
    browser_profile: Optional[str] = typer.Option(None, "--browser-profile", help="瀏覽器設定檔名稱"),
    playlist: bool = typer.Option(False, "--playlist", help="解析整份播放清單"),
    no_auth: bool = typer.Option(False, "--no-auth", help="強制不使用任何帳號 Cookie"),
) -> None:
    """查詢 YouTube 影片或播放清單的可用畫質（含 1080p Premium）與字幕。"""
    auth = _resolve_auth(cookies, browser, browser_profile, no_auth)
    with console.status("正在解析影片資訊...", spinner="dots"):
        try:
            data = probe_url(url, auth=auth, allow_playlist=playlist)
        except Exception as exc:
            console.print(f"[red]解析失敗：[/red]{exc}")
            raise typer.Exit(code=1)

    if data["is_playlist"]:
        console.print(
            Panel.fit(
                f"[bold]{data['title']}[/bold]\n"
                f"頻道：{data['uploader'] or '未知'}\n"
                f"影片數量：{data['entry_count']} 部",
                title="播放清單資訊",
                border_style="cyan",
            )
        )
        t = Table(show_header=True)
        t.add_column("#", justify="right", style="cyan")
        t.add_column("標題")
        t.add_column("片長", justify="right")
        for entry in data["entries"][:30]:
            t.add_row(str(entry["index"]), entry["title"], _format_duration(entry["duration"]))
        console.print(t)
        return

    premium_badge = " [bold yellow]★ 偵測到 1080p Premium 串流[/bold yellow]" if data["has_premium_format"] else ""
    console.print(
        Panel.fit(
            f"[bold]{data['title']}[/bold]{premium_badge}\n"
            f"頻道：{data['uploader'] or '未知'}  |  片長：{_format_duration(data.get('duration'))}\n"
            f"可用人工字幕：{', '.join(data['subtitles'][:10]) or '無'}\n"
            f"驗證模式：{auth.mode.value}",
            title="影片資訊",
            border_style="green",
        )
    )

    t = Table(title="可用畫質 / 音訊串流（可搭配 --format-id 指定）", show_header=True)
    t.add_column("Format ID", style="cyan")
    t.add_column("類型")
    t.add_column("規格")
    for fmt in data["formats"]:
        t.add_row(fmt["format_id"], fmt["type"], fmt["label"])
    console.print(t)


@app.command("download")
def download_cmd(
    url: str = typer.Argument(..., help="YouTube 影片或播放清單網址"),
    preset: QualityPreset = typer.Option(
        QualityPreset.BEST,
        "--preset",
        "-p",
        case_sensitive=False,
        help="下載畫質/格式預設：best / 4k / 1080p / 720p / audio_mp3 / audio_m4a",
    ),
    format_id: Optional[str] = typer.Option(None, "--format-id", "-f", help="指定特定 format_id（覆蓋 preset）"),
    cookies: Optional[Path] = typer.Option(None, "--cookies", "-c", help="cookies.txt 檔案路徑"),
    browser: Optional[str] = typer.Option(None, "--browser", "-b", help="從瀏覽器讀取登入狀態 (chrome/edge/firefox/brave)"),
    browser_profile: Optional[str] = typer.Option(None, "--browser-profile", help="瀏覽器設定檔名稱"),
    no_auth: bool = typer.Option(False, "--no-auth", help="強制不使用任何帳號 Cookie"),
    subtitles: bool = typer.Option(False, "--subtitles", "-s", help="下載字幕（繁體中文 / 英文）"),
    no_auto_subs: bool = typer.Option(False, "--no-auto-subs", help="僅下載人工字幕，不下載自動產生字幕"),
    sub_langs: Optional[str] = typer.Option(
        None, "--sub-langs", help="字幕語系（逗號分隔，預設 zh-Hant,zh-TW,zh-HK,en）"
    ),
    embed_subs: bool = typer.Option(False, "--embed-subs", help="將字幕內嵌至 MP4 影片檔"),
    playlist: bool = typer.Option(False, "--playlist", help="允許下載整份播放清單"),
    playlist_items: Optional[str] = typer.Option(None, "--playlist-items", help="播放清單項目範圍，例如 1-5 或 1,3,5"),
    output: Path = typer.Option(DOWNLOADS_DIR, "--output", "-o", help="輸出資料夾路徑"),
) -> None:
    """下載 YouTube 影片、音訊、字幕或播放清單。"""
    ensure_runtime_dirs()
    auth = _resolve_auth(cookies, browser, browser_profile, no_auth)
    langs = (
        [lang.strip() for lang in sub_langs.split(",") if lang.strip()]
        if sub_langs
        else list(DEFAULT_SUBTITLE_LANGS)
    )

    options = DownloadOptions(
        url=url,
        preset=preset,
        format_id=format_id,
        output_dir=output,
        subtitles=subtitles,
        auto_subtitles=not no_auto_subs,
        subtitle_langs=langs,
        embed_subtitles=embed_subs,
        allow_playlist=playlist,
        playlist_items=playlist_items,
        auth=auth,
    )

    console.print(
        f"[cyan]驗證模式：[/cyan]{auth.mode.value}  "
        f"[cyan]格式：[/cyan]{format_id or preset.value}  "
        f"[cyan]輸出：[/cyan]{output.resolve()}"
    )

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task_id = progress.add_task("準備下載...", total=None)

        def on_progress(info: dict) -> None:
            stage = info.get("stage")
            title = info.get("title") or "下載中"
            if len(title) > 40:
                title = title[:37] + "..."

            if stage == "downloading":
                total = info.get("total_bytes") or 0
                downloaded = info.get("downloaded_bytes") or 0
                if total > 0:
                    progress.update(task_id, total=total, completed=downloaded, description=f"[green]{title}[/green]")
                else:
                    progress.update(task_id, description=f"[green]{title}[/green]")
            elif stage == "postprocessing":
                pp = info.get("postprocessor") or "轉檔/合併"
                progress.update(task_id, description=f"[yellow]後處理 ({pp})...[/yellow]")

        try:
            result = download_media(options, progress_callback=on_progress)
        except Exception as exc:
            console.print(f"\n[red]下載失敗：[/red]{exc}")
            raise typer.Exit(code=1)

    console.print(f"\n[bold green]下載完成！[/bold green] {result['title']}")
    for fp in result["files"]:
        console.print(f"  • {fp}")


def _find_available_port(host: str, preferred_port: int) -> int:
    """檢查指定埠號是否可用；若被 Windows Hyper-V/WSL 保留或佔用，自動切換至可用埠號。"""
    candidates = [preferred_port, 18000, 18080, 28000, 38000, 0]
    for candidate in candidates:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((host, candidate))
                return int(sock.getsockname()[1])
            except OSError:
                continue
    raise RuntimeError(f"無法在 {host} 找到可用的監聽埠號。")


@app.command("web")
def web_cmd(
    host: str = typer.Option("127.0.0.1", "--host", help="監聽位址（建議維持 127.0.0.1 本機存取）"),
    port: int = typer.Option(18000, "--port", help="監聽埠號（若被系統保留或佔用會自動切換）"),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="啟動後自動開啟瀏覽器"),
) -> None:
    """啟動本機 Web 下載介面。"""
    ensure_runtime_dirs()
    actual_port = _find_available_port(host, port)
    if actual_port != port:
        console.print(
            f"[yellow]提示：埠號 {port} 已被佔用或受 Windows 保留（WinError 10013），"
            f"已自動切換至可用埠號 {actual_port}。[/yellow]"
        )
    url = f"http://{host}:{actual_port}"
    console.print(
        Panel.fit(
            f"YouTube 下載器 Web 介面已啟動：\n[bold cyan]{url}[/bold cyan]\n按下 Ctrl+C 可停止伺服器。",
            title="YT-Download Web UI",
            border_style="cyan",
        )
    )
    if open_browser:
        webbrowser.open(url)
    uvicorn.run("yt_download.web:app", host=host, port=actual_port, log_level="warning")


if __name__ == "__main__":
    app()
