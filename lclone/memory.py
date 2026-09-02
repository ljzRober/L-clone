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
import os
import re
import sqlite3
from typing import List, Optional

from . import db as db_mod
from . import llm
from .db import pack_vec, unpack_vec

LEVELS = ("insight",)

# ---- 记忆准入条件 (代码强制, 不依赖模型意图) ----
# 排除「做了什么」: 代码改动/接口/重构/bug 归 git & spec, 不进 lclone 记忆
DID_MARKERS = (
    "修复", "重构", "迁移", "回滚", "commit", "fix", "bug", "hotfix",
    "refactor", "新增端点", "改接口", "实现了一个",
)

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
                title: str = "", summary: str = "", key: str = "") -> int:
    cur = conn.execute(
        "INSERT INTO sessions(project_id, title, summary, session_key)"
        " VALUES (?,?,?,?)",
        (project_id, title, summary, key),
    )
    conn.commit()
    return cur.lastrowid


def _find_session_by_key(conn: sqlite3.Connection, key: str) -> Optional[int]:
    if not key:
        return None
    row = conn.execute(
        "SELECT id FROM sessions WHERE session_key=? ORDER BY id LIMIT 1", (key,)
    ).fetchone()
    return row["id"] if row else None


def _ensure_session(conn: sqlite3.Connection, project_id: Optional[int],
                    title: str, summary: str, key: str) -> int:
    """按 session_key 复用已有 session (一个外部会话对应一个 lclone session)。"""
    sid = _find_session_by_key(conn, key)
    if sid is not None:
        return sid
    return log_session(conn, project_id, title=title, summary=summary, key=key)


# ---------------------------------------------------------------- C 主动触发
def remember(conn: sqlite3.Connection, content: str, level: str = "insight",
             project_id: Optional[int] = None, reason: str = "",
             source_ref: str = "", confirmed: bool = False) -> int:
    level = level if level in LEVELS else "insight"
    emb = llm.embed_one(content)
    # 洞察强确认: decision 默认进 pending, 除非 confirmed=True (用户当场确认); note 恒 active
    status = "active" if (level != "insight" or confirmed) else "pending"
    if status == "active":
        cur = conn.execute(
            "INSERT INTO memories(project_id, level, content, reason, status,"
            " source_type, source_ref, embedding, confirmed_at)"
            " VALUES (?,?,?,?,'active','manual',?,?,datetime('now'))",
            (project_id, level, content, reason, source_ref, pack_vec(emb)),
        )
    else:
        cur = conn.execute(
            "INSERT INTO memories(project_id, level, content, reason, status,"
            " source_type, source_ref, embedding)"
            " VALUES (?,?,?,?,'pending','manual',?,?)",
            (project_id, level, content, reason, source_ref, pack_vec(emb)),
        )
    _store_links(conn, cur.lastrowid, content)
    conn.commit()
    return cur.lastrowid


# ---------------------------------------------------------------- B 自动捕获 + 确认
def _is_duplicate(conn: sqlite3.Connection, emb: List[float],
                  project_id: Optional[int] = None,
                  threshold: float = 0.92, limit: int = 300) -> bool:
    """写入去重: 与同一归属内已有的记忆向量相似度 >= threshold 视为重复。

    对 active + pending 都去重 (避免 post-commit 等反复触发时堆积重复草稿);
    project_id=None 时只对全局层去重; 指定项目时只对该项目去重。
    """
    q = ("SELECT embedding FROM memories"
         " WHERE status IN ('active','pending') AND embedding IS NOT NULL")
    params: list = []
    if project_id is None:
        q += " AND project_id IS NULL"
    else:
        q += " AND project_id=?"
        params.append(project_id)
    q += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    for r in conn.execute(q, params).fetchall():
        if r["embedding"] and _cosine(emb, unpack_vec(r["embedding"])) >= threshold:
            return True
    return False


def _has_marker(text: str, markers) -> bool:
    t = (text or "").lower()
    return any(m.lower() in t for m in markers)


