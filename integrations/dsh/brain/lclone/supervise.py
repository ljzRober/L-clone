"""规范环: 监督新提议是否符合项目的边界条件与规格。

流程: 新提议 -> 召回项目上下文 (方向/决策/spec 索引原文) -> LLM 逐条对照
      -> 输出 ✅通过 / ⚠️警告 / ❌违反 检查报告。
"""

from __future__ import annotations

import sqlite3
from typing import Optional

from . import llm
from . import projects as proj_mod


def supervise(conn: sqlite3.Connection, proposal: str,
              project_id: Optional[int] = None) -> dict:
    if project_id is None:
        raise ValueError("监督需要指定项目 (--proj)")
    ctx = proj_mod.project_context(conn, project_id)
    if not ctx:
        return {"ok": False, "error": "项目不存在或没有可监督的内容", "report": ""}
    report = llm.check_boundaries(ctx, proposal)
    return {"ok": True, "project_id": project_id, "report": report}
