"""YouTube 影片下載工具（支援付費帳號 Cookies、4K/1080p Premium、音訊、字幕、播放清單）。"""

try:
    import truststore

    truststore.inject_into_ssl()
except Exception:
    pass

__version__ = "0.1.0"
