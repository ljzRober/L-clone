"""进化资产(evolution): 服务器唯一权威的**版本化内容寻址存储** + 本地**只读缓存**。

权威与介质
  - 权威在**服务器**: 内容以 sha256 命名存放 (`<DB 目录>/evolution/blobs/<前2位>/<hash>`),
    不可变、天然去重; 版本索引在 SQL (`evo_versions` 只追加 + `evo_current` 当前指针)。
  - 本地 `~/.lclone/evolution/` 是**只读缓存**: 带 manifest、可随手删、pull 时按哈希校验、
    手改过的文件不会被静默覆盖; 改动走显式 `publish` 产生新版本。
  - 因此**不存在双向同步/合并冲突**: 本地永远不是权威。这是 npx/cacache 模型, 不是 git 模型
    (git 模型下本地是可写工作副本, 两边都可改 → 需要 push/pull/merge)。

不变式
  - `evo_versions` 只追加, 永不改写; **回滚 = 改 `evo_current` 指向, blob 一动不动**。
  - 内容身份 = sha256(内容); 校验/去重/脏检测全部退化为一次哈希比较。
  - 删掉整个本地缓存目录再 `pull --all` 即可完全还原。

后端适配
  `LocalBackend`(直连 SQLite) 与 `HttpBackend`(REST, 远端大脑) 实现同一组方法,
  因此 pull/status/publish 的逻辑与"大脑在哪"无关。
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import config

MANIFEST_NAME = ".lclone-manifest.json"
MANIFEST_VERSION = 1
DEFAULT_KIND = "other"
# kind → 扩展名兜底 (name 自带扩展名时以 name 为准)
KIND_EXT = {"script": "sh", "tool": "py", "command": "sh", "model": "md", "other": "txt"}


def _now() -> str:
    """UTC 时间戳 —— 与 SQLite `datetime('now')` 及既有表 (memories/sessions) 口径一致。"""
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------- 路径解析
def cache_dir(create: bool = True) -> Path:
    """本地物化缓存目录 (只读缓存的落点)。LCLONE_EVO_DIR 可覆盖 (测试/自定义用)。"""
    d = Path(os.environ.get("LCLONE_EVO_DIR") or (Path.home() / ".lclone" / "evolution"))
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def blob_dir(create: bool = False) -> Path:
    """内容存储目录 (权威)。

    默认跟着数据库走 (`<BRAIN_DB_PATH 所在目录>/evolution/blobs`) —— 这样"大脑在哪,
    内容就在哪", 天生与 DB 落在同一个持久化卷与同一份备份里, 且服务器侧持久化结果
    收敛为**一处** `data/evolution/` (与客户端缓存 `~/.lclone/evolution/` 同名)。
    LCLONE_EVO_BLOB_DIR 可覆盖。
    """
    raw = (os.environ.get("LCLONE_EVO_BLOB_DIR") or "").strip()
    d = Path(raw) if raw else Path(config.db_path()).parent / "evolution" / "blobs"
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def _blob_path(h: str) -> Path:
    return blob_dir() / h[:2] / h


def ensure_ext(name: str, kind: str = "") -> str:
    """按 kind 兜底扩展名 (name 已带扩展名则原样返回)。"""
    base = (name or "").rsplit("/", 1)[-1]
    if "." in base and not base.startswith("."):
        return base
    return base + "." + KIND_EXT.get(kind or DEFAULT_KIND, "txt")


def kind_of_name(name: str) -> str:
    """按扩展名推断 kind (script/tool/model/other)。

    迁移摄入与种子种入共用同一份规则 —— 否则迁移进来的 md 规范会和脚本一样被标成
    `other`, 元数据上分不出「可执行产物」与「模型/规范文档」。
    """
    ext = Path(str(name)).suffix.lower().lstrip(".")
    return {"sh": "script", "py": "tool", "md": "model"}.get(ext, DEFAULT_KIND)


def sha256_text(content: str) -> str:
    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- 内容存储 (blob)
def put_blob(content: str) -> Tuple[str, int]:
    """写入内容, 返回 (sha256, 字节数)。同内容只存一份; 先写临时文件再原子替换。

    若目标已存在但**哈希不匹配**(损坏/被篡改), 直接重写 —— 让内容库能自愈。
    """
    data = (content or "").encode("utf-8")
    h = hashlib.sha256(data).hexdigest()
    p = _blob_path(h)
    intact = False
    if p.is_file():
        try:
            intact = hashlib.sha256(p.read_bytes()).hexdigest() == h
        except OSError:
            intact = False
    if not intact:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(p)
    return h, len(data)


def get_blob(h: str) -> Optional[str]:
    """按哈希取内容; 缺失或哈希不匹配(损坏)都返回 None (缓存可自愈)。"""
    if not h:
        return None
    p = _blob_path(h)
    if not p.is_file():
        return None
    data = p.read_bytes()
    if hashlib.sha256(data).hexdigest() != h:
        return None
    return data.decode("utf-8", errors="replace")


def blob_count() -> int:
    """blob 文件数 (诊断/测试用; 不计入写坏的 .tmp 残留)。"""
    root = blob_dir()
    if not root.is_dir():
        return 0
    return sum(1 for p in root.rglob("*")
               if p.is_file() and not p.name.endswith(".tmp"))


# ---------------------------------------------------------------- 索引: 发布 / 解析
def current(conn: sqlite3.Connection, name: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT v.* FROM evo_current c"
        " JOIN evo_versions v ON v.name = c.name AND v.version = c.version"
        " WHERE c.name = ?", (name,)
    ).fetchone()
    return dict(row) if row else None


def publish(conn: sqlite3.Connection, name: str, content: Optional[str] = None,
            kind: str = "", project_id: Optional[int] = None, ref: str = "",
            message: str = "", source_ref: str = "") -> dict:
    """发布一版内容。内容未变则**不新增版本**(幂等), 返回 {name, version, hash, changed}。

    ref 类 (项目内脚本, 内容在项目仓库) 只记引用、不写 blob —— hash 为空。
    """
    fname = ensure_ext(name, kind)
    if ref and content is not None:
        raise ValueError("ref 类只记引用, 不能同时给 content (内容在项目仓库)")
    cur = current(conn, fname)
    if ref and content is None:
        h, size = "", 0
    else:
        h, size = put_blob(content or "")

    # 元数据也参与"是否有变化"的判断 —— 否则"内容没变但改了归属/类型"会被静默丢弃
    ref_n = ref or ""
    k = kind or (cur["kind"] if cur else "") or DEFAULT_KIND
    pid = project_id if project_id is not None else (cur["project_id"] if cur else None)
    sref_n = source_ref or (cur["source_ref"] if cur else "") or ""
    if (cur and cur["hash"] == h and (cur["ref"] or "") == ref_n
            and cur["kind"] == k and cur["project_id"] == pid
            and (cur["source_ref"] or "") == sref_n):
        return {"name": fname, "version": cur["version"], "hash": h, "changed": False}

    # 版本号按**历史最大版本**递增, 不是"当前版本+1" —— 回滚会把当前指针往回拨,
    # 用当前+1 会撞上已存在的版本 (UNIQUE(name, version) 冲突)。
    # 并发下两个请求可能同时算出同一个号 → 撞 UNIQUE 时重算一次。
    for attempt in (1, 2):
        mx = conn.execute("SELECT COALESCE(MAX(version), 0) AS mx FROM evo_versions"
                          " WHERE name=?", (fname,)).fetchone()["mx"]
        ver = int(mx) + 1
        try:
            conn.execute(
                "INSERT INTO evo_versions(name, version, hash, size, kind, project_id,"
                " ref, message, source_ref) VALUES (?,?,?,?,?,?,?,?,?)",
                (fname, ver, h, size, k, pid, ref_n, message or "", sref_n),
            )
            break
        except sqlite3.IntegrityError:
            if attempt == 2:
                conn.rollback()
                raise
    conn.execute(
        "INSERT INTO evo_current(name, version, updated_at) VALUES (?,?,?)"
        " ON CONFLICT(name) DO UPDATE SET version=excluded.version,"
        " updated_at=excluded.updated_at",
        (fname, ver, _now()),
    )
    conn.commit()
    return {"name": fname, "version": ver, "hash": h, "changed": True}


def resolve(conn: sqlite3.Connection, name: str,
            version: Optional[int] = None) -> Optional[dict]:
    """取某版本 (version=None 取当前版本), 附上 content (ref 类为 None)。"""
    if version is None:
        row = current(conn, name)
    else:
        r = conn.execute("SELECT * FROM evo_versions WHERE name=? AND version=?",
                         (name, version)).fetchone()
        row = dict(r) if r else None
    if not row:
        return None
    row = dict(row)
    row["content"] = None if row.get("ref") else get_blob(row.get("hash") or "")
    return row


def history(conn: sqlite3.Connection, name: str) -> List[dict]:
    rows = conn.execute(
        "SELECT version, hash, size, kind, project_id, ref, message, source_ref, created_at"
        " FROM evo_versions WHERE name=? ORDER BY version DESC", (name,)
    ).fetchall()
    return [dict(r) for r in rows]


def rollback(conn: sqlite3.Connection, name: str, to_version: int) -> dict:
    """回滚 = 把当前指针指回某个历史版本; 不改任何 blob (可逆、零数据风险)。"""
    r = conn.execute("SELECT * FROM evo_versions WHERE name=? AND version=?",
                     (name, to_version)).fetchone()
    if not r:
        raise ValueError(f"版本不存在: {name}@v{to_version}")
    conn.execute(
        "INSERT INTO evo_current(name, version, updated_at) VALUES (?,?,?)"
        " ON CONFLICT(name) DO UPDATE SET version=excluded.version,"
        " updated_at=excluded.updated_at",
        (name, to_version, _now()),
    )
    conn.commit()
    return dict(r)


def ls(conn: sqlite3.Connection) -> List[dict]:
    """列出所有进化资产 (当前版本)。"""
    rows = conn.execute(
        "SELECT v.name, v.version, v.hash, v.size, v.kind, v.project_id, v.ref,"
        " v.created_at, c.updated_at FROM evo_current c"
        " JOIN evo_versions v ON v.name = c.name AND v.version = c.version"
        " ORDER BY v.name"
    ).fetchall()
    return [dict(r) for r in rows]


def manifest_index(conn: sqlite3.Connection) -> Dict[str, dict]:
    """客户端同步用的清单: name → {version, hash, size, kind, project_id, ref}。

    ref 类**不进清单** (内容在项目仓库, 没有可物化的内容)。
    """
    out: Dict[str, dict] = {}
    for row in ls(conn):
        if row.get("ref"):
            continue
        out[row["name"]] = {"version": row["version"], "hash": row["hash"],
                            "size": row["size"], "kind": row["kind"],
                            "project_id": row["project_id"]}
    return out


def _ext(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def _fmt_db_ts(ts: str) -> str:
    t = (ts or "").strip()
    return t[5:16] if len(t) >= 16 else t


def _fmt_mtime(ts: float) -> str:
    import datetime
    return datetime.datetime.fromtimestamp(ts).strftime("%m-%d %H:%M")


def tree(conn: sqlite3.Connection) -> List[dict]:
    """目录 UI 用的扁平清单 (索引条目 + 本地未收录文件)。

    保留旧 `list_evolution_files` 的形状 (name/ext/size/mtime/is_dir/children),
    另附加 version/hash/kind/ref/untracked 供 UI/CLI 展示版本与脏状态。
    """
    out: List[dict] = []
    seen = set()
    for row in ls(conn):
        name = row["name"]
        seen.add(name)
        out.append({
            "name": name, "ext": _ext(name), "size": row["size"],
            "mtime": _fmt_db_ts(row["created_at"]), "is_dir": False, "children": [],
            "version": row["version"], "hash": (row["hash"] or "")[:12],
            "kind": row["kind"], "project_id": row["project_id"],
            "ref": row["ref"], "untracked": False,
        })
    for name in _local_files():
        if name in seen:
            continue
        p = cache_dir(create=False) / name
        try:
            st = p.stat()
        except OSError:
            continue
        out.append({
            "name": name, "ext": _ext(name), "size": st.st_size,
            "mtime": _fmt_mtime(st.st_mtime), "is_dir": False, "children": [],
            "version": 0, "hash": (local_sha(p) or "")[:12], "kind": "other",
            "project_id": None, "ref": "", "untracked": True,
        })
    return sorted(out, key=lambda x: x["name"])


def materialize(conn: sqlite3.Connection, name: str,
                version: Optional[int] = None) -> Optional[str]:
    """把某版本内容写到本地缓存并更新 manifest (发布后本地立即可见/可执行)。"""
    row = resolve(conn, name, version)
    if row is None or row["content"] is None:
        return None
    p = cache_dir() / row["name"]
    p.write_text(row["content"], encoding="utf-8")
    man = read_manifest()
    entries = dict(man.get("entries", {}))
    entries[row["name"]] = {"version": row["version"], "hash": row["hash"],
                            "size": row["size"], "pulled_at": _now()}
    man["entries"] = entries
    write_manifest(man)
    return row["content"]


# ---------------------------------------------------------------- 本地缓存 (manifest)
def manifest_path() -> Path:
    return cache_dir() / MANIFEST_NAME


def read_manifest() -> dict:
    p = manifest_path()
    data: Any = {}
    if p.is_file():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("version", MANIFEST_VERSION)
    entries = data.get("entries")
    if not isinstance(entries, dict):
        entries = {}
    data["entries"] = entries
    return data


def write_manifest(data: dict) -> None:
    cache_dir().mkdir(parents=True, exist_ok=True)
    manifest_path().write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def local_sha(path: Path) -> Optional[str]:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _local_files() -> List[str]:
    d = cache_dir(create=False)
    if not d.is_dir():
        return []
    return sorted(p.name for p in d.iterdir()
                  if p.is_file() and p.name != MANIFEST_NAME
                  and not p.name.startswith(".")
                  and not p.name.endswith(".dirty.bak"))


# ---------------------------------------------------------------- 同步操作 (后端无关)
def status(remote: Dict[str, dict], cache: Optional[Path] = None) -> List[dict]:
    """本地缓存相对服务器的状态, 五态:

      in-sync    本地内容 == 服务器当前版本
      behind     本地是**干净的旧版本** (manifest 记录的哈希与本地一致), 可安全 pull
      dirty      本地被改过 / 或与服务器内容不一致 → pull 会拒绝覆盖
      missing    服务器有, 本地没有
      untracked  本地有, 服务器没有 (可 publish 上去)

    `behind` 只看"本地是否干净"(与 manifest 哈希一致), 不看版本号大小 —— 回滚会让
    服务器当前版本号变小, 用版本号比较会把干净的本地文件误判成 dirty。
    """
    cache = cache or cache_dir(create=False)
    entries = read_manifest().get("entries", {})
    names = sorted(set(remote) | set(entries) | set(_local_files()))
    out: List[dict] = []
    for n in names:
        r = remote.get(n)
        m = entries.get(n) or {}
        p = cache / n
        lh = local_sha(p)
        if r is None:
            st = "untracked"
        elif lh is None:
            st = "missing"
        elif lh == r["hash"]:
            st = "in-sync"
        elif m.get("hash") == lh:
            st = "behind"
        else:
            st = "dirty"
        out.append({"name": n, "state": st, "local_hash": lh,
                    "remote_version": (r or {}).get("version"),
                    "local_version": m.get("version")})
    return out


def pull(backend, names: Optional[List[str]] = None, all_: bool = False,
         force: bool = False) -> dict:
    """按清单把内容物化到本地缓存。

    规则: 内容未变 → 跳过; 本地是干净的旧版本 → 直接覆盖; 本地被改过 → **拒绝覆盖**
    (报 skipped_dirty), 只有 force=True 才覆盖 (覆盖前把旧文件另存为 <name>.dirty.bak 以免手改内容丢失)。
    """
    remote = backend.manifest()
    cache = cache_dir()
    man = read_manifest()
    entries = dict(man.get("entries", {}))
    res: Dict[str, List[str]] = {"written": [], "up_to_date": [], "skipped_dirty": [],
                                 "missing_remote": [], "hash_mismatch": []}
    targets = sorted(remote) if all_ else list(names or [])
    for n in targets:
        r = remote.get(n)
        if not r:
            res["missing_remote"].append(n)
            continue
        p = cache / n
        lh = local_sha(p)
        if lh == r["hash"]:
            entries[n] = {"version": r["version"], "hash": r["hash"],
                          "size": r["size"], "pulled_at": _now()}
            res["up_to_date"].append(n)
            continue
        m = entries.get(n) or {}
        if lh is not None and not force and not (m.get("hash") == lh):
            res["skipped_dirty"].append(n)
            continue
        content = backend.content(n, r["version"])
        if content is None:
            res["missing_remote"].append(n)
            continue
        # 必须校验哈希后再落盘: 传输被截断/内容被篡改时不能写进缓存
        # (否则会写成"用户没改过却显示 dirty"的文件, 还被 publish 推回去)
        got = sha256_text(content)
        if got != r["hash"]:
            res["hash_mismatch"].append(n)
            continue
        if p.is_file() and lh is not None:
            p.with_name(p.name + ".dirty.bak").write_bytes(p.read_bytes())
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        entries[n] = {"version": r["version"], "hash": got,
                      "size": r["size"], "pulled_at": _now()}
        res["written"].append(n)
    man["entries"] = entries
    write_manifest(man)
    return res


def publish_local(backend, name: str, message: str = "", kind: str = "",
                  project_id: Optional[int] = None) -> dict:
    """把本地缓存里的文件作为新版本推回服务器 (显式动作, 没有自动同步)。

    名字先过 `ensure_ext` 归一化 —— 否则 `noext` 会推成 `noext.txt`, 本地却按 `noext`
    记账, status 永远显示 untracked+missing (同时也堵住带 `/` 的路径穿越)。
    """
    fname = ensure_ext(name, kind)
    p = cache_dir() / fname
    if not p.is_file():
        raw = cache_dir() / Path(str(name)).name
        if raw.is_file():
            # 用户按原名存的文件(如无扩展名)也接受: 顺手归一化文件名,
            # 让本地缓存与服务器名字一致 —— 否则 status 会永远显示一个 untracked 幽灵
            p = raw
    if not p.is_file():
        raise ValueError(f"本地没有这个文件: {p}")
    if p.name != fname and not (cache_dir() / fname).exists():
        try:
            p.replace(cache_dir() / fname)
            p = cache_dir() / fname
        except OSError:
            pass
    content = p.read_text(encoding="utf-8")
    out = backend.publish(name=fname, content=content, kind=kind,
                          project_id=project_id, message=message)
    man = read_manifest()
    entries = dict(man.get("entries", {}))
    entries[out["name"]] = {"version": out["version"], "hash": out["hash"],
                            "size": len(content.encode("utf-8")), "pulled_at": _now()}
    man["entries"] = entries
    write_manifest(man)
    return out


def publish_all(backend, message: str = "") -> Dict[str, List[dict]]:
    """把本地所有 dirty / untracked 文件一次推上去 (首次把本地手写的资产倒进服务器用)。"""
    res: Dict[str, List[dict]] = {"published": [], "unchanged": [], "failed": []}
    for s in status(backend.manifest()):
        if s["state"] not in ("dirty", "untracked"):
            continue
        try:
            out = publish_local(backend, s["name"], message=message)
        except Exception as e:  # noqa: BLE001 - 单个失败不影响其余
            res["failed"].append({"name": s["name"], "error": str(e)})
            continue
        (res["published"] if out.get("changed") else res["unchanged"]).append(out)
    return res


# ---------------------------------------------------------------- 后端适配
class LocalBackend:
    """直连本地 SQLite (大脑在本机 / 服务器进程内)。"""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def index(self) -> List[dict]:
        return ls(self.conn)

    def manifest(self) -> Dict[str, dict]:
        return manifest_index(self.conn)

    def content(self, name: str, version: Optional[int] = None) -> Optional[str]:
        row = resolve(self.conn, name, version)
        return None if row is None else row["content"]

    def publish(self, name: str, content: Optional[str] = None, *, kind: str = "",
                project_id: Optional[int] = None, message: str = "",
                source_ref: str = "", ref: str = "") -> dict:
        return publish(self.conn, name, content, kind=kind, project_id=project_id,
                       ref=ref, message=message, source_ref=source_ref)

    def history(self, name: str) -> List[dict]:
        return history(self.conn, name)

    def rollback(self, name: str, to_version: int) -> dict:
        return rollback(self.conn, name, to_version)


class HttpBackend:
    """通过 REST 连远端大脑 (设了 LCLONE_WEB_URL 时走这条)。"""

    def __init__(self, base_url: str, token: str = "", timeout: int = 15):
        self.base = (base_url or "").rstrip("/")
        self.token = token or ""
        self.timeout = timeout

    def _req(self, method: str, path: str, payload: Optional[dict] = None) -> Any:
        import urllib.error
        import urllib.parse
        import urllib.request

        url = self.base + path
        data = None
        headers = {"accept": "application/json"}
        if self.token:
            headers["authorization"] = "Bearer " + self.token
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["content-type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                raw = r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8")[:200]
            except Exception:
                pass
            raise RuntimeError(f"{method} {path} → HTTP {e.code} {detail}") from e
        except Exception as e:  # 连接失败等
            raise RuntimeError(f"{method} {path} 失败: {e}") from e
        return json.loads(raw) if raw else {}

    def index(self) -> List[dict]:
        return self._req("GET", "/api/evolution/index").get("items", [])

    def manifest(self) -> Dict[str, dict]:
        return self._req("GET", "/api/evolution/manifest").get("items", {})

    def content(self, name: str, version: Optional[int] = None) -> Optional[str]:
        import urllib.parse
        q = {"name": name}
        if version is not None:
            q["version"] = str(version)
        body = self._req("GET", "/api/evolution/content?" + urllib.parse.urlencode(q))
        return body.get("content")

    def publish(self, name: str, content: Optional[str] = None, *, kind: str = "",
                project_id: Optional[int] = None, message: str = "",
                source_ref: str = "", ref: str = "") -> dict:
        return self._req("POST", "/api/evolution/publish", {
            "name": name, "content": content, "kind": kind,
            "project_id": project_id, "message": message,
            "source_ref": source_ref, "ref": ref,
        }).get("result", {})

    def history(self, name: str) -> List[dict]:
        import urllib.parse
        return self._req("GET", "/api/evolution/history?"
                         + urllib.parse.urlencode({"name": name})).get("items", [])

    def rollback(self, name: str, to_version: int) -> dict:
        return self._req("POST", "/api/evolution/rollback",
                         {"name": name, "version": to_version}).get("result", {})

    def find_project(self, ref: Optional[str] = None, repo_path: str = "") -> Optional[int]:
        """把项目名/id 或**本机仓库路径**解析成服务器的 project_id。

        远端大脑下服务端看不到客户端路径, 归属必须在客户端解析后随请求上报
        (与 DSH 插件的 resolveProject 同规则): 先按名字/id 命中, 再按 path 最长前缀匹配。
        """
        items = self._req("GET", "/api/projects").get("items", [])
        if ref:
            r = str(ref).strip()
            if r.lower() in ("global", "个人区", "个人", "personal", "none"):
                return None
            for p in items:
                if str(p.get("id")) == r or p.get("name") == r:
                    return p.get("id")
            return None
        if repo_path:
            best: Optional[tuple] = None
            for p in items:
                path = (p.get("path") or "").rstrip("/")
                if path and (repo_path == path or repo_path.startswith(path + "/")):
                    if best is None or len(path) > best[1]:
                        best = (p.get("id"), len(path))
            if best:
                return best[0]
        return None


def backend_for(conn: Optional[sqlite3.Connection] = None,
                local: bool = False):
    """按环境选后端: 设了 LCLONE_WEB_URL(且未强制 local) → HTTP; 否则本地 DB。

    与 DSH 插件的既有约定一致 —— 本机若已 export LCLONE_WEB_URL, CLI 就直接对服务器操作。
    """
    url = (config.get("LCLONE_WEB_URL") or "").strip()
    if url and not local:
        return HttpBackend(url, token=config.get("LCLONE_API_KEY") or "")
    if conn is None:
        raise RuntimeError("本地后端需要数据库连接")
    return LocalBackend(conn)


# ---------------------------------------------------------------- 存量迁移 / 元数据补正
def migrate_cache_files(conn: sqlite3.Connection) -> List[dict]:
    """把缓存目录里**尚未进索引**的文件发布为 v1 (存量文件一次性摄入)。

    只处理本地缓存目录里的文件; 已在索引里的名字不动 (不覆盖、不自动升版)。
    """
    known = {row["name"] for row in ls(conn)}
    out: List[dict] = []
    for name in _local_files():
        if name in known:
            continue
        p = cache_dir(create=False) / name
        try:
            content = p.read_text(encoding="utf-8")
        except Exception:
            continue
        r = publish(conn, name, content, kind=kind_of_name(name),
                    message="存量文件摄入 (v1)")
        out.append(r)
    return out


def retype_default_kinds(backend) -> List[dict]:
    """把 kind 仍是默认值、但扩展名能推断出更具体类型的资产补正类型。

    典型场景: 早期 migrate 未推断 kind, 于是 `.md` 规范文档与 `.sh` 脚本都被标成
    `other`, 元数据上分不出来。补正走**正常发布流程**(新增一版并在版本说明里写明),
    不原地改历史 —— 与"evo_versions 只追加"的模型一致。
    """
    out: List[dict] = []
    for row in backend.index():
        if (row.get("kind") or DEFAULT_KIND) != DEFAULT_KIND:
            continue
        want = kind_of_name(row["name"])
        if want == DEFAULT_KIND:
            continue
        content = backend.content(row["name"])
        if content is None:  # ref 类没有内容, 跳过
            continue
        res = backend.publish(name=row["name"], content=content, kind=want,
                              message=f"类型补正: {DEFAULT_KIND} → {want}")
        out.append({"name": res.get("name", row["name"]),
                    "version": res.get("version"), "kind": want,
                    "changed": res.get("changed")})
    return out
