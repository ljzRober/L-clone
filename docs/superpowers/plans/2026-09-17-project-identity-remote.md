# Project Identity (git remote) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把项目归属的身份键从本地路径换成归一化 git remote，并修好远端大脑下读侧不注入项目记忆的缺陷。

**Architecture:** 客户端（插件 / CLI / MCP 调用方）在会话机器上解析仓库 remote 与仓库根，随请求上报 `repo_remote` / `project_id`；服务端按「remote 精确 → path 兜底 → 自动注册」解析归属。新增只读重复探测与显式合并（事务 + 备份 + 回滚），新增列走 `db.init` 的幂等 `ALTER TABLE ADD COLUMN`。

**Tech Stack:** Python 3 / SQLite / FastAPI / Node（DSH 插件）/ openspec（spec 存储）

**Spec:** `openspec/changes/project-identity-remote/proposal.md` + `openspec/changes/project-identity-remote/specs/`（delta 已 `openspec validate` 通过）

## Global Constraints

- 身份键是归一化 remote（`host/group/repo`）：去协议/凭据/`.git`/尾 `/`，host 小写，**path 保留大小写**；fork 的 remote 不同 → 视为不同项目。
- `projects.path` 保留单列，语义降级为「最近一次看到的位置」，**后写覆盖**；SHALL NOT 作为身份键。
- 匹配顺序固定：remote 精确 → path（resolved 相等或上报路径最长前缀）→ 自动注册（name=仓库 basename、撞名沿用 `-2` 后缀）。
- 合并 SHALL 在一个事务内完成，且 SHALL 先产出可回滚备份；源项目复用 `project_removals` 墓碑，SHALL NOT 物理删除。
- 服务端 SHALL NOT 依赖对客户端路径执行 git 检测；客户端解析失败才允许回落 `cwd`。
- `记忆分类与确认` / `准入` / `跨层去重` / `删除项目` / `进化资产版本库` / 鉴权 的既有语义一律不动。
- 所有新函数默认参数保持向后兼容；既有测试断言（尤其 `check("12 召回限定项目")`）必须继续通过。

---

### Task 1: remote 归一化与客户端 remote 读取

**Files:**
- Modify: `lclone/projects.py`（新增 `normalize_remote` / `git_remote`，放在 `_git_toplevel` 附近）
- Test: `tests/test_offline.py`（文件末尾追加新段，沿用既有 `check()` 风格）

**Interfaces:**
- Produces: `normalize_remote(url: str) -> str`、`git_remote(cwd: Optional[str] = None) -> str`

- [ ] **Step 1: 写失败测试**

```python
# ---- 346+: 项目身份改 git remote ----
from lclone.projects import normalize_remote, git_remote
check("346 remote 归一化 ssh scp 形式",
      normalize_remote("git@git.xiaojukeji.com:PH-596/expressdriver-drn.git")
      == "git.xiaojukeji.com/PH-596/expressdriver-drn",
      normalize_remote("git@git.xiaojukeji.com:PH-596/expressdriver-drn.git"))
check("347 remote 归一化 https 去凭据",
      normalize_remote("https://user:tok@GitHub.com/ljzRober/L-clone.git")
      == "github.com/ljzRober/L-clone",
      normalize_remote("https://user:tok@GitHub.com/ljzRober/L-clone.git"))
check("348 remote 归一化 ssh:// 带端口",
      normalize_remote("ssh://git@host:2222/a/b.git") == "host:2222/a/b",
      normalize_remote("ssh://git@host:2222/a/b.git"))
check("349 remote 空/无 remote 返回空串",
      normalize_remote("") == "" and normalize_remote("   ") == "")
check("350 同仓库两种写法归一后相等",
      normalize_remote("git@git.xiaojukeji.com:PH-596/x.git")
      == normalize_remote("https://git.xiaojukeji.com/PH-596/x"))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `BRAIN_LLM=dummy .venv/bin/python tests/test_offline.py 2>&1 | tail -20`
Expected: `ImportError: cannot import name 'normalize_remote'`

- [ ] **Step 3: 实现**

```python
_REMOTE_SCHEMES = ("ssh://", "git://", "https://", "http://")

