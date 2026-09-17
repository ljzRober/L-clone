"""项目模块 (竖向分层): 项目注册 + spec 格式无关索引。

设计原则:
  - 具体事务 (spec 全文/代码/PR) 永远留在项目仓库, 大脑只建索引和记忆。
  - spec 格式不绑定任何工具 (OpenSpec/ADR 只是约定之一): 通过路径模式
    启发式分类, 新增格式只需扩展 detect_format 和 PROJECT_SPEC_DIRS。
  - 索引内容: 定位信息 + 标题 + 摘要 + 哈希; 权威以 repo 为准。
"""

from __future__ import annotations

import base64
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


_REMOTE_SCHEMES = ("ssh://", "git://", "https://", "http://", "file://")
_LOCAL_REMOTE_RE = re.compile(r"^(/|~|\.[/\\]|[A-Za-z]:[/\\])")


def normalize_remote(url: str) -> str:
    """把 git remote 地址归一化为 `host/group/repo`, 作为项目身份键。

    规则:
      - 去协议与**凭据**(取首个 `/` 之前最后一个 `@`, 兼容密码里带 `@`);
      - **无协议**的 scp 形式 `[user@]host:path` 拆开; `host:8080/g/r` 视为 host:port
        (与 `https://host:8080/g/r` 收敛到同一个键);
      - 去尾 `/` 与 `.git`; host 小写, 端口保留;
      - **path 保留大小写** (自建 GitLab 可能大小写敏感, 宁可少合并也不误合并);
      - 本地路径 / `file://` 返回空串 (跨机器同路径不同仓库会误合并, 不如回落 path 身份)。
    """
    s = (url or "").strip()
    if not s:
        return ""
    if s.lower().startswith("file://") or _LOCAL_REMOTE_RE.match(s):
        return ""
    had_scheme = "://" in s
    if had_scheme:
        s = s.split("://", 1)[1]
    first_slash = s.find("/")
    head_seg = s if first_slash == -1 else s[:first_slash]
    at = head_seg.rfind("@")                 # 凭据里可能还有 @ → 取最后一个
    if at != -1:
        s = s[at + 1:]
    if not had_scheme:
        head = s if "/" not in s else s.split("/", 1)[0]
        if ":" in head:
            host, _, path = s.partition(":")
            if re.match(r"^\d+/", path):      # host:8080/group/repo → 当 host:port
                s = host + ":" + path
            else:                             # scp 形式 host:group/repo
                s = host + "/" + path.lstrip("/")
    s = s.rstrip("/")
    if s.lower().endswith(".git"):
        s = s[:-4]
    head, _, rest = s.partition("/")
    if ":" in head:
        h, _, port = head.partition(":")
        head = h.lower() + ":" + port
    else:
        head = head.lower()
    return f"{head}/{rest}" if rest else head


def git_remote(cwd: Optional[str] = None) -> str:
    """取仓库 origin 的 remote 地址; 无 origin 取第一条 remote; 无仓库/无 remote 返回空串。"""
    import subprocess
    if not cwd:
        return ""
    base = cwd
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


def match_by_path_str(conn: sqlite3.Connection, path: str) -> Optional[int]:
    """按**上报路径字符串**做最长前缀匹配 (不跑 git)。

    远端大脑下服务端跑不了客户端路径的 git, 这是唯一可用的路径兜底;
    父子目录也算命中 (兼容历史上把子目录/父目录注册成项目的脏数据)。
    """
    p = (path or "").strip().rstrip("/")
    if not p:
        return None
    best: Optional[tuple] = None
    for row in list_projects(conn):
        q = (row["path"] or "").strip().rstrip("/")
        if not q:
            continue
        if p == q or p.startswith(q + "/"):
            if best is None or len(q) > best[1]:
                best = (row["id"], len(q))
    return best[0] if best else None


def set_remote(conn: sqlite3.Connection, project_id: int, remote: str,
               force: bool = False) -> bool:
    """把客户端解析出的 remote 回填到项目; 默认不覆盖已有值 (force=True 才覆盖)。"""
    r = normalize_remote(remote)
    if not r:
        raise ValueError("remote 为空或不可归一化 (本地路径/file:// 不进身份键)")
    row = conn.execute("SELECT remote FROM projects WHERE id=?", (project_id,)).fetchone()
    if row is None:
        raise ValueError(f"项目不存在: {project_id}")
    cur = (row["remote"] or "").strip()
    if cur == r or (cur and not force):
        return False
    conn.execute("UPDATE projects SET remote=?, updated_at=datetime('now') WHERE id=?",
                 (r, project_id))
    conn.commit()
    return True