def _filter_item(item: dict) -> Optional[dict]:
    """记忆准入条件 (代码强制): 在 LLM 提炼之后、落库之前做确定性过滤。

    返回过滤后的 item (固定 level=insight); None 表示不记忆。
    1. 排除「做了什么」: 命中 DID_MARKERS (代码改动/接口/重构/bug) → 归 git & spec。
    2. 内容过短(< 4 字)视为琐碎 → 丢弃 (仅拦空壳/单字噪音)。
    """
    content = (item.get("content") or "").strip()
    if not content:
        return None
    if _has_marker(content, DID_MARKERS):
        return None
    if len(content) < 4:
        return None
    return dict(item, level="insight")


def capture(conn: sqlite3.Connection, text: str,
            project_id: Optional[int] = None, title: str = "",
            session_key: str = "") -> List[int]:
    """自动捕获: LLM 提炼洞察 (insight)。note 通道已废弃, 由 evolution 承接。

    洞察(insight) → pending 草稿 (B 确认制, 防幻觉, 需 review 才生效)。
    准入: 每条内容先过 _filter_item (排除「做了什么」/ 过短琐碎)。
    不再每轮无条件记录原始文本 (note-append 已废弃); 提炼为空则本条不落库。
    """
    session_key = session_key or os.environ.get("DSH_SESSION_ID", "")
    session_id = _ensure_session(conn, project_id, title, text[:300], session_key)
    items = llm.extract_memories(text)
    reason = f"来自会话 #{session_id}"
    ref = f"session:{session_id}"
    ids = []
    for raw in items or []:
        if (raw.get("level") or "").lower() != "insight":
            continue
        it = _filter_item(raw)
        if it is None:
            continue
        content = (it.get("content") or "").strip()
        if not content:
            continue
        emb = llm.embed_one(content)
        # 洞察进草稿待确认 (B 类); 写入前去重
        if _is_duplicate(conn, emb, project_id=project_id):
            continue
        cur = conn.execute(
            "INSERT INTO memories(project_id, level, content, reason,"
            " status, source_type, source_ref, embedding)"
            " VALUES (?, ?, ?, ?, 'pending', 'auto', ?, ?)",
            (project_id, "insight", content, reason, ref, pack_vec(emb)),
        )
        _store_links(conn, cur.lastrowid, content)
        ids.append(cur.lastrowid)
    conn.commit()
    return ids