def normalize_remote(url: str) -> str:
    """把 git remote 地址归一化为 `host/group/repo` 作为项目身份键。

    规则: 去协议前缀与凭据; **无协议**的 scp 形式 [user@]host:path 拆开 (带协议的
    host:port/path 不拆, 端口保留为 host:port); 去尾 '/' 与 '.git'; host 小写;
    path 保留大小写。无 remote 返回空串 (调用方回落 path)。
    """
    s = (url or "").strip()
    if not s:
        return ""
    had_scheme = "://" in s
    if had_scheme:
        s = s.split("://", 1)[1]
    if "@" in s.split("/", 1)[0]:          # 去凭据 (user@ 或 user:token@)
        s = s.split("@", 1)[1]
    if not had_scheme and ":" in s.split("/", 1)[0]:   # scp 形式 host:path
        host, _, path = s.partition(":")
        s = host + "/" + path.lstrip("/")
    s = s.rstrip("/")
    if s.lower().endswith(".git"):
        s = s[:-4]
    head, _, rest = s.partition("/")
    if ":" in head:                         # host:port 归一化: host 小写, 端口保留
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
```

> 实现注记：**scp 形式只在原串没有协议前缀时才拆**（`ssh://git@host:2222/a/b.git` 的 `2222` 是端口，不是路径），
> 否则会被误归一化成 `host/2222/a/b`。JS 侧（插件）的 `normalizeRemote` 用同一规则，已有行为对齐用例。

- [ ] **Step 4: 跑测试确认通过**

Run: `BRAIN_LLM=dummy .venv/bin/python tests/test_offline.py 2>&1 | tail -8`
Expected: 新增 346-350 全 PASS，既有用例数量与通过数不变

- [ ] **Step 5: Commit**

```bash
git add lclone/projects.py tests/test_offline.py
git commit -m "feat(projects): add remote normalization and client remote lookup"
```

---

### Task 2: `projects.remote` 幂等迁移

**Files:**
- Modify: `lclone/db.py:201-217`（现有 `PRAGMA table_info` + `ALTER TABLE` 块）
- Test: `tests/test_offline.py`

**Interfaces:**
- Produces: `projects.remote TEXT NOT NULL DEFAULT ''`（新库与旧库都有）

- [ ] **Step 1: 写失败测试**

```python
_pcols = [r["name"] for r in conn.execute("PRAGMA table_info(projects)")]
check("351 projects 有 remote 列", "remote" in _pcols, str(_pcols))
_re_conn = db_mod.init(dbp)          # 二次 init 必须幂等
check("352 db.init 幂等 (重复加列不报错)",
      "remote" in [r["name"] for r in _re_conn.execute("PRAGMA table_info(projects)")])
_re_conn.close()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `BRAIN_LLM=dummy .venv/bin/python tests/test_offline.py 2>&1 | tail -10`
Expected: `351 projects 有 remote 列 ... False`

- [ ] **Step 3: 实现**

在 `CREATE TABLE IF NOT EXISTS projects` 的 `path` 之后加 `remote TEXT NOT NULL DEFAULT ''`，并在迁移块末尾追加：

```python
    pcols = [r["name"] for r in conn.execute("PRAGMA table_info(projects)")]
    if "remote" not in pcols:
        conn.execute("ALTER TABLE projects ADD COLUMN remote TEXT NOT NULL DEFAULT ''")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `BRAIN_LLM=dummy .venv/bin/python tests/test_offline.py 2>&1 | tail -8`
Expected: 351/352 PASS

- [ ] **Step 5: Commit**

```bash
git add lclone/db.py tests/test_offline.py
git commit -m "feat(db): add projects.remote column with idempotent migration"
```

---

### Task 3: remote 优先匹配 + 惰性回填

**Files:**
- Modify: `lclone/projects.py`（`add_project` / `_match_registered` / 新增 `match_by_remote` / `backfill_remote` / 重写 `resolve_project`）
- Test: `tests/test_offline.py`

**Interfaces:**
- Consumes: `normalize_remote`, `git_remote`（Task 1）
- Produces: `add_project(conn, name, path="", charter="", remote="") -> int`、`match_by_remote(conn, remote) -> Optional[int]`、`backfill_remote(conn, pid, remote) -> bool`、`resolve_project(conn, cwd=None, remote=None) -> (status, pid)`

