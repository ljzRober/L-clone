"""回顾环: 带记忆的问答。

流程: 提问 -> 召回相关记忆 (项目或个人区) -> 注入上下文 -> LLM 回答。
会话历史按 thread 归档, 支持跨会话上下文延续。
"""

from __future__ import annotations

import sqlite3
import uuid
from typing import Optional

from . import db as db_mod
from . import llm
from . import memory as mem_mod
from . import projects as proj_mod


def _ensure_thread(conn: sqlite3.Connection, thread_id: Optional[str],
                   project_id: Optional[int]) -> str:
    tid = thread_id or uuid.uuid4().hex
    row = conn.execute("SELECT id FROM threads WHERE id=?", (tid,)).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO threads(id, project_id) VALUES (?,?)", (tid, project_id)
        )
        conn.commit()
    return tid


def _history(conn: sqlite3.Connection, thread_id: str, limit: int = 12) -> list:
    rows = conn.execute(
        "SELECT role, content FROM messages WHERE thread_id=? ORDER BY id"
        " LIMIT ?",
        (thread_id, limit),
    ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in rows]


def _save(conn: sqlite3.Connection, thread_id: str, role: str, content: str) -> None:
    conn.execute(
        "INSERT INTO messages(thread_id, role, content) VALUES (?,?,?)",
        (thread_id, role, content),
    )
    conn.commit()


def ask(conn: sqlite3.Connection, question: str,
        project_id: Optional[int] = None, thread_id: Optional[str] = None,
        k: int = 5, with_specs: bool = True) -> dict:
    tid = _ensure_thread(conn, thread_id, project_id)

    recalls = mem_mod.recall(conn, question, k=k, project_id=project_id)
    context_parts = []
    if recalls:
        lines = [
            f"- [{r['project']}/{r['level']}] {r['content']}"
            + (f" (来源: {r['source_ref']})" if r["source_ref"] else "")
            for r in recalls
        ]
        context_parts.append("【记忆】\n" + "\n".join(lines))

    if project_id is not None and with_specs:
        ctx = proj_mod.project_context(conn, project_id, spec_budget=5000)
        if ctx:
            context_parts.append(ctx)

    system = (
        "你是用户的外置大脑。基于给出的【记忆】和【项目上下文】回答, "
        "不要编造未给出的信息; 记忆不足时明确说明。回答用中文, 简洁、可执行。"
    )
    if context_parts:
        system += "\n\n以下是相关内容:\n" + "\n\n".join(context_parts)

    history = _history(conn, tid)
    messages = [{"role": "system", "content": system}] + history + [
        {"role": "user", "content": question}
    ]
    answer = llm.chat(messages)
    _save(conn, tid, "user", question)
    _save(conn, tid, "assistant", answer)
    return {
        "thread_id": tid,
        "answer": answer,
        "recalls": recalls,
        "project_id": project_id,
    }
