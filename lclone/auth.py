"""鉴权: 可选 API key。设了 LCLONE_API_KEY 才强制鉴权, 不设则本地免鉴权。"""

from __future__ import annotations

from typing import Optional

from . import config


def api_key() -> str:
    return (config.get("LCLONE_API_KEY") or "").strip()


def check(headers) -> bool:
    """校验请求头; 未设 key 时恒通过 (本地免鉴权, 向后兼容)。"""
    key = api_key()
    if not key:
        return True
    auth = (headers.get("authorization") or "").strip()
    if auth == f"Bearer {key}":
        return True
    return (headers.get("x-api-key") or "").strip() == key


def _needs_auth(path: str) -> bool:
    return path.startswith("/api/") or path.startswith("/mcp")


async def enforce(request, call_next):
    """FastAPI 中间件逻辑: 只对 /api/* 与 /mcp 鉴权, HTML 页面保持公开。"""
    from starlette.responses import JSONResponse
    if _needs_auth(request.url.path) and not check(request.headers):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return await call_next(request)


def describe() -> Optional[str]:
    """返回鉴权状态描述 (doctor 用)。"""
    key = api_key()
    return "已启用 (LCLONE_API_KEY)" if key else "未启用 (本地免鉴权)"
