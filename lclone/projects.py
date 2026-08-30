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
    """列出项目 (已移除的墓碑项目不显示)。

    mem_count 只数正式(active)记忆, 与 Web 架构图展示口径一致;
    pending_count 单列待确认决策数, 供 UI 角标提示。
    """
    return conn.execute(
        "SELECT p.*,"
        " (SELECT COUNT(*) FROM memories m WHERE m.project_id=p.id"
        "    AND m.status='active') AS mem_count,"
        " (SELECT COUNT(*) FROM memories m WHERE m.project_id=p.id"
        "    AND m.status='pending') AS pending_count,"
        " (SELECT COUNT(*) FROM specs_index s WHERE s.project_id=p.id) AS spec_count"
        " FROM projects p"
        " LEFT JOIN project_removals pr ON pr.project_id = p.id"
        " WHERE pr.project_id IS NULL ORDER BY p.id"
    ).fetchall()


def get_project(conn: sqlite3.Connection, project_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()


def is_removed(conn: sqlite3.Connection, project_id: int) -> bool:
    """读取时生命周期判定: 该项目是否已被移除 (墓碑登记)。"""
    return conn.execute(
        "SELECT 1 FROM project_removals WHERE project_id=?", (project_id,)
    ).fetchone() is not None


def remove_project(conn: sqlite3.Connection, project_id: int) -> None:
    """移除项目 (墓碑式, 不删行、不加状态字段):
    项目从列表消失、记忆停止加载, 但行与记忆都保留, 可 restore 复活;
    是否真正删除记忆由用户通过 suggest 提示后自行决定。
    """
    row = conn.execute("SELECT id, name FROM projects WHERE id=?",
                       (project_id,)).fetchone()
    if row is None:
        raise ValueError(f"项目不存在: {project_id}")
    conn.execute(
        "INSERT OR IGNORE INTO project_removals(project_id, name) VALUES (?,?)",
        (row["id"], row["name"]),
    )
    conn.commit()


def restore_project(conn: sqlite3.Connection, project_id: int) -> None:
    """复活被移除的项目: 从墓碑表除名, 记忆恢复加载。"""
    row = conn.execute("SELECT id, name FROM projects WHERE id=?",
                       (project_id,)).fetchone()
    if row is None:
        raise ValueError(f"项目不存在: {project_id}")
    conn.execute("DELETE FROM project_removals WHERE project_id=?", (project_id,))
    conn.commit()


def list_modules(conn: sqlite3.Connection, project_id: int) -> List[str]:
    """项目内声明的模块名列表 (modules 表)。"""
    return [r["name"] for r in conn.execute(
        "SELECT name FROM modules WHERE project_id=? ORDER BY name",
        (project_id,)).fetchall()]


def add_module(conn: sqlite3.Connection, project_id: int, name: str) -> int:
    """给项目声明一个模块 (允许空模块)。"""
    if get_project(conn, project_id) is None:
        raise ValueError(f"项目不存在: {project_id}")
    name = (name or "").strip()
    if not name:
        raise ValueError("模块名不能为空")
    try:
        cur = conn.execute("INSERT INTO modules(project_id, name) VALUES (?,?)",
                           (project_id, name))
        conn.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        raise ValueError(f"模块已存在: {name}")


def remove_module(conn: sqlite3.Connection, project_id: int, name: str) -> int:
    """删除项目下的一个模块, 并连带删除挂在该模块下的 decision 记忆。

    返回受影响(删除)的记忆条数。模块不存在时报错; 删除操作原子提交。
    记忆按 level='decision' + module=name 精确匹配连带删除 (note 无模块, 不受影响)。
    """
    if get_project(conn, project_id) is None:
        raise ValueError(f"项目不存在: {project_id}")
    name = (name or "").strip()
    if not name:
        raise ValueError("模块名不能为空")
    row = conn.execute("SELECT id FROM modules WHERE project_id=? AND name=?",
                       (project_id, name)).fetchone()
    if row is None:
        raise ValueError(f"模块不存在: {name}")
    # 连带删除该模块下的决策记忆 (decision 挂模块; note 无模块不受影响)
    cur = conn.execute("DELETE FROM memories WHERE project_id=? AND module=?",
                       (project_id, name))
    conn.execute("DELETE FROM modules WHERE project_id=? AND name=?",
                 (project_id, name))
    conn.commit()
    return cur.rowcount


def _git_toplevel(cwd: Optional[str] = None) -> Optional[Path]:
    """取目录所在 git 仓库根 (确定性); 不在 git 仓库内返回 None。"""
    import subprocess
    cwd = cwd or os.getcwd()
    try:
        proc = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    out = proc.stdout.strip()
    return Path(out) if out else None


def _match_registered(conn: sqlite3.Connection, repo: Path) -> Optional[int]:
    """在已注册项目中匹配给定 git 仓库根, 返回项目 id 或 None。"""
    for p in list_projects(conn):
        if not p["path"]:
            continue
        try:
            if Path(os.path.expanduser(p["path"])).resolve() == repo.resolve():
                return p["id"]
        except OSError:
            continue
    return None


def detect_project_by_git(conn: sqlite3.Connection,
                          cwd: Optional[str] = None) -> Optional[int]:
    """项目归属判定 (git 优先): 取目录的 git 仓库根, 匹配已注册项目。

    返回匹配的项目 id; 不在任何已注册项目的 git 仓库内则返回 None
    (调用方决定落到全局层或询问用户)。不自动注册 —— 自动注册走 resolve_project。
    """
    repo = _git_toplevel(cwd)
    if repo is None:
        return None
    return _match_registered(conn, repo)


def _unique_project_name(conn: sqlite3.Connection, base: str) -> str:
    """自动注册时保证项目名唯一: 与已有项目名冲突则追加 -2/-3... 后缀。"""
    name = (base or "project").strip()
    n = 2
    while conn.execute("SELECT 1 FROM projects WHERE name=?",
                       (name,)).fetchone() is not None:
        name = f"{base}-{n}"
        n += 1
    return name


def resolve_project(conn: sqlite3.Connection,
                    cwd: Optional[str] = None) -> tuple:
    """确定性项目归属 (代码强制): 返回 (status, project_id)。

    status:
      - "matched": git 仓库匹配到已注册项目, 记忆归该项目
      - "created": git 检测到仓库但未注册 → 自动注册 (name=仓库 basename,
                   path=仓库根, charter 留空), 记忆归新项目
      - "no_git":  不在任何 git 仓库内 → 需向用户确认 (新建项目 or 全局层),
                   调用方不得静默落全局
    """
    repo = _git_toplevel(cwd)
    if repo is None:
        return ("no_git", None)
    pid = _match_registered(conn, repo)
    if pid is not None:
        return ("matched", pid)
    pid = add_project(conn, _unique_project_name(conn, repo.name), str(repo), "")
    return ("created", pid)


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
    if is_removed(conn, project_id):
        raise ValueError(f"项目已移除: {project_id} (先 lclone proj restore)")
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
    if is_removed(conn, project_id):
        return ""  # 已移除项目不再注入上下文 (生命周期规则)
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