def _refresh_path(conn: sqlite3.Connection, project_id: int,
                  cwd: Optional[str]) -> None:
    """remote 命中时顺手把 path 刷成「最近一次看到的位置」(拿不到仓库根就跳过)。"""
    if not cwd:
        return
    repo = _git_toplevel(cwd)
    if repo is None:
        return
    conn.execute("UPDATE projects SET path=?, updated_at=datetime('now')"
                 " WHERE id=? AND path<>?", (str(repo), project_id, str(repo)))
    conn.commit()


def resolve_project(conn: sqlite3.Connection, cwd: Optional[str] = None,
                    remote: Optional[str] = None) -> tuple:
    """确定性项目归属 (代码强制): 返回 (status, project_id)。

    匹配顺序: 归一化 git remote 精确 → 仓库根路径(或上报路径字符串最长前缀) → 自动注册。
    status:
      - "matched": 命中已注册项目 (顺带回填 remote / 刷新 path)
      - "created": git 检测到仓库但未注册 → 自动注册 (name=仓库 basename,
                   path=仓库根, remote=归一化值), 记忆归新项目
      - "no_git":  既未命中、又拿不到仓库 → 需向用户确认 (新建项目 或 全局层),
                   调用方不得静默落全局

    **绝不用服务端进程目录顶替客户端路径**: 一旦显式给了 cwd 或 remote (远端大脑的场景),
    就只按它们判定; 只有两者都没给时, 才回落到进程目录 (本地后端兼容)。
    """
    cwd = (cwd or "").strip() or None          # 空白等于没给, 绝不用它触发进程目录兜底
    remote = (remote or "").strip() or None
    reported = bool(remote)
    r = normalize_remote(remote) if reported else (
        normalize_remote(git_remote(cwd)) if cwd else "")
    if r:
        pid = match_by_remote(conn, r)
        if pid is not None:
            _refresh_path(conn, pid, cwd)
            return ("matched", pid)
    repo = _git_toplevel(cwd) if cwd else None
    if repo is None:
        if cwd and not reported:
            # 字符串兜底只在客户端**没给 remote** 时启用; 明说了另一个 remote 还去按路径猜,
            # 会把嵌套的别的仓库算进来
            pid = match_by_path_str(conn, cwd)
            if pid is not None:
                backfill_remote(conn, pid, r or remote)
                # 注意: 这里**不**写 path —— 上报路径没经过校验 (可能是父目录或含 ../),
                # path 只由 _refresh_path 用真实 git 仓库根刷新
                return ("matched", pid)
        if reported or cwd:
            return ("no_git", None)
        repo = _git_toplevel(None)                  # 本地后端: 未显式给参数时按进程目录
        if repo is None:
            return ("no_git", None)
    pid = _match_registered(conn, repo)
    if pid is not None:
        backfill_remote(conn, pid, r or remote)
        conn.execute("UPDATE projects SET path=?, updated_at=datetime('now') WHERE id=?",
                     (str(repo), pid))
        conn.commit()
        return ("matched", pid)
    pid = add_project(conn, _unique_project_name(conn, repo.name), str(repo), "", r)
    return ("created", pid)