- [ ] **Step 1: 写失败测试**

```python
_rp = db_mod.init(os.path.join(tmp, "remoteid.db"))
_pa = proj_mod.add_project(_rp, "repoA", "/old/path/repoA", "", "git@host:grp/repoA.git")
check("353 add_project 落归一化 remote",
      _rp.execute("SELECT remote FROM projects WHERE id=?", (_pa,)).fetchone()["remote"]
      == "host/grp/repoA",
      _rp.execute("SELECT remote FROM projects WHERE id=?", (_pa,)).fetchone()["remote"])
_st, _pid = proj_mod.resolve_project(_rp, cwd=None, remote="ssh://git@host/grp/repoA")
check("354 remote 优先命中 (路径不同也归同一项目)",
      _st == "matched" and _pid == _pa, f"{_st}/{_pid}")
_plain_rd = os.path.join(tmp, "plain_remote_dir")
os.makedirs(_plain_rd, exist_ok=True)
_st2, _pb = proj_mod.resolve_project(_rp, cwd=_plain_rd, remote="git@host:grp/repoB.git")
check("355 未知 remote 且不在 git 仓库 → no_git 信号",
      _st2 == "no_git" and _pb is None, f"{_st2}/{_pb}")
# 注意: examples/demo_project 本身不是 git 仓库 (toplevel 会落到 L-clone 根),
# 路径兜底必须用一个真的独立仓库来测。
_pc_repo = os.path.join(tmp, "repoC")
os.makedirs(_pc_repo, exist_ok=True)
subprocess.run(["git", "init", "-q", _pc_repo], check=True)
subprocess.run(["git", "-C", _pc_repo, "remote", "add", "origin",
                "git@host:grp/repoC.git"], check=True)
_pc = proj_mod.add_project(_rp, "repoC", _pc_repo, "", "")
_st3, _pid3 = proj_mod.resolve_project(_rp, cwd=_pc_repo)
check("356 空 remote 命中 path 后惰性回填",
      _st3 == "matched" and _pid3 == _pc
      and _rp.execute("SELECT remote FROM projects WHERE id=?", (_pc,)).fetchone()["remote"]
      == "host/grp/repoC", f"{_st3}/{_pid3}")
_rp.close()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `BRAIN_LLM=dummy .venv/bin/python tests/test_offline.py 2>&1 | tail -10`
Expected: TypeError（`add_project` 不接受 `remote`）或断言失败

- [ ] **Step 3: 实现**

```python
def add_project(conn, name, path="", charter="", remote=""):
    cur = conn.execute(
        "INSERT INTO projects(name, path, charter, remote) VALUES (?,?,?,?)",
        (name.strip(), path.strip(), charter.strip(), normalize_remote(remote) if remote else ""),
    )
    conn.commit()
    return cur.lastrowid


def match_by_remote(conn, remote):
    """归一化 remote 精确匹配 (先归一化再比, 兼容历史未归一化的脏值)。"""
    r = normalize_remote(remote)
    if not r:
        return None
    for p in list_projects(conn):
        if p["remote"] and normalize_remote(p["remote"]) == r:
            return p["id"]
    return None


def backfill_remote(conn, project_id, remote):
    """把归一化 remote 写进一个 remote 为空的既有项目, 返回是否写入。"""
    r = normalize_remote(remote)
    if not r:
        return False
    row = conn.execute("SELECT remote FROM projects WHERE id=?", (project_id,)).fetchone()
    if row is None or (row["remote"] or "").strip():
        return False
    conn.execute("UPDATE projects SET remote=?, updated_at=datetime('now') WHERE id=?",
                 (r, project_id))
    conn.commit()
    return True


def resolve_project(conn, cwd=None, remote=None):
    """确定性项目归属: remote 精确 → path 兜底(命中即回填 remote) → 自动注册 → no_git。"""
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
        backfill_remote(conn, pid, r)
        conn.execute("UPDATE projects SET path=?, updated_at=datetime('now') WHERE id=?",
                     (str(repo), pid))
        conn.commit()
        return ("matched", pid)
    pid = add_project(conn, _unique_project_name(conn, repo.name), str(repo), "", r)
    return ("created", pid)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `BRAIN_LLM=dummy .venv/bin/python tests/test_offline.py 2>&1 | tail -8`
