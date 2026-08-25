"""记忆模块 (L0/L1 层): 流水、主动记忆、自动捕获 + 确认、回顾检索。

写入策略:
  C 主动触发 (remember)        -> 直接 active, 你说算
  B 自动捕获 (capture)         -> 进 pending 草稿区, 你 review 后生效

生命周期 (读取时决定, 不落状态字段):
  - 全局层 (project_id=NULL) 的记忆永远加载
  - 项目记忆只在项目"活着"时加载; 项目被 rm (墓碑登记) 后不再加载
  - 内容里的 [[m:12]] 链接: 召回时顺藤把被链接的记忆一起带出
"""

from __future__ import annotations

import math
import re
import sqlite3
from typing import List, Optional

from . import db as db_mod
from . import llm
from .db import pack_vec, unpack_vec

LEVELS = ("note", "decision", "milestone")

# 链接语法: 在记忆内容里写 [[m:12]] 即链接到记忆 #12
LINK_RE = re.compile(r"\[\[m:(\d+)\]\]")


# ---------------------------------------------------------------- 记忆链接
def _extract_links(content: str) -> List[int]:
    return [int(x) for x in LINK_RE.findall(content or "")]


def _store_links(conn: sqlite3.Connection, memory_id: int, content: str) -> None:
    """解析内容里的 [[m:N]] 并重建该记忆发出的链接 (不 commit, 由调用方统一提交)。"""
    conn.execute("DELETE FROM memory_links WHERE source_id=?", (memory_id,))
    for target in _extract_links(content):
        if target == memory_id:
            continue  # 不允许自引用
        conn.execute(
            "INSERT OR IGNORE INTO memory_links(source_id, target_id)"
            " VALUES (?,?)",
            (memory_id, target),
        )


def _alive_filter() -> str:
    """读取时生命周期规则: 排除所属项目已被移除 (墓碑) 的记忆。"""
    return (
        " AND NOT EXISTS (SELECT 1 FROM project_removals pr"
        " WHERE pr.project_id = m.project_id)"
    )


# ---------------------------------------------------------------- L0 流水
def log_session(conn: sqlite3.Connection, project_id: Optional[int] = None,
                title: str = "", summary: str = "") -> int:
    cur = conn.execute(
        "INSERT INTO sessions(project_id, title, summary) VALUES (?,?,?)",
        (project_id, title, summary),
    )
    conn.commit()
    return cur.lastrowid


# ---------------------------------------------------------------- C 主动触发
def remember(conn: sqlite3.Connection, content: str, level: str = "decision",
             project_id: Optional[int] = None, reason: str = "",
             source_ref: str = "", module: str = "") -> int:
    level = level if level in LEVELS else "decision"
    emb = llm.embed_one(content)
    cur = conn.execute(
        "INSERT INTO memories(project_id, level, module, content, reason, status,"
        " source_type, source_ref, embedding, confirmed_at)"
        " VALUES (?,?,?,?,?,'active','manual',?,?,datetime('now'))",
        (project_id, level, module.strip(), content, reason, source_ref,
         pack_vec(emb)),
    )
    _store_links(conn, cur.lastrowid, content)
    conn.commit()
    return cur.lastrowid


# ---------------------------------------------------------------- B 自动捕获 + 确认
def capture(conn: sqlite3.Connection, text: str,
            project_id: Optional[int] = None, title: str = "",
            module: str = "") -> List[int]:
    """自动捕获: LLM 提炼决策 -> 写入 pending 草稿区, 待确认。"""
    session_id = log_session(conn, project_id, title=title, summary=text[:300])
    decisions = llm.extract_decisions(text)
    ids = []
    for d in decisions:
        emb = llm.embed_one(d)
        cur = conn.execute(
            "INSERT INTO memories(project_id, level, module, content, reason, status,"
            " source_type, source_ref, embedding)"
            " VALUES (?, 'decision', ?, ?, ?, 'pending', 'auto', ?, ?)",
            (project_id, module.strip(), d, f"来自会话 #{session_id}",
             f"session:{session_id}", pack_vec(emb)),
        )
        _store_links(conn, cur.lastrowid, d)
        ids.append(cur.lastrowid)
    conn.commit()
    return ids


def pending_memories(conn: sqlite3.Connection) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT m.*, p.name AS project_name FROM memories m"
        " LEFT JOIN projects p ON p.id = m.project_id"
        " WHERE m.status='pending' ORDER BY m.id"
    ).fetchall()


