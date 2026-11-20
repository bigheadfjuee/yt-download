# YT-Download — YouTube 付費帳號高畫質下載工具

支援透過 **YouTube 付費帳號（YouTube Premium / 頻道會員）** 驗證下載影片、音訊、字幕與播放清單，提供 **本機 Web 介面** 與 **CLI 命令列** 雙模式。

## 功能特色

- **付費帳號驗證雙模式**：
  - **匯入 `cookies.txt`（最推薦）**：支援 Netscape 格式自動檢查（驗證是否含有效 `SAPISID` / `LOGIN_INFO` 與是否過期），徹底避開 Windows Chrome / Edge 的 DPAPI 加密鎖定問題。
  - **瀏覽器自動讀取**：直接讀取本機 Firefox / Chrome / Edge / Brave 的登入狀態。
- **最高畫質影片**：支援 4K / 1080p Premium（高位元率）自動偵測與標記，透過 FFmpeg 合併為 MP4。
- **純音訊下載**：支援轉檔最高音質 MP3 與無損封裝 M4A。
- **字幕下載**：自動下載繁體中文 / 英文（`zh-Hant, zh-TW, zh-HK, en`）SRT 字幕，可選包含自動字幕或內嵌至 MP4。
- **播放清單批次下載**：支援自動建立播放清單子資料夾與指定集數範圍（如 `1-5`）。

---

## 環境需求與安裝

本專案使用 Python 3.11+、[`uv`](https://docs.astral.sh/uv/)、FFmpeg（合併高畫質與轉 MP3）與 Node.js（YouTube 簽章解析）：

```powershell
# 安裝所有依賴套件
uv sync

# 檢查環境與 cookies.txt 狀態
uv run yt-dl check-auth
```

---

## 方式一：啟動 Web 介面（推薦）

直接執行：

```powershell
uv run yt-dl web
```

或執行一鍵腳本：

```powershell
.\start_web.ps1
```

啟動後會自動開啟 `http://127.0.0.1:8000`（僅監聽本機，確保您的 Cookies 與下載檔案安全）。

---

## 方式二：CLI 命令列使用範例

### 1. 查詢影片可用畫質（含 1080p Premium 偵測）

```powershell
# 使用預設 data/cookies.txt（若已透過 Web 介面匯入）
uv run yt-dl info "https://www.youtube.com/watch?v=3zgm60bXmQk"

# 指定 cookies.txt
uv run yt-dl info "https://www.youtube.com/watch?v=3zgm60bXmQk" -c .\cookies.txt

# 直接讀取本機瀏覽器登入狀態
uv run yt-dl info "https://www.youtube.com/watch?v=3zgm60bXmQk" -b firefox
```

### 2. 下載影片 / 音訊 / 字幕 / 播放清單

```powershell
# 最高畫質（4K / 1080p Premium）+ 繁中/英文字幕
uv run yt-dl download "https://www.youtube.com/watch?v=3zgm60bXmQk" -p best -s

# 指定 1080p（優先 1080p Premium）並內嵌字幕
uv run yt-dl download "https://www.youtube.com/watch?v=3zgm60bXmQk" -p 1080p -s --embed-subs

# 純音訊 MP3
uv run yt-dl download "https://www.youtube.com/watch?v=3zgm60bXmQk" -p audio_mp3

# 下載播放清單的第 1 到 5 部影片
uv run yt-dl download "https://www.youtube.com/playlist?list=XXXX" --playlist --playlist-items 1-5
```

---

## 如何安全匯出付費帳號 `cookies.txt`

Windows 版 Chrome / Edge 自 v127 起啟用 App-Bound Encryption，容易導致直接讀取瀏覽器資料庫失敗。建議使用 `cookies.txt`：

1. 在瀏覽器安裝開源擴充功能 **Get cookies.txt LOCALLY**。
2. 登入您的 YouTube Premium / 頻道會員帳號並開啟 `https://www.youtube.com`。
3. 點擊擴充功能 → 按下 **Export** 取得 `youtube.com_cookies.txt`。
4. 在 Web 介面的「1. 付費帳號驗證」區塊上傳，或於 CLI 透過 `-c youtube.com_cookies.txt` 指定。

> **安全提醒**：`cookies.txt` 與 `data/`、`downloads/` 均已加入 `.gitignore`，請勿將您的 `cookies.txt` 提交至 Git 或分享給他人。

> **DRM 說明**：YouTube Premium（1080p Enhanced Bitrate）、頻道會員專屬影片、年齡限制與私人影片皆可透過付費帳號 Cookies 下載；但受 Widevine DRM 保護的「YouTube 電影租借/購買」內容無法透過 `yt-dlp` 解密下載。
