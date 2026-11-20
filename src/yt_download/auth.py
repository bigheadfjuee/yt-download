from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from yt_download.config import AuthMode, DEFAULT_COOKIES_FILE, SUPPORTED_BROWSERS

YOUTUBE_AUTH_COOKIE_KEYS = {
    "SAPISID",
    "__Secure-3PAPISID",
    "__Secure-1PAPISID",
    "SID",
    "__Secure-3PSID",
    "__Secure-1PSID",
    "LOGIN_INFO",
}


@dataclass
class AuthConfig:
    mode: AuthMode = AuthMode.NONE
    cookies_file: Path | None = None
    browser: str | None = None
    browser_profile: str | None = None

    @classmethod
    def auto_default(cls) -> AuthConfig:
        """若預設 cookies.txt 存在且有效，優先採用；否則預設為未登入。"""
        if DEFAULT_COOKIES_FILE.exists():
            return cls(mode=AuthMode.COOKIES_FILE, cookies_file=DEFAULT_COOKIES_FILE)
        return cls(mode=AuthMode.NONE)


@dataclass
class CookieValidationResult:
    exists: bool
    valid_format: bool
    youtube_cookie_count: int = 0
    has_auth_cookies: bool = False
    found_auth_keys: list[str] = field(default_factory=list)
    expired_auth_keys: list[str] = field(default_factory=list)
    message: str = ""
    path: str = ""
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_cookies_file(path: Path) -> CookieValidationResult:
    """檢查 Netscape cookies.txt 格式以及是否包含有效的 YouTube 登入驗證 Cookie。"""
    path = Path(path)
    if not path.exists() or not path.is_file():
        return CookieValidationResult(
            exists=False,
            valid_format=False,
            message="尚未設定 cookies.txt 檔案。",
            path=str(path),
        )

    updated_at = datetime.fromtimestamp(
        path.stat().st_mtime, tz=timezone.utc
    ).astimezone().isoformat(timespec="seconds")

    try:
        raw_text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return CookieValidationResult(
            exists=True,
            valid_format=False,
            message=f"無法讀取 cookies.txt：{exc}",
            path=str(path),
            updated_at=updated_at,
        )

    now = int(time.time())
    total_valid_lines = 0
    yt_count = 0
    found_auth: set[str] = set()
    expired_auth: set[str] = set()

    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#HttpOnly_"):
            line = line[len("#HttpOnly_"):]
        elif line.startswith("#"):
            continue

        parts = line.split("\t")
        if len(parts) < 7:
            continue

        domain, _flag, _path, _secure, expiry_str, name, value = parts[:7]
        total_valid_lines += 1

        domain_lower = domain.lower()
        if "youtube.com" in domain_lower or "google.com" in domain_lower:
            yt_count += 1
            if name in YOUTUBE_AUTH_COOKIE_KEYS and value:
                try:
                    expiry = int(expiry_str)
                except ValueError:
                    expiry = 0
                if expiry != 0 and expiry < now:
                    expired_auth.add(name)
                else:
                    found_auth.add(name)

    if total_valid_lines == 0:
        return CookieValidationResult(
            exists=True,
            valid_format=False,
            message="cookies.txt 格式無效（非標準 Netscape 格式，或內容為空）。",
            path=str(path),
            updated_at=updated_at,
        )

    has_auth = len(found_auth) > 0
    if has_auth:
        msg = f"Cookies 有效：偵測到 {yt_count} 筆 YouTube/Google Cookie 與登入憑證（{', '.join(sorted(found_auth))}）。"
    elif expired_auth:
        msg = "Cookies 中的 YouTube 登入憑證已過期，請重新從瀏覽器匯出最新的 cookies.txt。"
    else:
        msg = (
            f"格式正確（{yt_count} 筆 YouTube/Google Cookie），但未偵測到帳號登入憑證（如 SAPISID / LOGIN_INFO）。"
            "請確認匯出時已在瀏覽器登入付費帳號。"
        )

    return CookieValidationResult(
        exists=True,
        valid_format=True,
        youtube_cookie_count=yt_count,
        has_auth_cookies=has_auth,
        found_auth_keys=sorted(found_auth),
        expired_auth_keys=sorted(expired_auth),
        message=msg,
        path=str(path),
        updated_at=updated_at,
    )