def list_memories(conn: sqlite3.Connection,
                  project_id: Optional[int] = None,
                  level: Optional[str] = None,
                  status: Optional[str] = "active",
                  limit: int = 20,
                  layer: Optional[str] = None) -> List[sqlite3.Row]:
    """列出记忆 (按时间倒序), 支持按项目/等级/状态过滤。

    layer="global" 时只看全局层 (project_id IS NULL) 的记忆。
    """
    q = (
        "SELECT m.id, m.project_id, m.level, m.module, m.content, m.reason, m.status,"
        " m.source_type, m.source_ref, m.created_at,"
        " p.name AS project_name"
        " FROM memories m LEFT JOIN projects p ON p.id = m.project_id"
        " WHERE 1=1"
    )
    params: list = []
    if layer == "global":
        q += " AND m.project_id IS NULL"
    elif project_id is not None:
        q += " AND m.project_id=?"
        params.append(project_id)
    if level:
        q += " AND m.level=?"
        params.append(level)
    if status:
        q += " AND m.status=?"
        params.append(status)
    q += " ORDER BY m.id DESC LIMIT ?"
    params.append(limit)
    return conn.execute(q, params).fetchall()


def review(conn: sqlite3.Connection, memory_id: int, action: str,
           new_content: Optional[str] = None,
           new_module: Optional[str] = None) -> None:
    """B 确认关卡: keep | edit | delete。"""
    action = action.lower()
    if action == "keep":
        conn.execute(
            "UPDATE memories SET status='active', confirmed_at=datetime('now')"
            " WHERE id=?",
            (memory_id,),
        )
    elif action == "edit":
        content = (new_content or "").strip()
        if not content:
            raise ValueError("edit 需要提供 new_content")
        emb = llm.embed_one(content)
        conn.execute(
            "UPDATE memories SET content=?, embedding=?, status='active',"
            " confirmed_at=datetime('now') WHERE id=?",
            (content, pack_vec(emb), memory_id),
        )
        if new_module is not None:
            conn.execute("UPDATE memories SET module=? WHERE id=?",
                         (new_module.strip(), memory_id))
        _store_links(conn, memory_id, content)
    elif action == "delete":
        conn.execute("DELETE FROM memories WHERE id=?", (memory_id,))
    else:
        raise ValueError("action 必须是 keep/edit/delete")
    conn.commit()


def set_status(conn: sqlite3.Connection, memory_id: int, status: str) -> None:
    conn.execute("UPDATE memories SET status=? WHERE id=?", (status, memory_id))
    conn.commit()


# ---------------------------------------------------------------- 上升 / 下降 (生命周期)
def promote(conn: sqlite3.Connection, memory_id: int) -> None:
    """上升: 项目记忆 -> 全局层 (project_id=NULL, 永不过期, 多项目共读)。"""
    if conn.execute("SELECT 1 FROM memories WHERE id=?",
                    (memory_id,)).fetchone() is None:
        raise ValueError(f"记忆不存在: {memory_id}")
    conn.execute("UPDATE memories SET project_id=NULL WHERE id=?", (memory_id,))
    conn.commit()


def demote(conn: sqlite3.Connection, memory_id: int, project_id: int) -> None:
    """下降: 记忆挂到指定项目 (从全局层降下来, 或项目 A 横向搬到项目 B)。"""
    if conn.execute("SELECT 1 FROM memories WHERE id=?",
                    (memory_id,)).fetchone() is None:
        raise ValueError(f"记忆不存在: {memory_id}")
    if conn.execute("SELECT 1 FROM projects WHERE id=?",
                    (project_id,)).fetchone() is None:
        raise ValueError(f"项目不存在: {project_id}")
    conn.execute("UPDATE memories SET project_id=? WHERE id=?",
                 (project_id, memory_id))
    conn.commit()


def linked_memories(conn: sqlite3.Connection, memory_id: int,
                    limit: int = 5) -> List[dict]:
    """取出 #memory_id 链接指向的记忆 (一层)。"""
    rows = conn.execute(
        "SELECT m.id, m.project_id, m.level, m.content, m.reason, m.source_ref,"
        " m.created_at, p.name AS project_name"
        " FROM memory_links l"
        " JOIN memories m ON m.id = l.target_id"
        " LEFT JOIN projects p ON p.id = m.project_id"
        " WHERE l.source_id=? AND m.status='active'"
        + _alive_filter() +
        " ORDER BY l.id LIMIT ?",
        (memory_id, limit),
    ).fetchall()
    return [{
        "id": r["id"], "project_id": r["project_id"],
        "project": r["project_name"] or "个人区",
        "level": r["level"], "content": r["content"],
        "reason": r["reason"], "source_ref": r["source_ref"],
        "created_at": r["created_at"], "via_link": True,
    } for r in rows]