Expected: 353-356 PASS，既有用例全绿

- [ ] **Step 5: Commit**

```bash
git add lclone/projects.py tests/test_offline.py
git commit -m "feat(projects): resolve attribution by git remote with path fallback and lazy backfill"
```

---

### Task 4: 重复探测 + 显式合并 + 回滚

**Files:**
- Modify: `lclone/projects.py`（新增 `duplicate_groups` / `merge_projects` / `rollback_merge`）
- Test: `tests/test_offline.py`

**Interfaces:**
- Produces: `duplicate_groups(conn) -> List[dict]`、`merge_projects(conn, src_id, dst_id, backup_path) -> dict`、`rollback_merge(conn, backup_path) -> dict`

- [ ] **Step 1: 写失败测试**

```python
_mg = db_mod.init(os.path.join(tmp, "merge.db"))
_d1 = proj_mod.add_project(_mg, "drn", "/a/drn", "", "git@host:g/drn.git")
_d2 = proj_mod.add_project(_mg, "drn-2", "/b/drn", "", "git@host:g/drn.git")
mem_mod.remember(_mg, "要点：合并前卡。\n背景/为什么：验证。\n影响/以后注意：迁移。",
                 level="insight", project_id=_d2, confirmed=True)
_groups = proj_mod.duplicate_groups(_mg)
check("357 重复项目可探测",
      any(sorted(i["id"] for i in g["items"]) == sorted([_d1, _d2]) for g in _groups),
      str(_groups))
check("358 探测只读 (不改 remote)", 
      _mg.execute("SELECT COUNT(*) c FROM projects WHERE remote=''").fetchone()["c"] == 0)
_bk = os.path.join(tmp, "merge-backup.json")
_rep = proj_mod.merge_projects(_mg, _d2, _d1, _bk)
check("359 合并改挂记忆并打墓碑",
      _mg.execute("SELECT project_id FROM memories WHERE content LIKE '要点：合并前卡%'")
      .fetchone()["project_id"] == _d1
      and proj_mod.is_removed(_mg, _d2) and _rep["moved_memories"] == 1, str(_rep))
check("360 合并产出备份", os.path.exists(_bk))
_rb = proj_mod.rollback_merge(_mg, _bk)
check("361 回滚还原归属并撤墓碑",
      _mg.execute("SELECT project_id FROM memories WHERE content LIKE '要点：合并前卡%'")
      .fetchone()["project_id"] == _d2
      and not proj_mod.is_removed(_mg, _d2), str(_rb))
_mg.close()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `BRAIN_LLM=dummy .venv/bin/python tests/test_offline.py 2>&1 | tail -10`
Expected: `AttributeError: module 'lclone.projects' has no attribute 'duplicate_groups'`

- [ ] **Step 3: 实现**

```python
def duplicate_groups(conn) -> List[dict]:
    """只读: 按归一化 remote 分组, 列出同一 remote 下的多个项目。"""
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


def merge_projects(conn, src_id: int, dst_id: int, backup_path: str) -> dict:
    """显式合并: 记忆与 spec 索引改挂 dst, src 打墓碑; 合并前写可回滚备份。"""
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
    payload = {"version": 1, "src_id": src_id, "dst_id": dst_id,
               "memories": mems, "specs_index": specs, "src_row": src}
    Path(backup_path).write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    dropped = 0
    with conn:                                  # 单事务
        dst_paths = {r["rel_path"] for r in conn.execute(
            "SELECT rel_path FROM specs_index WHERE project_id=?", (dst_id,)).fetchall()}
        for s in specs:
            if s["rel_path"] in dst_paths:
                conn.execute("DELETE FROM specs_index WHERE id=?", (s["id"],))
                dropped += 1
        conn.execute("UPDATE specs_index SET project_id=? WHERE project_id=?", (dst_id, src_id))
        conn.execute("UPDATE memories SET project_id=? WHERE project_id=?", (dst_id, src_id))
        conn.execute("INSERT OR IGNORE INTO project_removals(project_id, name) VALUES (?,?)",
                     (src_id, src["name"]))
    return {"moved_memories": len(mems), "moved_specs": len(specs) - dropped,
            "dropped_specs": dropped, "backup": backup_path}


