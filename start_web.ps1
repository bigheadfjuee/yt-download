# 啟動 YT-Download 本機 Web 介面（若 18000 被佔用或系統保留會自動切換可用埠號）
Set-Location $PSScriptRoot
uv run yt-dl web --host 127.0.0.1 --port 18000 --open