# ---------------------------------------------------------------- 回顾环
def _keyword_scores(conn: sqlite3.Connection, query: str,
                    ids: List[int]) -> dict:
    scores: dict = {}
    q = " ".join(query.split())
    if len(q) < 3:
        return scores
    try:
        rows = conn.execute(
            "SELECT rowid, bm25(memories_fts) AS s FROM memories_fts"
            " WHERE memories_fts MATCH ?",
            (f'"{q}"',),
        ).fetchall()
    except Exception:
        return scores
    for r in rows:
        if r["rowid"] in ids:
            scores[r["rowid"]] = -r["s"]
    return scores


def recall(conn: sqlite3.Connection, query: str, k: int = 5,
           project_id: Optional[int] = None, alpha: float = 0.7,
           status: str = "active", follow_links: bool = True,
           link_extra: int = 3) -> List[dict]:
    """混合检索: 向量余弦 + FTS 关键词加权, 返回记忆及其项目归属。

    生命周期规则 (读取时决定, 不落状态):
      - 已移除项目 (墓碑) 的记忆不加载
      - follow_links=True 时, 顺 [[m:N]] 链接把被链接记忆一起带出 (一层, 限量)
    每次召回都会写入 recall_log, 供"长期未用"删除提示使用。
    """
    qv = llm.embed_one(query)
    rows = conn.execute(
        "SELECT m.id, m.project_id, m.level, m.content, m.reason, m.source_ref,"
        " m.created_at, m.embedding, p.name AS project_name"
        " FROM memories m LEFT JOIN projects p ON p.id = m.project_id"
        " WHERE m.status=? AND m.embedding IS NOT NULL"
        + _alive_filter()
        + (" AND m.project_id=?" if project_id is not None else ""),
        (status, project_id) if project_id is not None else (status,),
    ).fetchall()

    scored = []
    for r in rows:
        ev = unpack_vec(r["embedding"])
        s = sum(a * b for a, b in zip(qv, ev))
        scored.append((s, r))
    if not scored:
        return []
    mx = max(s for s, _ in scored)
    mn = min(s for s, _ in scored)
    span = (mx - mn) or 1.0
    ids = [r["id"] for _, r in scored]
    kscores = _keyword_scores(conn, query, ids)
    items = []
    for s, r in scored:
        norm = (s - mn) / span
        kscore = kscores.get(r["id"], 0.0)
        if kscores:
            kmx = max(kscores.values()) or 1.0
            knorm = kscore / kmx
        else:
            knorm = 0.0
        combo = alpha * norm + (1.0 - alpha) * knorm
        items.append({
            "id": r["id"], "project_id": r["project_id"],
            "project": r["project_name"] or "个人区",
            "level": r["level"], "content": r["content"],
            "reason": r["reason"], "source_ref": r["source_ref"],
            "created_at": r["created_at"], "score": round(combo, 4),
        })
    items.sort(key=lambda x: x["score"], reverse=True)
    base = items[:k]

    # 顺藤摸瓜: 把被链接的记忆带出来 (不限于本项目的竖向切分)
    if follow_links and link_extra > 0 and base:
        target_ids = [r["target_id"] for r in conn.execute(
            "SELECT DISTINCT target_id FROM memory_links WHERE source_id IN (%s)"
            % ",".join("?" * len(base)),
            tuple(x["id"] for x in base),
        ).fetchall()]
        have = {x["id"] for x in base}
        wanted = [t for t in target_ids if t not in have][:link_extra]
        if wanted:
            rows2 = conn.execute(
                "SELECT m.id, m.project_id, m.level, m.content, m.reason,"
                " m.source_ref, m.created_at, p.name AS project_name"
                " FROM memories m LEFT JOIN projects p ON p.id = m.project_id"
                " WHERE m.status=? AND m.id IN (%s)"
                % ",".join("?" * len(wanted))
                + _alive_filter(),
                (status, *wanted),
            ).fetchall()
            for r in rows2:
                base.append({
                    "id": r["id"], "project_id": r["project_id"],
                    "project": r["project_name"] or "个人区",
                    "level": r["level"], "content": r["content"],
                    "reason": r["reason"], "source_ref": r["source_ref"],
                    "created_at": r["created_at"], "score": None,
                    "via_link": True,
                })

    # 召回日志 (供 suggest 的"长期未用"信号)
    if base:
        conn.executemany(
            "INSERT INTO recall_log(memory_id) VALUES (?)",
            [(x["id"],) for x in base],
        )
        conn.commit()
    return base