def rollback_merge(conn, backup_path: str) -> dict:
    """按备份还原合并: 记忆/spec 索引 project_id 复原, 撤销 src 墓碑。"""
    data = json.loads(Path(backup_path).read_text(encoding="utf-8"))
    with conn:
        for m in data["memories"]:
            conn.execute("UPDATE memories SET project_id=? WHERE id=?", (m["project_id"], m["id"]))
        for s in data["specs_index"]:
            conn.execute("UPDATE specs_index SET project_id=? WHERE id=?", (s["project_id"], s["id"]))
        conn.execute("DELETE FROM project_removals WHERE project_id=?", (data["src_id"],))
    return {"restored_memories": len(data["memories"]), "restored_specs": len(data["specs_index"])}
```

`projects.py` 顶部需补 `import json`。

- [ ] **Step 4: 跑测试确认通过**

Run: `BRAIN_LLM=dummy .venv/bin/python tests/test_offline.py 2>&1 | tail -8`
Expected: 357-361 PASS

- [ ] **Step 5: Commit**

```bash
git add lclone/projects.py tests/test_offline.py
git commit -m "feat(projects): duplicate detection, explicit merge with backup and rollback"
```

---

### Task 5: 读侧 bootstrap 按客户端上报的归属加载

**Files:**
- Modify: `lclone/web.py:270-279`（`/api/bootstrap`）
- Modify: `lclone/mcp_server.py`（`bootstrap` / `capture` / `remember` / `projects` 透传 remote）
- Test: `tests/test_offline.py`

**Interfaces:**
- Consumes: `resolve_project(conn, cwd, remote)`（Task 3）
- Produces: `GET /api/bootstrap?project_id=&repo_remote=&cwd=&query=&k=`；MCP `bootstrap` 新增 `repo_remote`；MCP `projects` 输出含 `remote`

- [ ] **Step 1: 写失败测试**

```python
_bp = db_mod.init(os.path.join(tmp, "bootpid.db"))
_bpid = proj_mod.add_project(_bp, "bootproj", "", "方向X", "git@host:g/boot.git")
mem_mod.remember(_bp, "要点：项目专属卡。\n背景/为什么：验证读侧。\n影响/以后注意：注入。",
                 level="insight", project_id=_bpid, confirmed=True)
_check = mem_mod.bootstrap(_bp, project_id=proj_mod.match_by_remote(_bp, "git@host/g/boot"))
check("362 remote 可解析出项目并按项目注入",
      "项目专属卡" in _check, _check[:80])
_bp.close()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `BRAIN_LLM=dummy .venv/bin/python tests/test_offline.py 2>&1 | tail -8`
Expected: `362` FAIL（`#N` 未实现 remote 解析路径）

- [ ] **Step 3: 实现**

`web.py`：

```python
    @app.get("/api/bootstrap")
    def bootstrap(cwd: str = "", query: str = "", k: int = 5,
                  project_id: Optional[int] = None, repo_remote: str = "",
                  conn: sqlite3.Connection = Depends(get_db)):
        pid = project_id if project_id is not None else None
        if pid is None and repo_remote:
            pid = proj_mod.match_by_remote(conn, repo_remote)
        if pid is None and cwd:
            status, pid = proj_mod.resolve_project(conn, cwd=cwd)
            if status == "no_git":
                pid = None
        text = mem_mod.bootstrap(conn, query=query, project_id=pid, k=k)
        return {"text": text, "project_id": pid}
```

`mcp_server.py`：`bootstrap` 的 `_resolve_project(conn, args.get("project"))` 之后再按 `repo_remote` 兜底；`capture` / `remember` 在 `args.get("project")` 为空时用 `match_by_remote(conn, args.get("repo_remote"))`；`projects` 每条追加 `remote`。

- [ ] **Step 4: 跑测试确认通过**

