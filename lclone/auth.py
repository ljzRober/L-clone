"""鉴权: env `LCLONE_API_KEY` + 库中受管 token (只存 sha256 哈希)。

启用条件: 设了 `LCLONE_API_KEY`, 或库中存在至少一个未吊销 token;
两者皆无 → 本地免鉴权 (向后兼容)。
"""

from __future__ import annotations

import hashlib
import secrets
from typing import List, Optional

from . import config

TOKEN_PREFIX = "lclone_"


def api_key() -> str:
    return (config.get("LCLONE_API_KEY") or "").strip()


# ---------------------------------------------------------------- 受管 token
def hash_token(token: str) -> str:
    """token 明文 → sha256 hex (库里只存这个)。"""
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def create_token(conn, name: str) -> str:
    """生成一把新 token, 入库其哈希, 返回明文 (仅此一次, 之后不可再取)。"""
    name = (name or "").strip()
    if not name:
        raise ValueError("token 名称不能为空")
    token = TOKEN_PREFIX + secrets.token_hex(24)
    conn.execute("INSERT INTO access_tokens(name, token_hash) VALUES (?, ?)",
                 (name, hash_token(token)))
    conn.commit()
    return token


def list_tokens(conn) -> List:
    """列出所有 token 的元数据 (不含明文/哈希)。"""
    return conn.execute(
        "SELECT id, name, created_at, last_used_at, revoked_at "
        "FROM access_tokens ORDER BY id"
    ).fetchall()


def revoke_token(conn, name: Optional[str] = None,
                 token_id: Optional[int] = None) -> int:
    """吊销 token (置 revoked_at, 不物理删除); 返回受影响行数。"""
    if token_id is not None:
        cur = conn.execute(
            "UPDATE access_tokens SET revoked_at=datetime('now') "
            "WHERE id=? AND revoked_at IS NULL", (int(token_id),))
    elif name:
        cur = conn.execute(
            "UPDATE access_tokens SET revoked_at=datetime('now') "
            "WHERE name=? AND revoked_at IS NULL", (name,))
    else:
        raise ValueError("需要 name 或 id")
    conn.commit()
    return cur.rowcount


def _verify_token(presented: str, conn) -> bool:
    """命中未吊销 token 则更新 last_used_at 并返回 True。"""
    if not presented or conn is None:
        return False
    row = conn.execute(
        "SELECT id FROM access_tokens WHERE token_hash=? AND revoked_at IS NULL",
        (hash_token(presented),)).fetchone()
    if row is None:
        return False
    conn.execute("UPDATE access_tokens SET last_used_at=datetime('now') WHERE id=?",
                 (row["id"],))
    conn.commit()
    return True


def has_tokens(conn) -> bool:
    """库中是否存在任何 token (含已吊销)。"""
    if conn is None:
        return False
    return conn.execute("SELECT 1 FROM access_tokens LIMIT 1").fetchone() is not None


def enabled(conn=None) -> bool:
    """是否启用鉴权: env key 非空 或 库中已存在任何 token。

    一旦创建过 token, 鉴权即持续启用 (吊销最后一把也不会自动敞开)。
    """
    return bool(api_key()) or has_tokens(conn)


# ---------------------------------------------------------------- 请求校验
def _presented(headers) -> str:
    auth = (headers.get("authorization") or "").strip()
    if auth[:7].lower() == "bearer ":
        return auth[7:].strip()
    if auth:
        return auth
    return (headers.get("x-api-key") or "").strip()


def check(headers, conn=None) -> bool:
    """校验请求头。未启用鉴权 (env key 空 且 无未吊销 token) 时恒通过。"""
    key = api_key()
    presented = _presented(headers)
    if key and presented == key:
        return True
    if _verify_token(presented, conn):
        return True
    # 有 env key 却没过 = 拒绝; 从未配置过任何凭证 = 免鉴权
    return not key and not has_tokens(conn)


def _needs_auth(path: str) -> bool:
    return path.startswith("/api/") or path.startswith("/mcp")


async def enforce(request, call_next, conn=None, db_path: Optional[str] = None):
    """FastAPI 中间件逻辑: 只对 /api/* 与 /mcp 鉴权, HTML 页面保持公开。

    需要查库时: 优先用传入的 conn, 否则按 db_path 临时开连接 (仅受保护路径)。
    """
    from starlette.responses import JSONResponse
    if not _needs_auth(request.url.path):
        return await call_next(request)
    own = None
    try:
        if conn is None and db_path is not None:
            from . import db as db_mod
            own = db_mod.connect(db_path)
            conn = own
        if check(request.headers, conn=conn):
            return await call_next(request)
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    finally:
        if own is not None:
            own.close()


def describe() -> Optional[str]:
    """返回鉴权状态描述 (doctor 用)。"""
    key = api_key()
    return "已启用 (LCLONE_API_KEY)" if key else "未启用 (本地免鉴权)"
