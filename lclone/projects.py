"""项目模块 (竖向分层): 项目注册 + spec 格式无关索引。

设计原则:
  - 具体事务 (spec 全文/代码/PR) 永远留在项目仓库, 大脑只建索引和记忆。
  - spec 格式不绑定任何工具 (OpenSpec/ADR 只是约定之一): 通过路径模式
    启发式分类, 新增格式只需扩展 detect_format 和 PROJECT_SPEC_DIRS。
  - 索引内容: 定位信息 + 标题 + 摘要 + 哈希; 权威以 repo 为准。
"""

from __future__ import annotations

import hashlib
import json
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
                charter: str = "", remote: str = "") -> int:
    cur = conn.execute(
        "INSERT INTO projects(name, path, charter, remote) VALUES (?,?,?,?)",
        (name.strip(), path.strip(), charter.strip(),
         normalize_remote(remote) if remote else ""),
    )
    conn.commit()
    return cur.lastrowid


def list_projects(conn: sqlite3.Connection) -> List[sqlite3.Row]:
    """列出项目 (已移除的墓碑项目不显示)。

    mem_count 只数正式(active)记忆, 与 Web 架构图展示口径一致;
    pending_count 单列待确认洞察数, 供 UI 角标提示。
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


_REMOTE_SCHEMES = ("ssh://", "git://", "https://", "http://")


def normalize_remote(url: str) -> str:
    """把 git remote 地址归一化为 `host/group/repo`, 作为项目身份键。

    规则: 去协议前缀与凭据; **无协议**的 scp 形式 `[user@]host:path` 拆开 (带协议的
    `host:port/path` 不拆, 端口保留为 `host:port`); 去尾 `/` 与 `.git`; host 小写;
    **path 保留大小写** (自建 GitLab 可能大小写敏感, 宁可少合并也不误合并)。
    无 remote / 空串返回空串, 由调用方回落 path。
    """
    s = (url or "").strip()
    if not s:
        return ""
    had_scheme = "://" in s
    if had_scheme:
        s = s.split("://", 1)[1]
    if "@" in s.split("/", 1)[0]:            # 去凭据 (user@ 或 user:token@)
        s = s.split("@", 1)[1]
    if not had_scheme and ":" in s.split("/", 1)[0]:   # scp 形式 host:path
        host, _, path = s.partition(":")
        s = host + "/" + path.lstrip("/")
    s = s.rstrip("/")
    if s.lower().endswith(".git"):
        s = s[:-4]
    head, _, rest = s.partition("/")
    if ":" in head:                          # host:port → host 小写, 端口保留
        h, _, port = head.partition(":")
        head = h.lower() + ":" + port
    else:
        head = head.lower()
    return f"{head}/{rest}" if rest else head


def git_remote(cwd: Optional[str] = None) -> str:
    """取仓库 origin 的 remote 地址; 无 origin 取第一条 remote; 无仓库/无 remote 返回空串。"""
    import subprocess
    base = cwd or os.getcwd()
    try:
        proc = subprocess.run(["git", "-C", base, "remote", "get-url", "origin"],
                              capture_output=True, text=True, timeout=10)
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
        proc = subprocess.run(["git", "-C", base, "remote", "-v"],
                              capture_output=True, text=True, timeout=10)
    except Exception:
        return ""
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[2] == "(fetch)":
            return parts[1]
    return ""


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


def match_by_remote(conn: sqlite3.Connection, remote: str) -> Optional[int]:
    """按归一化 git remote 精确匹配已注册项目 (先归一化再比, 兼容历史脏值)。"""
    r = normalize_remote(remote)
    if not r:
        return None
    for p in list_projects(conn):
        if p["remote"] and normalize_remote(p["remote"]) == r:
            return p["id"]
    return None


def backfill_remote(conn: sqlite3.Connection, project_id: int, remote: str) -> bool:
    """把一个 remote 为空的既有项目补上归一化 remote; 已非空则不覆盖。返回是否写入。"""
    r = normalize_remote(remote)
    if not r:
        return False
    row = conn.execute("SELECT remote FROM projects WHERE id=?",
                       (project_id,)).fetchone()
    if row is None or (row["remote"] or "").strip():
        return False
    conn.execute("UPDATE projects SET remote=?, updated_at=datetime('now') WHERE id=?",
                 (r, project_id))
    conn.commit()
    return True


def _unique_project_name(conn: sqlite3.Connection, base: str) -> str:
    """自动注册时保证项目名唯一: 与已有项目名冲突则追加 -2/-3... 后缀。"""
    name = (base or "project").strip()
    n = 2
    while conn.execute("SELECT 1 FROM projects WHERE name=?",
                       (name,)).fetchone() is not None:
        name = f"{base}-{n}"
        n += 1
    return name


def resolve_project(conn: sqlite3.Connection, cwd: Optional[str] = None,
                    remote: Optional[str] = None) -> tuple:
    """确定性项目归属 (代码强制): 返回 (status, project_id)。

    匹配顺序: 归一化 git remote 精确 → 仓库根路径 → 自动注册。
    status:
      - "matched": remote 或路径匹配到已注册项目, 记忆归该项目 (路径命中时顺手回填 remote/path)
      - "created": git 检测到仓库但未注册 → 自动注册 (name=仓库 basename,
                   path=仓库根, remote=归一化值), 记忆归新项目
      - "no_git":  既无 remote 命中、又不在任何 git 仓库内 → 需向用户确认
                   (新建项目 或 全局层), 调用方不得静默落全局
    """
    r = normalize_remote(remote) if remote else normalize_remote(git_remote(cwd))
    if r:
        pid = match_by_remote(conn, r)
        if pid is not None:
            return ("matched", pid)
    repo = _git_toplevel(cwd)
    if repo is None:
        return ("no_git", None)
    pid = _match_registered(conn, repo)
    if pid is not None:
        # 路径命中: path 降级为「最近一次看到的位置」(后写覆盖), remote 惰性回填
        backfill_remote(conn, pid, r)
        conn.execute("UPDATE projects SET path=?, updated_at=datetime('now') WHERE id=?",
                     (str(repo), pid))
        conn.commit()
        return ("matched", pid)
    pid = add_project(conn, _unique_project_name(conn, repo.name), str(repo), "", r)
    return ("created", pid)


def duplicate_groups(conn: sqlite3.Connection) -> List[dict]:
    """只读: 按归一化 remote 分组, 列出同一 remote 下的多个项目 (身份重复的信号)。"""
    buckets: dict = {}
    for p in list_projects(conn):
        r = normalize_remote(p["remote"])
        if not r:
            continue
        buckets.setdefault(r, []).append(p)
    return [{"remote": r,
             "items": [{"id": p["id"], "name": p["name"], "path": p["path"],
                        "mem_count": p["mem_count"]} for p in ps]}
            for r, ps in sorted(buckets.items()) if len(ps) > 1]


def merge_projects(conn: sqlite3.Connection, src_id: int, dst_id: int,
                   backup_path: str) -> dict:
    """显式合并: 记忆与 spec 索引改挂 dst, src 打墓碑; 合并前写可回滚备份。

    单事务内完成; specs_index 的 UNIQUE(project_id, rel_path) 冲突保留 dst 既有行、
    删除 src 重复行并计入报告。不物理删除任何项目/记忆。
    """
    if src_id == dst_id:
        raise ValueError("源与目标不能相同")
    for pid in (src_id, dst_id):
        if conn.execute("SELECT 1 FROM projects WHERE id=?", (pid,)).fetchone() is None:
            raise ValueError(f"项目不存在: {pid}")
    mems = [dict(r) for r in conn.execute(
        "SELECT id, project_id FROM memories WHERE project_id=?", (src_id,)).fetchall()]
    specs = [dict(r) for r in conn.execute(
        "SELECT id, project_id, rel_path FROM specs_index WHERE project_id=?",
        (src_id,)).fetchall()]
    src = dict(conn.execute("SELECT * FROM projects WHERE id=?", (src_id,)).fetchone())
    Path(backup_path).write_text(
        json.dumps({"version": 1, "src_id": src_id, "dst_id": dst_id,
                    "memories": mems, "specs_index": specs, "src_row": src},
                   ensure_ascii=False, indent=2),
        encoding="utf-8")
    dropped = 0
    with conn:  # 单事务
        dst_paths = {r["rel_path"] for r in conn.execute(
            "SELECT rel_path FROM specs_index WHERE project_id=?", (dst_id,)).fetchall()}
        for s in specs:
            if s["rel_path"] in dst_paths:
                conn.execute("DELETE FROM specs_index WHERE id=?", (s["id"],))
                dropped += 1
        conn.execute("UPDATE specs_index SET project_id=? WHERE project_id=?",
                     (dst_id, src_id))
        conn.execute("UPDATE memories SET project_id=? WHERE project_id=?",
                     (dst_id, src_id))
        conn.execute("INSERT OR IGNORE INTO project_removals(project_id, name) VALUES (?,?)",
                     (src_id, src["name"]))
    return {"moved_memories": len(mems), "moved_specs": len(specs) - dropped,
            "dropped_specs": dropped, "backup": backup_path}


def rollback_merge(conn: sqlite3.Connection, backup_path: str) -> dict:
    """按合并产出的备份还原: 记忆/spec 索引 project_id 复原, 撤销 src 墓碑。"""
    data = json.loads(Path(backup_path).read_text(encoding="utf-8"))
    with conn:
        for m in data["memories"]:
            conn.execute("UPDATE memories SET project_id=? WHERE id=?",
                         (m["project_id"], m["id"]))
        for s in data["specs_index"]:
            conn.execute("UPDATE specs_index SET project_id=? WHERE id=?",
                         (s["project_id"], s["id"]))
        conn.execute("DELETE FROM project_removals WHERE project_id=?",
                     (data["src_id"],))
    return {"restored_memories": len(data["memories"]),
            "restored_specs": len(data["specs_index"])}


def _walk_spec_files(root: Path) -> List[Path]:
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fn in filenames:
            if not fn.lower().endswith(".md"):
                continue
            p = Path(dirpath) / fn
            rel = p.relative_to(root).as_posix()
            # 只索引看起来像 spec/洞察/规划 的文件, 不索引普通 README 正文
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
    """拼出监督环用的项目上下文: charter + 洞察 + spec 摘要/原文片段。

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
        " WHERE project_id=? AND status='active' AND level='insight'"
        " ORDER BY id DESC LIMIT 15",
        (project_id,),
    ).fetchall()
    if decisions:
        dlines = [f"- {d['content']} ({d['created_at'][:10]})" for d in decisions]
        parts.append("【已确认洞察】\n" + "\n".join(dlines))

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