Run: `BRAIN_LLM=dummy .venv/bin/python tests/test_offline.py 2>&1 | tail -8`
Expected: 362 PASS

- [ ] **Step 5: Commit**

```bash
git add lclone/web.py lclone/mcp_server.py tests/test_offline.py
git commit -m "feat(api): resolve bootstrap project from client-reported remote/project_id"
```

---

### Task 6: CLI 与插件 surface

**Files:**
- Modify: `lclone/cli.py`（`proj` 子命令新增 `dupes` / `merge` / `rollback`；capture/remember 上报 remote）
- Modify: `lclone/evolutions.py:950-974`（`find_project` 增加 `repo_remote`，HttpBackend 调用点同步）
- Modify: `integrations/dsh/dsh/index.js:190-198, 148-167`（读侧传 `project_id`；写侧附 `repo_remote`）
- Test: `tests/test_offline.py`（CLI 冒烟）

**Interfaces:**
- Consumes: Task 3/4/5 的服务端能力
- Produces: `lclone proj dupes` / `lclone proj merge <src> <dst> [--backup PATH]` / `lclone proj rollback <backup>`；`HttpBackend.find_project(ref=None, repo_path="", repo_remote="")`

- [ ] **Step 1: 写失败测试**

```python
_buf = io.StringIO()
with contextlib.redirect_stdout(_buf):
    cli.main(["proj", "--db", dbp, "dupes"])
check("363 proj dupes 可跑", "重复" in _buf.getvalue() or _buf.getvalue().strip() == "无重复项目",
      _buf.getvalue()[:60])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `BRAIN_LLM=dummy .venv/bin/python tests/test_offline.py 2>&1 | tail -8`
Expected: argparse `invalid choice: 'dupes'`

- [ ] **Step 3: 实现**

- `cli.py`：新增三个子命令；`cmd_capture` / `cmd_remember` 在远端分支把 `_git_toplevel(args.cwd)` 改为同时解析 `git_remote(args.cwd)` 并放进 HTTP body 的 `repo_remote`；`cmd_proj_dupes` 打印 `remote → [#id name (N 条), ...]`，无重复时打印 `无重复项目`。
- `evolutions.py`：`find_project(self, ref=None, repo_path="", repo_remote="")`，匹配顺序 `ref`（名/id）→ `repo_remote`（对 `p["remote"]` 归一化后比）→ `repo_path` 最长前缀（现有逻辑保留）。
- `integrations/dsh/dsh/index.js`：`runBootstrap(cwd, projectId, onDone)` 在 path 里拼 `project_id`；`injectSessionStart` 先 `resolveProject(cwd, ...)` 再调 `runBootstrap`；`captureTurn` 在 body 里加 `repo_remote: await gitRemote(cwd)`（新增 `gitRemote()`，取 `git remote get-url origin`）。

- [ ] **Step 4: 跑测试确认通过**

Run: `BRAIN_LLM=dummy .venv/bin/python tests/test_offline.py 2>&1 | tail -8`
Expected: 363 PASS；插件侧用 `node --check integrations/dsh/dsh/index.js` 过语法

- [ ] **Step 5: Commit**

```bash
git add lclone/cli.py lclone/evolutions.py integrations/dsh/dsh/index.js tests/test_offline.py
git commit -m "feat(cli,dsh): surface remote identity (proj dupes/merge/rollback, client-side bootstrap attribution)"
```

---

### Task 7: 种子资产与文档同步

**Files:**
- Modify: `lclone/data/starter/evolutions/会话归属与落库约定.md`
- Modify: `lclone/data/starter/insights.md`（「归属判定」卡措辞）
- Modify: `docs/CLI.md`、`docs/CONCEPTS.md`、`README.md` / `README.zh-CN.md`（归属 = remote 身份）
- Modify: `integrations/skill/SKILL.md`（规则 3 改 remote 优先）+ 同步 `~/.agents/skills/lclone-memory/SKILL.md`

- [ ] **Step 1: 改种子资产正文**

把「归属」一节改为：身份键 = 归一化 `origin` remote（`host/group/repo`）；本地路径只作位置提示；远端大脑下客户端上报 `remote`/`project_id`；无 remote 才回落路径。

- [ ] **Step 2: 改 skill 规则 3**

> 归属判定：优先按**归一化 git remote**（`git remote get-url origin` → `host/group/repo`）匹配已注册项目；无 remote 才按路径最长前缀。远端后端下**必须显式传 `project` 或 `repo_remote`**，先 `projects` 看 `remote` 列表再决定。

- [ ] **Step 3: 同步安装副本**

```bash
cp integrations/skill/SKILL.md ~/.agents/skills/lclone-memory/SKILL.md
diff -q integrations/skill/SKILL.md ~/.agents/skills/lclone-memory/SKILL.md
```

- [ ] **Step 4: 验证文档无残留旧口径**

Run: `grep -rn "path 匹配当前工作目录\|按 path 匹配" docs/ integrations/skill/SKILL.md lclone/data/starter/`
Expected: 无匹配（或仅剩明确说明"回落"的句子）

- [ ] **Step 5: Commit**

```bash
git add lclone/data/starter docs README.md README.zh-CN.md integrations/skill/SKILL.md
git commit -m "docs(attribution): switch project identity docs and seed content to git remote"
```

---

### Task 8: 全量回归 + 生产回填/合并（需单独确认）

- [ ] **Step 1: 全量离线回归**

Run: `BRAIN_LLM=dummy .venv/bin/python tests/test_offline.py 2>&1 | tail -5`
Expected: 全部 PASS，无 FAIL

- [ ] **Step 2: 前端 JS 回归（未改前端，回归确认）**

Run: `node tests/frontend_evo_test.js 2>&1 | tail -5`
Expected: 全部 PASS

- [ ] **Step 3: 部署服务器（**执行前必须再找用户确认**）**

容器镜像只 COPY `lclone/`（不含 scripts/），迁移靠 `db.init` 在启动时跑。

```bash
git push origin master
ssh root@60.205.3.97 'cd /root/github/L-clone && git pull && docker compose up -d --build'
curl -s -H "Authorization: Bearer $LCLONE_API_KEY" http://60.205.3.97:8000/api/projects | head -c 400
```

- [ ] **Step 4: 回填 + 重复合并（**执行前必须再找用户确认**）**

CLI 的 `proj` 命令走**本地** DB（`_conn`），生产库必须走 REST：

```bash
# 探测（只读）
curl -s -H "Authorization: Bearer $LCLONE_API_KEY" http://60.205.3.97:8000/api/projects/duplicates
# 逐组合并（备份写在服务器 /data 下，可回滚）
for pair in "10 1" "6 4" "8 2"; do set -- $pair; \
  curl -s -X POST -H "Authorization: Bearer $LCLONE_API_KEY" -H "Content-Type: application/json" \
    -d "{\"src_id\":$1,\"dst_id\":$2,\"backup\":\"/data/merge-$1-$2.json\"}" \
    http://60.205.3.97:8000/api/projects/merge; echo; done
# 复核
curl -s -H "Authorization: Bearer $LCLONE_API_KEY" http://60.205.3.97:8000/api/projects/duplicates
```

- [ ] **Step 5: 端到端验证读侧**

```bash
curl -s -H "Authorization: Bearer $LCLONE_API_KEY" \
  "http://60.205.3.97:8000/api/bootstrap?repo_remote=git@github.com:ljzRober/L-clone.git" \
  | python3 -c "import json,sys; t=json.load(sys.stdin)['text']; print('项目记忆' in t, len(t))"
```
Expected: `True <len>`（项目记忆段出现）

## Self-Review

- **Spec coverage**：归属判定（Task 1/3/5）、按环境加载记忆（Task 5/6）、项目身份与重复探测（Task 2/4）、dsh 会话开始加载 skill（Task 6）—— 全部有对应 task；合并可回滚（Task 4 Step 1 `361`）。
- **Placeholder scan**：无 TBD；每个代码步骤给出可执行代码或明确的编辑位置。
- **Type consistency**：`normalize_remote` / `git_remote` / `add_project(remote=)` / `match_by_remote` / `backfill_remote` / `resolve_project(cwd, remote)` / `duplicate_groups` / `merge_projects` / `rollback_merge` / `find_project(repo_remote=)` 在 Task 1-6 中签名一致。