def resolve_capture_project(conn: sqlite3.Connection, project_id: Optional[int] = None,
                            cwd: Optional[str] = None,
                            remote: Optional[str] = None) -> tuple:
    """**写入路径**的归属解析 (web/MCP 共用, 可单测): 返回 (status, pid)。

    status:
      - "explicit": 显式 project_id 有效 → 用它 (顺带回填 remote)
      - "invalid":  project_id 不存在或已被移除 (调用方应报错, 不得静默写入)
      - "remote":   归一化 remote 命中已注册项目 (顺带回填)
      - "path":     上报路径字符串命中 (仅在**没给 remote** 时启用 —— 客户端明说了另一个
                    remote 就不能再拿路径去猜, 否则会把别的仓库算进来)
      - "matched"/"created": 交给 resolve_project (本地 git 判定 / 自动注册)
      - "unattributed": 三样都没有或都没命中 → 未归属 (调用方决定 global_fallback 或报错)
    """
    cwd = (cwd or "").strip() or None
    remote = (remote or "").strip() or None
    if project_id is not None:
        if get_project(conn, project_id) is None or is_removed(conn, project_id):
            return ("invalid", None)
        if remote:
            backfill_remote(conn, project_id, remote)
        return ("explicit", project_id)
    if remote:
        pid = match_by_remote(conn, remote)
        if pid is not None:
            backfill_remote(conn, pid, remote)
            return ("remote", pid)
    if cwd:
        pid = match_by_path_str(conn, cwd)
        if pid is not None:
            if not remote:
                return ("path", pid)
            # remote 对不上: 只有命中项目的 remote 还空着 (历史数据, 尚未回填) 才认路径;
            # 它已经有别的 remote → 说明是另一个仓库, 不猜
            row = get_project(conn, pid)
            if not ((row["remote"] if row else "") or "").strip():
                backfill_remote(conn, pid, remote)
                return ("path", pid)
            return ("unattributed", None)
    if cwd or remote:
        status, pid = resolve_project(conn, cwd=cwd, remote=remote)
        if status == "no_git":
            return ("unattributed", None)
        return (status, pid)
    return ("unattributed", None)


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


_MERGE_SKIP_TABLES = {"projects", "project_removals", "review_log", "sqlite_sequence"}


def _project_tables(conn: sqlite3.Connection) -> List[str]:
    """所有带 project_id 列的业务表 (合并时一起改挂)。"""
    out = []
    for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        t = row["name"]
        if t in _MERGE_SKIP_TABLES or t.startswith("sqlite_") or "_fts" in t:
            continue
        cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({t})")]
        if "project_id" in cols:
            out.append(t)
    return out


def _pk_col(conn: sqlite3.Connection, table: str) -> str:
    for r in conn.execute(f"PRAGMA table_info({table})"):
        if r["pk"]:
            return r["name"]
    return "rowid"


def merge_backup_path(db_path: str, src_id: int, dst_id: int, name: str = "") -> Path:
    """合并备份固定落在 DB 同级的 `merges/` 下, 只接受 basename (防任意路径写入)。"""
    import datetime
    base = Path(name).name if name else (
        f"merge-{src_id}-{dst_id}-{datetime.datetime.now():%Y%m%d-%H%M%S}.json")
    if not base.endswith(".json"):
        base += ".json"
    d = Path(db_path).resolve().parent / "merges"
    d.mkdir(parents=True, exist_ok=True)
    return d / base


def _jsonable_row(row: dict) -> dict:
    """把 BLOB 列 (memories.embedding) 编码成可 JSON 存的形式。"""
    return {k: ({"__b64__": base64.b64encode(bytes(v)).decode()}
                if isinstance(v, (bytes, bytearray)) else v)
            for k, v in row.items()}


def _decode_row(row: dict) -> dict:
    return {k: (base64.b64decode(v["__b64__"])
                if isinstance(v, dict) and "__b64__" in v else v)
            for k, v in row.items()}


def resolve_backup_path(db_path: str, name: str) -> Path:
    """把备份路径解析到 DB 同级 `merges/` 内 (读取侧同样受限), 只收 basename 或该目录下的绝对路径。"""
    merges = (Path(db_path).resolve().parent / "merges").resolve()
    p = Path(name or "")
    if not str(p):
        raise ValueError("缺少备份文件路径")
    cand = (p if p.is_absolute() else merges / p.name).resolve()
    if merges not in cand.parents:
        raise ValueError("备份路径必须在 merges/ 目录内")
    if not cand.is_file():
        raise ValueError(f"备份文件不存在: {cand.name}")
    return cand


