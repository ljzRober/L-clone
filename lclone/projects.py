"""项目模块 (竖向分层): 项目注册 + spec 格式无关索引。

设计原则:
  - 具体事务 (spec 全文/代码/PR) 永远留在项目仓库, 大脑只建索引和记忆。
  - spec 格式不绑定任何工具 (OpenSpec/ADR 只是约定之一): 通过路径模式
    启发式分类, 新增格式只需扩展 detect_format 和 PROJECT_SPEC_DIRS。
  - 索引内容: 定位信息 + 标题 + 摘要 + 哈希; 权威以 repo 为准。
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from pathlib import Path
from typing import List, Optional

from . import db as db_mod

# 启发式目录/文件模式 -> 格式名 (可扩展)
_SPEC_PATTERNS = [
    (re.compile(r"(^|[/\\])\.specs[/\\]"), "openspec"),
    (re.compile(r"(^|[/\\])specs?[/\\]"), "openspec"),
    (re.compile(r"(^|[/\\])doc[/\\]adr[/\\]"), "adr"),
    (re.compile(r"(^|[/\\])docs[/\\]adr[/\\]"), "adr"),
    (re.compile(r"(^|[/\\])adr[-_]?\d", re.IGNORECASE), "adr"),
    (re.compile(r"(^|[/\\])spec\.md$", re.IGNORECASE), "spec"),
]

_SKIP_DIRS = {".git", "node_modules", "dist", "build", "__pycache__",
              ".venv", "venv", ".idea", ".vscode", "target", ".next"}


def detect_format(rel_path: str) -> str:
    for pat, fmt in _SPEC_PATTERNS:
        if pat.search(rel_path):
            return fmt
    name = Path(rel_path).name.lower()
    if name.startswith(("spec", "adr")) or "spec" in name or "adr" in name:
        return "markdown-spec"
    return "markdown"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _first_heading(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#"):
            return line.lstrip("#").strip()
    return ""


def _summary(text: str, n: int = 300) -> str:
    t = re.sub(r"\s+", " ", text).strip()
    return t[:n]


def add_project(conn: sqlite3.Connection, name: str, path: str = "",
                charter: str = "") -> int:
    cur = conn.execute(
        "INSERT INTO projects(name, path, charter) VALUES (?,?,?)",
        (name.strip(), path.strip(), charter.strip()),
    )
    conn.commit()
    return cur.lastrowid


def list_projects(conn: sqlite3.Connection) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT p.*,"
        " (SELECT COUNT(*) FROM memories m WHERE m.project_id=p.id) AS mem_count,"
        " (SELECT COUNT(*) FROM specs_index s WHERE s.project_id=p.id) AS spec_count"
        " FROM projects p ORDER BY p.id"
    ).fetchall()


def get_project(conn: sqlite3.Connection, project_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()


def remove_project(conn: sqlite3.Connection, project_id: int) -> None:
    conn.execute("DELETE FROM projects WHERE id=?", (project_id,))
    conn.commit()


def _walk_spec_files(root: Path) -> List[Path]:
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fn in filenames:
            if not fn.lower().endswith(".md"):
                continue
            p = Path(dirpath) / fn
            rel = p.relative_to(root).as_posix()
            # 只索引看起来像 spec/决策/规划 的文件, 不索引普通 README 正文
            if detect_format(rel) != "markdown" or re.search(
                r"(spec|adr|plan|design|roadmap|charter|boundar)",
                rel, re.IGNORECASE,
            ):
                out.append(p)
    out.sort()
    return out


def sync_project(conn: sqlite3.Connection, project_id: int) -> dict:
    """扫描项目仓库中的 spec 类文件, 建立/更新索引 (只读 repo, 不修改它)。"""
    proj = get_project(conn, project_id)
    if proj is None:
        raise ValueError(f"项目不存在: {project_id}")
    root = Path(os.path.expanduser(proj["path"]))
    if not root.exists() or not root.is_dir():
        raise ValueError(f"项目路径不存在或不是目录: {root}")

    added = updated = unchanged = 0
    for path in _walk_spec_files(root):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = path.relative_to(root).as_posix()
        sha = _sha256(text)
        fmt = detect_format(rel)
        title = _first_heading(text) or path.stem
        summ = _summary(text)
        row = conn.execute(
            "SELECT id, sha FROM specs_index WHERE project_id=? AND rel_path=?",
            (project_id, rel),
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO specs_index(project_id, rel_path, format, title,"
                " summary, sha) VALUES (?,?,?,?,?,?)",
                (project_id, rel, fmt, title, summ, sha),
            )
            added += 1
        elif row["sha"] != sha:
            conn.execute(
                "UPDATE specs_index SET format=?, title=?, summary=?, sha=?,"
                " last_indexed_at=datetime('now') WHERE id=?",
                (fmt, title, summ, sha, row["id"]),
            )
            updated += 1
        else:
            unchanged += 1
    conn.commit()
    return {"added": added, "updated": updated, "unchanged": unchanged}


def project_context(conn: sqlite3.Connection, project_id: int,
                    spec_budget: int = 6000) -> str:
    """拼出监督环用的项目上下文: charter + 决策 + spec 摘要/原文片段。

    spec 原文优先从 repo 读取 (权威), 读不到则退回索引摘要。
    """
    proj = get_project(conn, project_id)
    if proj is None:
        return ""
    parts = []
    if proj["charter"]:
        parts.append(f"【项目方向】{proj['charter']}")
    decisions = conn.execute(
        "SELECT content, created_at FROM memories"
        " WHERE project_id=? AND status='active' AND level='decision'"
        " ORDER BY id DESC LIMIT 15",
        (project_id,),
    ).fetchall()
    if decisions:
        dlines = [f"- {d['content']} ({d['created_at'][:10]})" for d in decisions]
        parts.append("【已确认决策】\n" + "\n".join(dlines))

    specs = conn.execute(
        "SELECT rel_path, format, title, summary, sha FROM specs_index"
        " WHERE project_id=? ORDER BY rel_path",
        (project_id,),
    ).fetchall()
    if specs:
        blocks = []
        budget = spec_budget
        root = Path(os.path.expanduser(proj["path"]))
        for s in specs:
            body = ""
            p = root / s["rel_path"]
            if p.exists():
                try:
                    body = p.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    body = ""
            body = body or s["summary"]
            take = min(len(body), max(800, budget // max(len(specs), 1)))
            blocks.append(
                f"--- {s['rel_path']} [{s['format']}] ---\n{body[:take]}"
            )
            budget -= take
        parts.append("【项目规格/边界 (来自仓库)】\n" + "\n".join(blocks))
    return "\n\n".join(parts)