def pending_memories(conn: sqlite3.Connection) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT m.id, m.project_id, m.level, m.content, m.reason,"
        " m.status, m.source_type, m.source_ref, m.created_at,"
        " p.name AS project_name"
        " FROM memories m LEFT JOIN projects p ON p.id = m.project_id"
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
        "SELECT m.id, m.project_id, m.level, m.content, m.reason, m.status,"
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
           new_content: Optional[str] = None) -> None:
    """B 确认关卡: keep | edit | delete | promote。

    promote: 项目级记忆 提升到全局级 (project_id=NULL) 并确认落地 (status=active)——
    用于"确认弹窗里把项目级洞察升到全局层再落地"的一步操作。
    """
    action = action.lower()
    if action == "keep":
        conn.execute(
            "UPDATE memories SET status='active', confirmed_at=datetime('now')"
            " WHERE id=?",
            (memory_id,),
        )
    elif action == "promote":
        conn.execute(
            "UPDATE memories SET project_id=NULL, status='active',"
            " confirmed_at=datetime('now') WHERE id=?",
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
        _store_links(conn, memory_id, content)
    elif action == "delete":
        conn.execute("DELETE FROM memories WHERE id=?", (memory_id,))
    else:
        raise ValueError("action 必须是 keep/edit/delete/promote")
    conn.commit()


def set_status(conn: sqlite3.Connection, memory_id: int, status: str) -> None:
    conn.execute("UPDATE memories SET status=? WHERE id=?", (status, memory_id))
    conn.commit()


# ---------------------------------------------------------------- 进化资产 (evolution)
def create_evolution(conn: sqlite3.Connection, name: str, kind: str = "script",
                     content: str = "", ref: str = "", reason: str = "",
                     project_id: Optional[int] = None, source_ref: str = "",
                     status: str = "active") -> int:
    """沉淀一个可复用脚本/工具 (evolution)。

    存储: content = 项目无关的通用脚本/工具内容 (存记忆库本体);
          ref = 项目内脚本路径 (内容留仓库, 只留引用, 如 scripts/x.py)。
    `status`: active(实践中/在用) | stable(暂不再修改)。改脚本时用 update_evolution 同步。
    """
    cur = conn.execute(
        "INSERT INTO evolutions(project_id, kind, name, content, ref, reason,"
        " status, source_ref) VALUES (?,?,?,?,?,?,?,?)",
        (project_id, kind, name, content, ref, reason, status, source_ref),
    )
    conn.commit()
    return cur.lastrowid


def update_evolution(conn: sqlite3.Connection, evolution_id: int,
                     content: Optional[str] = None, ref: Optional[str] = None,
                     status: Optional[str] = None, name: Optional[str] = None,
                     reason: Optional[str] = None) -> None:
    """同步一个 evolution 到最新版本 (脚本被改时调用)。

    只更新给到的字段; content/ref/status 同步为最新的当前版本。
    """
    sets, params = [], []
    for col, v in (("content", content), ("ref", ref), ("status", status),
                   ("name", name), ("reason", reason)):
        if v is not None:
            sets.append(f"{col}=?")
            params.append(v)
    if sets:
        sets.append("updated_at=datetime('now')")
        params.append(evolution_id)
        conn.execute(
            f"UPDATE evolutions SET {', '.join(sets)} WHERE id=?", params)
    conn.commit()


def link_insight_to_evolution(conn: sqlite3.Connection, insight_id: int,
                              evolution_id: int) -> None:
    """建立 insight → evolution 链接 (一个进化资产可被 1..N 个 insight 支撑)。"""
    conn.execute(
        "INSERT OR IGNORE INTO evolution_links(insight_id, evolution_id)"
        " VALUES (?,?)",
        (insight_id, evolution_id),
    )
    conn.commit()


def evolutions_for_insight(conn: sqlite3.Connection, insight_id: int) -> List[dict]:
    """取某个 insight 指向的 evolution 资产 (召回 follow 用)。"""
    rows = conn.execute(
        "SELECT e.id, e.project_id, e.kind, e.name, e.content, e.ref,"
        " e.reason, e.status, e.created_at, p.name AS project_name"
        " FROM evolution_links l JOIN evolutions e ON e.id = l.evolution_id"
        " LEFT JOIN projects p ON p.id = e.project_id"
        " WHERE l.insight_id=? ORDER BY e.id",
        (insight_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def insights_for_evolution(conn: sqlite3.Connection, evolution_id: int) -> List[dict]:
    """取支撑某个 evolution 的 insight 列表。"""
    rows = conn.execute(
        "SELECT m.id, m.project_id, m.content, m.reason, p.name AS project_name"
        " FROM evolution_links l JOIN memories m ON m.id = l.insight_id"
        " LEFT JOIN projects p ON p.id = m.project_id"
        " WHERE l.evolution_id=? ORDER BY m.id",
        (evolution_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def list_evolutions(conn: sqlite3.Connection, project_id: Optional[int] = None,
                    status: Optional[str] = None, limit: int = 50) -> List[dict]:
    """列出进化资产 (按时间倒序), 支持按项目/状态过滤。"""
    q = (
        "SELECT e.id, e.project_id, e.kind, e.name, e.content, e.ref, e.reason,"
        " e.status, e.created_at, e.updated_at, p.name AS project_name"
        " FROM evolutions e LEFT JOIN projects p ON p.id = e.project_id"
        " WHERE 1=1"
    )
    params: list = []
    if project_id is not None:
        q += " AND e.project_id=?"
        params.append(project_id)
    if status:
        q += " AND e.status=?"
        params.append(status)
    q += " ORDER BY e.id DESC LIMIT ?"
    params.append(limit)
    return [dict(r) for r in conn.execute(q, params).fetchall()]


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
        " WHERE m.status=? AND m.level='insight' AND m.embedding IS NOT NULL"
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
                    "via_link": True, "via_evolution": False,
                })

    # 进化资产 follow: 命中 insight 后, 把它指向的 evolution 一起带出 (实践沉淀的工具/脚本)
    if base:
        evo_by_insight: dict = {}
        for x in base:
            evo_by_insight[x["id"]] = evolutions_for_insight(conn, x["id"])
        for x in base:
            for evo in evo_by_insight.get(x["id"], []):
                base.append({
                    "kind": "evolution",
                    "id": evo["id"], "project_id": evo["project_id"],
                    "project": evo.get("project_name") or "个人区",
                    "level": "evolution", "content": evo["content"] or evo["ref"],
                    "reason": evo["reason"], "source_ref": f"evolution:{evo['id']}",
                    "created_at": evo["created_at"], "score": None,
                    "via_evolution": True, "evo_name": evo["name"], "evo_kind": evo["kind"],
                })

    # 召回日志 (供 suggest 的"长期未用"信号)
    if base:
        conn.executemany(
            "INSERT INTO recall_log(memory_id) VALUES (?)",
            [(x["id"],) for x in base],
        )
        conn.commit()
    return base


# ---------------------------------------------------------------- 会话启动引导
def bootstrap(conn: sqlite3.Connection, query: str = "",
              project_id: Optional[int] = None, k: int = 5,
              global_limit: int = 20, project_limit: int = 20) -> str:
    """会话启动引导: charter + 全局层记忆(无条件注入) + 项目记忆(若落进已知项目) + 按 query 召回的相关记忆。

    按环境决定加载范围: 传了 project_id (会话落进已知项目) → 额外加载该项目的近 project_limit 条洞察;
    否则只加载全局层。返回一段可直接注入上下文的文本; 无内容时返回空字符串。
    CLI 与 MCP 共用此实现。
    """
    parts: List[str] = []
    if project_id is not None:
        proj = conn.execute(
            "SELECT charter FROM projects WHERE id=?", (project_id,)
        ).fetchone()
        if proj and proj["charter"]:
            parts.append(f"【项目方向】{proj['charter']}")
    g = conn.execute(
        "SELECT content, level FROM memories"
        " WHERE status='active' AND project_id IS NULL"
        " ORDER BY id DESC LIMIT ?",
        (global_limit,),
    ).fetchall()
    if g:
        # 全局层只呈现洞察 (note 已废弃); 按等级分组逻辑保留以便将来扩展
        dec = [r for r in g if r["level"] == "insight"]
        glines = []
        if dec:
            glines.append("[洞察]\n" + "\n".join(f"- {r['content']}" for r in dec))
        if glines:
            parts.append("【全局记忆】\n" + "\n".join(glines))
    # 项目记忆: 会话落进已知项目 → 额外加载该项目的近 project_limit 条洞察 (有界, 避免爆上下文)。
    if project_id is not None:
        pj = conn.execute(
            "SELECT content FROM memories"
            " WHERE status='active' AND project_id=? AND level='insight'"
            " ORDER BY id DESC LIMIT ?",
            (project_id, project_limit),
        ).fetchall()
        if pj:
            parts.append("【项目记忆】\n" + "\n".join(f"- {r['content']}" for r in pj))
    q = (query or "").strip()
    if q:
        items = recall(conn, q, k=k, project_id=project_id)
        if items:
            # 相关记忆按 项目 分组 (全局层按等级) —— 分类加载
            parts.append("【相关记忆】\n" + _format_grouped(items))
    # 待确认洞察: 每轮 bootstrap 都带上, 供"强确认"——有洞察草稿就主动找用户确认
    pend = conn.execute(
        "SELECT id, content FROM memories"
        " WHERE level='insight' AND status='pending'"
        " ORDER BY id DESC LIMIT 20"
    ).fetchall()
    if pend:
        parts.append("【待确认洞察】\n" + "\n".join(
            f"- #{r['id']} {r['content']}" for r in pend))
    return "\n\n".join(parts)


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


# ---------------------------------------------------------------- 分类加载 (按 项目 分组)
def _format_grouped(items: List[dict], show_id: bool = False) -> str:
    """把召回/加载结果按「项目」分组、项目内按等级分组渲染 (分类加载)。"""
    by_proj: dict = {}
    for i in items:
        by_proj.setdefault(i.get("project") or "个人区", {}).setdefault(
            i.get("level") or "", []).append(i)
    out = []
    for proj, levels in by_proj.items():
        out.append(f"[{proj}]")
        for lvl, mems in levels.items():
            ind = "  "
            if lvl:
                out.append(f"  [{lvl}]")
                ind = "    "
            for m in mems:
                if m.get("via_evolution"):
                    name = m.get("evo_name") or ""
                    body = m.get("content") or ""
                    out.append(f"{ind}- ✳ [{m.get('evo_kind','script')}] {name} : {body}")
                else:
                    tag = " 🔗" if m.get("via_link") else ""
                    nid = f"#{m['id']} " if show_id else ""
                    out.append(f"{ind}- {nid}[{m['level']}] {m['content']}{tag}")
    return "\n".join(out)


# ---------------------------------------------------------------- 整理合并 (LLM 语义合并)
def organize(conn: sqlite3.Connection) -> dict:
    """整理: LLM 把「语义相近、说的是同一件事」的洞察合并成一条综合描述。

    硬约束: 只能合并 同项目 + 同等级(insight) 的记忆;
        跨项目/跨等级的合并由代码强制校验拒绝 (LLM 输出后)。
    note 通道已废弃 (由 evolution 承接), note 合并逻辑已移除。
    """
    merged = removed = 0
    applied = []

    # ---- LLM 语义合并 (区域硬约束) ----
    rows = conn.execute(
        "SELECT m.id, m.project_id, m.level, m.content, p.name AS proj"
        " FROM memories m LEFT JOIN projects p ON p.id = m.project_id"
        " WHERE m.status='active' AND m.level='insight'"
        " ORDER BY m.project_id, m.level, m.id"
    ).fetchall()
    if not rows:
        return {"merged": merged, "removed": removed, "groups": applied}
    idx = {r["id"]: r for r in rows}
    body = "\n".join(
        f"#{r['id']} [({('全局' if r['project_id'] is None else r['proj'])})/"
        f"{r['level']}] {r['content'][:120]}"
        for r in rows
    )
    prompt = (
        "下面是一批记忆。请把「语义相近、说的是同一件事」的记忆合并成一条综合描述。\n"
        "硬规则: 只能合并「项目、等级(insight)」都相同的记忆; "
        "跨项目/跨等级一律不合并。\n"
        "合并内容覆盖各条所有要点, 不遗漏, 中文。只有真正相近(同一主题/同一规则)才合并;\n"
        "不相关的保持不动, 不要出现在输出里。\n"
        "只输出 JSON 数组: [{\"content\": \"合并后描述\", \"ids\": [原id...]}], "
        "没有可合并的就输出 []\n\n" + body
    )
    groups = llm.chat_json(prompt) or []
    for g in groups:
        try:
            ids = [int(x) for x in (g.get("ids") or [])]
        except (ValueError, TypeError):
            continue
        content = (g.get("content") or "").strip()
        if not content or len(ids) < 2:
            continue
        members = [idx[i] for i in ids if i in idx]
        if len(members) < 2:
            continue
        key = (members[0]["project_id"], members[0]["level"])
        # 不能跨区域: 所有成员必须 项目/等级 完全一致
        if any((m["project_id"], m["level"]) != key for m in members):
            continue
        emb = llm.embed_one(content)
        cur = conn.execute(
            "INSERT INTO memories(project_id, level, content, reason, status,"
            " source_type, source_ref, embedding, confirmed_at)"
            " VALUES (?,?,?,?,'active','manual','',?,datetime('now'))",
            (key[0], key[1], content, "整理合并", pack_vec(emb)),
        )
        # 删除原记忆 (memory_links/recall_log 外键级联清理, FTS 由触发器清理)
        conn.execute("DELETE FROM memories WHERE id IN (%s)"
                     % ",".join("?" * len(ids)), ids)
        merged += 1
        removed += len(ids) - 1
        applied.append({"id": cur.lastrowid, "content": content, "merged": ids})
    conn.commit()
    return {"merged": merged, "removed": removed, "groups": applied}
