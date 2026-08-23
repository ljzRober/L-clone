"""配置: 环境变量 + 可选 .env 文件。"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULTS = {
    "BRAIN_DB_PATH": "lclone.db",
    "BRAIN_LLM": "api",                # "api" | "dummy" (离线测试)
    "OPENAI_API_KEY": "",
    "BRAIN_BASE_URL": "https://api.openai.com/v1",  # 可换 DeepSeek/硅基流动/智谱等
    "BRAIN_CHAT_MODEL": "gpt-4o-mini",
    "BRAIN_EMBED_MODEL": "text-embedding-3-small",
    "BRAIN_TEMPERATURE": "0.3",
    "BRAIN_HOST": "0.0.0.0",
    "BRAIN_PORT": "8000",
    "BRAIN_EMBED_DIM": "384",          # dummy 后端专用
}

_loaded = False


def _load_dotenv() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    for path in (Path.cwd() / ".env", Path(__file__).resolve().parent.parent / ".env"):
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def get(key: str) -> str:
    _load_dotenv()
    return os.environ.get(key, DEFAULTS.get(key, ""))


def get_int(key: str, default: int) -> int:
    try:
        return int(get(key) or default)
    except ValueError:
        return default


def get_float(key: str, default: float) -> float:
    try:
        return float(get(key) or default)
    except ValueError:
        return default


def db_path() -> str:
    return get("BRAIN_DB_PATH") or "lclone.db"