def apply_auth_to_ydl_opts(ydl_opts: dict[str, Any], auth: AuthConfig) -> dict[str, Any]:
    """將認證設定套用至 yt-dlp options dict。"""
    opts = dict(ydl_opts)

    if auth.mode == AuthMode.COOKIES_FILE:
        cookie_path = auth.cookies_file or DEFAULT_COOKIES_FILE
        if not Path(cookie_path).exists():
            raise FileNotFoundError(
                f"找不到 cookies.txt：{cookie_path}。請先上傳或指定有效的 cookies.txt 檔案。"
            )
        opts["cookiefile"] = str(cookie_path)
    elif auth.mode == AuthMode.BROWSER:
        browser = (auth.browser or "").strip().lower()
        if browser not in SUPPORTED_BROWSERS:
            raise ValueError(
                f"不支援的瀏覽器 '{browser}'，請選擇：{', '.join(SUPPORTED_BROWSERS)}"
            )
        if auth.browser_profile and auth.browser_profile.strip():
            opts["cookiesfrombrowser"] = (browser, auth.browser_profile.strip())
        else:
            opts["cookiesfrombrowser"] = (browser,)
    elif auth.mode == AuthMode.NONE:
        pass
    else:
        raise ValueError(f"不支援的驗證模式：{auth.mode}")

    return opts


def classify_yt_error(error_message: str) -> str:
    """將 yt-dlp 常見錯誤轉為易懂的繁體中文說明與排除建議。"""
    lower = error_message.lower()

    if "drm" in lower or "widevine" in lower:
        return (
            "此影片受 DRM（數位版權管理，例如 YouTube 電影租借/購買影片）保護，"
            "yt-dlp 無法下載或解密 DRM 影片。若是 YouTube Premium 或頻道會員影片，請確認帳號權限。"
        )

    if (
        "could not copy chrome cookie database" in lower
        or "failed to decrypt with dpapi" in lower
        or "app-bound" in lower
        or ("cookie" in lower and "permission denied" in lower)
    ):
        return (
            "Windows 上的 Chrome / Edge 瀏覽器啟用了 Cookie 加密或資料庫鎖定，導致無法直接讀取。\n"
            "建議解法：\n"
            "1. 改用「匯入 cookies.txt」（安裝擴充功能 'Get cookies.txt LOCALLY' 匯出），這是最穩定的方式。\n"
            "2. 或改用 Firefox 登入 YouTube 後選擇 Firefox 讀取。\n"
            "3. 或完全關閉所有 Chrome/Edge 視窗後再試。"
        )

    if "members-only" in lower or "join this channel" in lower or "member" in lower and "available to this channel" in lower:
        return (
            "此影片為「頻道會員專屬」影片。請確認：\n"
            "1. 已選擇「cookies.txt」或「瀏覽器登入」驗證模式。\n"
            "2. 該帳號確實已加入此頻道的對應會員等級。\n"
            "3. Cookies 尚未過期（可重新匯出 cookies.txt）。"
        )

    if "sign in to confirm" in lower or "confirm you're not a bot" in lower or "login required" in lower:
        return (
            "YouTube 要求登入驗證（防機器人或年齡/權限限制）。"
            "請匯入已登入 YouTube 的 cookies.txt，或切換至瀏覽器自動讀取模式後重試。"
        )

    if "private video" in lower:
        return "此影片為「私人影片」，請確認您使用的付費/登入帳號擁有觀看權限，並重新匯出 cookies.txt。"

    if "video unavailable" in lower:
        return "影片無法存取（可能已下架、設為私人、或受地區/會員權限限制）。"

    if "ffmpeg" in lower and ("not found" in lower or "not installed" in lower):
        return "找不到 ffmpeg，無法合併高畫質影音或轉檔 MP3。請確認系統已安裝 ffmpeg 並加入 PATH。"

    if "certificate_verify_failed" in lower or "certificate verify failed" in lower:
        return (
            "SSL 憑證驗證失敗（常見於企業網路代理憑證未受信任）。"
            "本工具已自動啟用 Windows 系統憑證庫（truststore）；若仍失敗，請確認公司根憑證已匯入 Windows 信任的根憑證授權單位。"
        )

    if "winerror 32" in lower or "unable to rename file" in lower:
        return (
            "檔案重新命名失敗（WinError 32：檔案正由另一個程序使用）。\n"
            "常見原因：Windows Defender / 企業防毒掃描、OneDrive 同步鎖定，或同時重複下載同一部影片。\n"
            "建議：稍等數秒後重試，或將 downloads 資料夾排除在防毒即時掃描/同步範圍外。"
        )

    if "winerror 10054" in lower or "connectionreseterror" in lower:
        return (
            "連線遭遠端主機或公司網路代理強制中斷（WinError 10054）。"
            "建議重新嘗試下載；若頻繁發生，請確認網路代理或 VPN 連線穩定度。"
        )

    return error_message