# ---------------------------------------------------------------- 删除提示 (算法建议, 删除仍由用户决定)
def _cosine(a: List[float], b: List[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def suggest(conn: sqlite3.Connection, dup_threshold: float = 0.92,
            stale_days: int = 7, unused_days: int = 30,
            dup_limit: int = 300, max_each: int = 20) -> List[dict]:
    """扫描出"可能该清理"的记忆候选, 附原因与建议命令; 是否删除由用户决定。

    信号:
      1. 疑似重复    —— 向量相似度 >= dup_threshold 的 active 记忆两两配对
      2. 长期未确认  —— pending 草稿超过 stale_days 天没 review
      3. 长期未召回  —— active 记忆在 unused_days 天内从未被召回 (基于 recall_log)
      4. 项目已移除  —— 所属项目被 rm (墓碑), 按生命周期规则已不再加载
    """
    out: List[dict] = []

    def _emit(mid: int, content: str, proj: str, created_at: str,
              reason: str) -> None:
        out.append({
            "id": mid, "project": proj, "content": content,
            "created_at": created_at, "reason": reason,
            "hint": f"lclone review --id {mid} --action delete",
        })

    # 1) 疑似重复
    rows = conn.execute(
        "SELECT m.id, m.content, m.created_at, m.embedding,"
        " p.name AS project_name FROM memories m"
        " LEFT JOIN projects p ON p.id = m.project_id"
        " WHERE m.status='active' AND m.embedding IS NOT NULL"
        " ORDER BY m.id DESC LIMIT ?",
        (dup_limit,),
    ).fetchall()
    n_dup = 0
    for i in range(len(rows)):
        if n_dup >= max_each:
            break
        for j in range(i + 1, len(rows)):
            sim = _cosine(unpack_vec(rows[i]["embedding"]),
                          unpack_vec(rows[j]["embedding"]))
            if sim >= dup_threshold:
                _emit(rows[i]["id"], rows[i]["content"],
                      rows[i]["project_name"] or "个人区",
                      rows[i]["created_at"],
                      f"与 #{rows[j]['id']} 疑似重复 (相似度 {sim:.2f})")
                n_dup += 1
                break

    # 2) 长期未确认的草稿
    for r in conn.execute(
        "SELECT m.id, m.content, m.created_at, p.name AS project_name"
        " FROM memories m LEFT JOIN projects p ON p.id = m.project_id"
        " WHERE m.status='pending'"
        " AND m.created_at < datetime('now', ?) ORDER BY m.id LIMIT ?",
        (f"-{stale_days} days", max_each),
    ).fetchall():
        _emit(r["id"], r["content"], r["project_name"] or "个人区",
              r["created_at"],
              f"草稿超过 {stale_days} 天未确认")

    # 3) 长期未被召回
    for r in conn.execute(
        "SELECT m.id, m.content, m.created_at, p.name AS project_name"
        " FROM memories m LEFT JOIN projects p ON p.id = m.project_id"
        " WHERE m.status='active' AND NOT EXISTS ("
        "   SELECT 1 FROM recall_log rl WHERE rl.memory_id = m.id"
        "   AND rl.recalled_at > datetime('now', ?))"
        " ORDER BY m.id LIMIT ?",
        (f"-{unused_days} days", max_each),
    ).fetchall():
        _emit(r["id"], r["content"], r["project_name"] or "个人区",
              r["created_at"], f"{unused_days} 天内从未被召回")

    # 4) 所属项目已移除 (生命周期已结束, 不再加载)
    for r in conn.execute(
        "SELECT m.id, m.content, m.created_at, pr.name AS removed_from"
        " FROM memories m JOIN project_removals pr ON pr.project_id = m.project_id"
        " WHERE m.status != 'pending' ORDER BY m.id LIMIT ?",
        (max_each,),
    ).fetchall():
        _emit(r["id"], r["content"], r["removed_from"] or "已移除项目",
              r["created_at"], "所属项目已移除, 已停止加载")

    return out