def merge_projects(conn: sqlite3.Connection, src_id: int, dst_id: int,
                   backup_path) -> dict:
    """显式合并: 把 src 名下所有 project_id 数据改挂 dst, src 打墓碑; 先写可回滚备份。

    备份记录**每张表的完整行** + src 原墓碑状态 + `specs_index` 冲突标记;
    `specs_index` 的 UNIQUE(project_id, rel_path) 冲突保留 dst 既有行、删除 src 重复行
    (回滚时按主键 INSERT 重建, 不会丢)。不物理删除任何项目。
    """
    if src_id == dst_id:
        raise ValueError("源与目标不能相同")
    for pid in (src_id, dst_id):
        if conn.execute("SELECT 1 FROM projects WHERE id=?", (pid,)).fetchone() is None:
            raise ValueError(f"项目不存在: {pid}")
    src = dict(conn.execute("SELECT * FROM projects WHERE id=?", (src_id,)).fetchone())
    tables = _project_tables(conn)
    dst_paths: set = set()
    if "specs_index" in tables:
        dst_paths = {r["rel_path"] for r in conn.execute(
            "SELECT rel_path FROM specs_index WHERE project_id=?", (dst_id,)).fetchall()}
    dropped_specs = 0
    backup = {"version": 2, "src_id": src_id, "dst_id": dst_id, "src_row": src,
              "src_removed": is_removed(conn, src_id), "tables": {}}
    for t in tables:
        rows = [_jsonable_row(dict(r)) for r in conn.execute(
            f"SELECT * FROM {t} WHERE project_id=?", (src_id,)).fetchall()]
        for row in rows:
            if t == "specs_index" and row.get("rel_path") in dst_paths:
                row["_conflict"] = 1
                dropped_specs += 1
        backup["tables"][t] = rows
    Path(backup_path).write_text(json.dumps(backup, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    with conn:  # 单事务
        for t, rows in backup["tables"].items():
            pk = _pk_col(conn, t)
            for row in rows:
                if row.get("_conflict"):
                    conn.execute(f"DELETE FROM {t} WHERE {pk}=?", (row[pk],))
            conn.execute(f"UPDATE {t} SET project_id=? WHERE project_id=?", (dst_id, src_id))
        conn.execute("INSERT OR IGNORE INTO project_removals(project_id, name) VALUES (?,?)",
                     (src_id, src["name"]))
    return {"moved_rows": sum(len(v) for v in backup["tables"].values()),
            "moved_memories": len(backup["tables"].get("memories", [])),
            "moved_specs": len(backup["tables"].get("specs_index", [])) - dropped_specs,
            "dropped_specs": dropped_specs, "tables": list(backup["tables"]),
            "backup": str(backup_path)}


def rollback_merge(conn: sqlite3.Connection, backup_path) -> dict:
    """按备份还原合并: 逐表按主键改回 project_id; 行已被合并删除 (冲突) 则 INSERT 重建;
    src 的墓碑状态恢复到**合并前**的样子 (原本已墓碑的不得被复活)。"""
    data = json.loads(Path(backup_path).read_text(encoding="utf-8"))
    tables = data.get("tables")
    if tables is None:   # 兼容 v1 备份
        tables = {"memories": data.get("memories", []),
                  "specs_index": data.get("specs_index", [])}
    restored: dict = {}
    rebuilt = 0
    with conn:
        for t, rows in tables.items():
            pk = _pk_col(conn, t)
            n = 0
            for row in rows:
                vals = _decode_row({k: v for k, v in row.items() if k != "_conflict"})
                cur = conn.execute(f"UPDATE {t} SET project_id=? WHERE {pk}=?",
                                   (vals.get("project_id"), vals.get(pk)))
                n += cur.rowcount
                if cur.rowcount == 0:
                    cols = list(vals)
                    try:
                        conn.execute(
                            f"INSERT OR IGNORE INTO {t}({','.join(cols)})"
                            f" VALUES ({','.join('?' * len(cols))})",
                            tuple(vals[c] for c in cols))
                        n += 1
                        rebuilt += 1
                    except sqlite3.Error:
                        pass      # v1 备份只有部分列, 无法重建 (不静默改写其它行)
            restored[t] = n
        if data.get("src_removed"):
            conn.execute("INSERT OR IGNORE INTO project_removals(project_id, name) VALUES (?,?)",
                         (data["src_id"], (data.get("src_row") or {}).get("name", "")))
        else:
            conn.execute("DELETE FROM project_removals WHERE project_id=?", (data["src_id"],))
    return {"restored": restored, "rebuilt_rows": rebuilt,
            "restored_memories": restored.get("memories", 0),
            "restored_specs": restored.get("specs_index", 0)}


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
