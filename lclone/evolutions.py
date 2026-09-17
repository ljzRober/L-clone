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

import contextlib
import hashlib
import json
import os
import re
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


# ---------------------------------------------------------------- 可编辑内容判定
DEFAULT_MAX_EDITABLE_BYTES = 262144   # 256 KB


def max_editable_bytes() -> int:
    """可编辑判定的字节上限; 每次调用都读 env, 便于运行时覆盖与测试。"""
    raw = (os.environ.get("LCLONE_EVO_MAX_EDIT_BYTES") or "").strip()
    try:
        n = int(raw)
    except ValueError:
        return DEFAULT_MAX_EDITABLE_BYTES
    return n if n > 0 else DEFAULT_MAX_EDITABLE_BYTES


def editability(raw: bytes) -> tuple[bool, str]:
    """字节内容 → (是否可编辑, 原因码)。服务端唯一权威, 前端只镜像。

    原因码: "" 可编辑 | "too_large" 超尺寸上限 | "binary" 含 NUL 或非法 UTF-8。
    先判尺寸再解码: 超大内容无需付出解码代价。
    """
    if raw is None:
        return True, ""
    if len(raw) > max_editable_bytes():
        return False, "too_large"
    if b"\x00" in raw:
        return False, "binary"
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        return False, "binary"
    return True, ""


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


def get_blob_bytes(h: str) -> Optional[bytes]:
    """按哈希取**原始字节**(不解码), 供可编辑判定用; 缺失或哈希不匹配返回 None。

    与 `get_blob` 的区别: 后者用 errors="replace" 解码, 非法 UTF-8 会被替换成
    替换字符而不是暴露出来 —— 因此判定二进制必须走本函数。
    """
    if not h:
        return None
    p = _blob_path(h)
    if not p.is_file():
        return None
    data = p.read_bytes()
    if hashlib.sha256(data).hexdigest() != h:
        return None
    return data


def blob_count() -> int:
    """blob 文件数 (诊断/测试用; 不计入写坏的 .tmp 残留)。"""
    root = blob_dir()
    if not root.is_dir():
        return 0
    return sum(1 for p in root.rglob("*")
               if p.is_file() and not p.name.endswith(".tmp"))


# ---------------------------------------------------------------- 索引: 发布 / 解析
def current(conn: sqlite3.Connection, name: str) -> Optional[dict]:
    """当前版本 + 墓碑状态 (deleted_at / renamed_to)。

    墓碑只影响**清单列举** (`ls`), 不影响按名字直接读取 —— 删除后历史仍可读、可回滚。
    """
    row = conn.execute(
        "SELECT v.*, c.deleted_at, c.renamed_to FROM evo_current c"
        " JOIN evo_versions v ON v.name = c.name AND v.version = c.version"
        " WHERE c.name = ?", (name,)
    ).fetchone()
    return dict(row) if row else None


class VersionConflict(Exception):
    """乐观锁冲突: 调用方 base_version 与服务器当前版本不一致 (或已被墓碑删除)。

    `deleted=True` 表示版本号虽然与 base_version 相同, 但该名字在此期间被删除
    (墓碑) —— 调用方读到的是"当时还活着"的视图, 因此同样是陈旧视图, 必须拒绝,
    否则带 base_version 的写会静默复活被删资产 (lost update)。
    """

    def __init__(self, name: str, base_version: Optional[int],
                 current_version: Optional[int], deleted: bool = False):
        self.name = name
        self.base_version = base_version
        self.current_version = current_version
        self.deleted = deleted
        cur = f"v{current_version}" if current_version is not None else "不存在"
        super().__init__(
            f"版本冲突: {name} 基于 v{base_version}, 服务器当前为 {cur}"
            + (" (已被删除)" if deleted else ""))


def _check_base_version(conn: sqlite3.Connection, name: str,
                        base_version: Optional[int]) -> None:
    """乐观锁校验: base_version 为 None 表示不校验 (向后兼容)。

    删除只打墓碑、**不新增版本**, 所以"版本号相同"不等于"视图未过期":
    版本一致但当前是墓碑态时同样判冲突 (不复活被删资产)。

    ⚠️ 本函数只做**读**。调用方必须把它和后续写入放进 `_immediate()` 的同一个排他
    事务里 —— 单靠比较版本号是 check-then-act, 挡不住并发丢更新。
    """
    if base_version is None:
        return
    row = current(conn, name)
    actual = row["version"] if row else None
    if actual != base_version:
        raise VersionConflict(name, base_version, actual)
    if row and (row.get("deleted_at") or ""):
        raise VersionConflict(name, base_version, actual, deleted=True)


# 已持有排他事务的连接 (按 id), 供 rename -> publish 这种"外层已开事务"的嵌套复用。
_EXCL_TX: set = set()


@contextlib.contextmanager
def _immediate(conn: sqlite3.Connection):
    """把「读当前版本 → 写入」整段包进**排他事务** (`BEGIN IMMEDIATE`)。

    为什么必须: 乐观锁是 check-then-act —— 不加锁时两个同 `base_version` 的写可以
    先后都通过校验, 后者把当前指针推过前者 (lost update)。`UNIQUE(name, version)`
    只挡重号, 挡不住丢更新 (第二个写者拿到的是下一个号, 两个都"成功")。
    `BEGIN IMMEDIATE` 在进入临界区时就拿写锁, 于是后到者要么等前者提交、拿到已更新的
    版本号而 409, 要么在 busy timeout 后拿到 `sqlite3.OperationalError` (服务端故障,
    由 web 层冒泡成 500) —— 两条路都不会静默覆盖。

    两个必须注意的 sqlite3 细节:
      * 默认的隐式事务只在 DML 前才 BEGIN 且是 deferred; 若连接上已有一个未了结的
        事务, `BEGIN IMMEDIATE` 会报 "cannot start a transaction within a
        transaction"(而不是嵌套), 所以进入前先 `commit()` —— 对无事务的连接是 no-op。
      * `rename()` 内部会调 `publish()`。已在同一连接的排他事务里时**复用它**(直接
        yield), 既不嵌套 BEGIN、也不提前 commit —— 于是改名整体变成一次原子事务。
    """
    if id(conn) in _EXCL_TX:
        yield conn
        return
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    _EXCL_TX.add(id(conn))
    try:
        yield conn
    except BaseException:
        conn.rollback()
        raise
    else:
        conn.commit()
    finally:
        _EXCL_TX.discard(id(conn))


def publish(conn: sqlite3.Connection, name: str, content: Optional[str] = None,
            kind: str = "", project_id: Optional[int] = None, ref: str = "",
            message: str = "", source_ref: str = "",
            base_version: Optional[int] = None, only_if_new: bool = False) -> dict:
    """发布一版内容。内容未变则**不新增版本**(幂等), 返回 {name, version, hash, changed}。

    ref 类 (项目内脚本, 内容在项目仓库) 只记引用、不写 blob —— hash 为空。

    `base_version` 是乐观锁: 只在显式给出时校验 (None = 不校验, 既有调用方行为不变;
    不给 base_version 时对墓碑名字发布仍视为**重新激活**, 该路径是刻意保留的)。
    版本号一致但名字已是墓碑态时也判冲突 —— 删除不产生新版本, 版本相同不代表视图未过期。
    校验**早于任何写**(含 `put_blob`) —— 冲突路径零副作用: 不加版本、不动当前指针、
    也不留下未引用的内容对象。

    `only_if_new` 用于"新建"语义 —— 目标名已是**活跃**资产时抛 `NameConflict` (409);
    **墓碑**名不拒绝, 按既有的"重新激活"路径续用自身版本号。

    整个「读当前版本 → 校验 → 写入」在 `_immediate()` 的**排他事务**内完成 (见该函数):
    否则两个同 `base_version` 的写能先后都通过校验, 后者把指针推过前者。
    """
    fname = ensure_ext(name, kind)
    if ref and content is not None:
        raise ValueError("ref 类只记引用, 不能同时给 content (内容在项目仓库)")
    with _immediate(conn):
        cur = current(conn, fname)
        _check_base_version(conn, fname, base_version)
        if only_if_new and cur is not None and not (cur.get("deleted_at") or ""):
            raise NameConflict(fname)      # 活跃名 → 409; 墓碑名仍允许(重新激活, 见 docstring)
        if ref and content is None:
            h, size = "", 0
        else:
            h, size = put_blob(content or "")

        # 元数据也参与"是否有变化"的判断 —— 否则"内容没变但改了归属/类型"会被静默丢弃
        ref_n = ref or ""
        k = kind or (cur["kind"] if cur else "") or DEFAULT_KIND
        pid = project_id if project_id is not None else (cur["project_id"] if cur else None)
        sref_n = source_ref or (cur["source_ref"] if cur else "") or ""
        # 墓碑名字再次 publish 视为**重新激活** (墓碑不在默认清单里, 用户以同名新建应当成功)。
        # 因此墓碑态必须跳过"内容未变则不新增版本"的早返回, 让流程走到 upsert 去清墓碑 ——
        # 否则"删除后原样重发"会被早返回挡住, 名字永远留在墓碑态。
        tombstoned = bool(cur and (cur.get("deleted_at") or ""))
        if (not tombstoned and cur and cur["hash"] == h and (cur["ref"] or "") == ref_n
                and cur["kind"] == k and cur["project_id"] == pid
                and (cur["source_ref"] or "") == sref_n):
            return {"name": fname, "version": cur["version"], "hash": h, "changed": False}

        # 版本号按**历史最大版本**递增, 不是"当前版本+1" —— 回滚会把当前指针往回拨,
        # 用当前+1 会撞上已存在的版本 (UNIQUE(name, version) 冲突)。
        # 排他事务下重号已不可能, 保留重试只为兜住"库被外部进程并发写"的残余窗口。
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
                    raise
        conn.execute(
            "INSERT INTO evo_current(name, version, updated_at, deleted_at, renamed_to)"
            " VALUES (?,?,?,'','')"
            " ON CONFLICT(name) DO UPDATE SET version=excluded.version,"
            " updated_at=excluded.updated_at, deleted_at='', renamed_to=''",
            (fname, ver, _now()),
        )
    res = {"name": fname, "version": ver, "hash": h, "changed": True}
    # 版本保留窗口: 默认每资产最近 5 个 (LCLONE_EVO_KEEP_VERSIONS); 当前指针版本永不剪
    pr = prune_versions(conn, name=fname, dry_run=False)
    if pr["assets"]:
        res["pruned_versions"] = pr["assets"][0]["pruned"]
        res["pruned_blobs"] = pr["blobs_removed"]
    return res


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


def delete(conn: sqlite3.Connection, name: str,
           base_version: Optional[int] = None) -> dict:
    """墓碑删除: 从默认清单移出, 但**不动** evo_versions 与 blob (可恢复)。幂等。

    `base_version` 是乐观锁 (None = 不校验): 名字不存在时既有语义仍是 `ValueError`;
    但若同时给了 `base_version`, 当前版本为 None → 由校验抛 `VersionConflict`。
    名字已是墓碑态且给了 `base_version` 时同样抛 `VersionConflict(deleted=True)`
    (不带 `base_version` 的重复删除仍是幂等的 `changed=False`)。

    「读当前版本 → 校验 → 打墓碑」在同一个排他事务内 (见 `_immediate`)。
    """
    with _immediate(conn):
        cur = current(conn, name)
        _check_base_version(conn, name, base_version)
        if cur is None:
            raise ValueError(f"进化资产不存在: {name}")
        if cur.get("deleted_at"):
            return {"name": name, "deleted_at": cur["deleted_at"], "changed": False}
        ts = _now()
        conn.execute("UPDATE evo_current SET deleted_at=?, updated_at=? WHERE name=?",
                     (ts, ts, name))
    return {"name": name, "deleted_at": ts, "changed": True}


def restore(conn: sqlite3.Connection, name: str) -> dict:
    """恢复墓碑: 清 deleted_at 与 renamed_to (回到普通活跃资产)。幂等。"""
    cur = current(conn, name)
    if cur is None:
        raise ValueError(f"进化资产不存在: {name}")
    if not (cur.get("deleted_at") or cur.get("renamed_to")):
        return {"name": name, "changed": False}
    conn.execute("UPDATE evo_current SET deleted_at='', renamed_to='', updated_at=?"
                 " WHERE name=?", (_now(), name))
    conn.commit()
    return {"name": name, "changed": True}


class NameConflict(Exception):
    """改名目标名冲突: 该名字已是活跃资产。"""

    def __init__(self, name: str):
        self.name = name
        super().__init__(f"目标名字已是活跃进化资产: {name}")


def rename(conn: sqlite3.Connection, name: str, new_name: str,
           base_version: Optional[int] = None, message: str = "") -> dict:
    """改名 = 新名字发布 v1 (内容继承当前版本) + 旧名字墓碑并记 renamed_to。

    **不迁移历史**: 旧名字的 evo_versions 行原样不动, 新名字从 v1 起算。

    目标名字已是活跃资产时抛 `NameConflict` (墓碑目标名允许 —— publish 会复活它);
    `base_version` 是旧名字的乐观锁 (None = 不校验), 校验早于任何写。

    当前版本的内容对象**缺失或损坏** (`get_blob` 返回 None) 时抛 `ValueError` ——
    内容继承无法兑现, 拒绝改名以免静默产出空资产 (合法的空内容 hash 非空且读回 `""`,
    不触发该守卫; ref 类无 blob, 同样不触发)。

    整体在一个排他事务内: 内层 `publish` 复用外层事务 (见 `_immediate`), 于是"新名字发布
    + 旧名字墓碑"要么都生效要么都不生效 —— 不再有"崩溃窗口里留下两个活跃名字"。
    """
    with _immediate(conn):
        _check_base_version(conn, name, base_version)
        cur = current(conn, name)
        if cur is None:
            raise ValueError(f"进化资产不存在: {name}")
        new_fname = ensure_ext(new_name, cur["kind"])
        if new_fname == name:
            return {"old_name": name, "new_name": new_fname, "version": cur["version"],
                    "hash": cur["hash"], "changed": False}
        tgt = current(conn, new_fname)
        if tgt is not None and not (tgt.get("deleted_at") or ""):
            raise NameConflict(new_fname)
        content = None if cur.get("ref") else get_blob(cur.get("hash") or "")
        if content is None and not cur.get("ref"):
            raise ValueError(f"内容缺失或损坏, 拒绝改名以免丢失内容: {name}")
        out = publish(conn, new_fname, content, kind=cur["kind"],
                      project_id=cur["project_id"], ref=cur.get("ref") or "",
                      message=message or f"改名自 {name}")
        # 旧名墓碑: 必须同时写 deleted_at 与 renamed_to, 否则改名旧名绕过乐观锁
        ts = _now()
        conn.execute(
            "UPDATE evo_current SET deleted_at=?, renamed_to=?, updated_at=? WHERE name=?",
            (ts, new_fname, ts, name))
    return {"old_name": name, "new_name": new_fname, "version": out["version"],
            "hash": out["hash"], "changed": True}


def ls(conn: sqlite3.Connection, include_deleted: bool = False) -> List[dict]:
    """列出所有进化资产 (当前版本)。默认不含墓碑; include_deleted=True 时含并带墓碑字段。"""
    sql = ("SELECT v.name, v.version, v.hash, v.size, v.kind, v.project_id, v.ref,"
           " v.created_at, c.updated_at, c.deleted_at, c.renamed_to FROM evo_current c"
           " JOIN evo_versions v ON v.name = c.name AND v.version = c.version")
    if not include_deleted:
        sql += " WHERE COALESCE(c.deleted_at, '') = ''"
    sql += " ORDER BY v.name"
    rows = conn.execute(sql).fetchall()
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


KEEP_VERSIONS_DEFAULT = 5

# 说明性文档的扩展名 (规范/说明/模板: 这类内容的家是 insight, 不是 evolution)
_PROSE_EXT = {"md", "markdown", "rst", "adoc"}
# 脚本/数据类扩展名 (evolution 的正当载体)
_CODE_EXT = {"sh", "bash", "zsh", "py", "js", "mjs", "ts", "rb", "pl", "ps1",
             "json", "yaml", "yml", "toml", "ini", "cfg", "conf", "csv", "sql"}


def audit_misplaced(conn: sqlite3.Connection) -> List[dict]:
    """只读巡检: 找出**疑似放错桶**的资产 (说明性文档应做成 insight, evolution 只装数据与脚本)。

    判据只看形态, 不做语义判断, 因此**只提示、绝不自动删**:
      - `ref` 类 (内容在项目仓库) 跳过;
      - 扩展名是代码/数据类的跳过;
      - `.md/.rst/...` 且正文像说明文 (有 markdown 标题或成句标点够多) → 提示;
      - `.txt` 这类: 有标题/成句特征才算说明文, 纯数据 (密钥表/清单) 不算。
    """
    out: List[dict] = []
    for row in ls(conn):
        name = row["name"]
        if row.get("ref"):
            continue
        ext = _ext(name)
        if ext in _CODE_EXT:
            continue
        content = (resolve(conn, name) or {}).get("content") or ""
        head = content.lstrip()
        del head
        has_heading = bool(re.search(r"^#{1,6}\s", content, re.M))
        sentences = len(re.findall(r"[。；！？]|[.;!?]\s", content))
        prose = has_heading or sentences >= 6
        if ext not in _PROSE_EXT and not prose:
            continue          # 纯数据文件 (.txt/.json 之类) 不提示
        if not prose:
            continue
        out.append({
            "name": name, "kind": row.get("kind"), "size": row.get("size"),
            "reason": ("扩展名是文档类" if ext in _PROSE_EXT else "正文像说明文")
                      + " —— 规范/说明应写成 insight (remember); "
                        "evolution 只承载数据与可执行文件",
        })
    return out


def keep_versions() -> int:
    """每个资产保留的版本数上限 (LCLONE_EVO_KEEP_VERSIONS, 默认 5; <=0 = 不限制)。"""
    return config.get_int("LCLONE_EVO_KEEP_VERSIONS", KEEP_VERSIONS_DEFAULT)


def _gc_blobs(conn: sqlite3.Connection, dry_run: bool = True) -> int:
    """回收没有任何 `evo_versions` 行引用的内容对象。

    内容寻址: 同一 hash 可能被多个资产/版本共享, 因此只在**全表**都不再引用时才删。
    """
    used = {r["hash"] for r in conn.execute(
        "SELECT DISTINCT hash FROM evo_versions WHERE hash<>''").fetchall()}
    root = blob_dir()
    if not root.is_dir():
        return 0
    removed = 0
    for sub in sorted(root.iterdir()):
        if not sub.is_dir():
            continue
        for f in sorted(sub.iterdir()):
            if f.name in used:
                continue
            if not dry_run:
                try:
                    f.unlink()
                except OSError:
                    continue
            removed += 1
        if not dry_run:
            try:
                if not any(sub.iterdir()):
                    sub.rmdir()
            except OSError:
                pass
    return removed


def prune_versions(conn: sqlite3.Connection, name: Optional[str] = None,
                   keep: Optional[int] = None, dry_run: bool = True) -> dict:
    """版本保留窗口: 每个资产**只保留最近 N 个版本** (默认 5), 并额外保留当前指针版本。

    两条硬边界:
      - 当前版本 (`evo_current.version`) **永远保留** —— 回滚到旧版后, 若只按"最近 N 个"
        剪, 那一版会被下一次发布剪掉, 回滚语义当场失效;
      - 只为没有任何剩余版本引用的 hash 回收 blob (内容寻址, 可能被多版本/多资产共享)。

    返回 {"assets": [{name, kept, pruned}], "blobs_removed": n, "dry_run": bool}。
    """
    limit = keep_versions() if keep is None else int(keep)
    names = [name] if name else [r["name"] for r in conn.execute(
        "SELECT DISTINCT name FROM evo_versions").fetchall()]
    out: dict = {"assets": [], "blobs_removed": 0, "dry_run": bool(dry_run)}
    for nm in names:
        vers = [r["version"] for r in conn.execute(
            "SELECT version FROM evo_versions WHERE name=? ORDER BY version DESC",
            (nm,)).fetchall()]
        if not vers:
            continue
        keep_set = set(vers[:limit]) if limit and limit > 0 else set(vers)
        cur = conn.execute("SELECT version FROM evo_current WHERE name=?",
                           (nm,)).fetchone()
        if cur is not None:
            keep_set.add(cur["version"])
        drop = [v for v in vers if v not in keep_set]
        if drop and not dry_run:
            conn.execute("DELETE FROM evo_versions WHERE name=? AND version IN (%s)"
                         % ",".join("?" * len(drop)), (nm, *drop))
        if drop:
            out["assets"].append({"name": nm, "kept": sorted(keep_set),
                                  "pruned": sorted(drop)})
    if not dry_run:
        conn.commit()
    out["blobs_removed"] = _gc_blobs(conn, dry_run=dry_run)
    return out


def _ext(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def _fmt_db_ts(ts: str) -> str:
    t = (ts or "").strip()
    return t[5:16] if len(t) >= 16 else t


def _fmt_mtime(ts: float) -> str:
    import datetime
    return datetime.datetime.fromtimestamp(ts).strftime("%m-%d %H:%M")


def tree(conn: sqlite3.Connection, include_deleted: bool = False) -> List[dict]:
    """目录 UI 用的扁平清单 (索引条目 + 本地未收录文件)。

    保留旧 `list_evolution_files` 的形状 (name/ext/size/mtime/is_dir/children),
    另附加 version/hash/kind/ref/untracked 供 UI/CLI 展示版本与脏状态。
    `include_deleted` 透传给 `ls` —— 形状**不因墓碑而改变**。
    """
    out: List[dict] = []
    seen = set()
    # 墓碑名字**一次算出**、在下面的本地缓存行里一并跳过: 已删除的资产可能仍在
    # 缓存目录里有副本 (先前 pull / publish_local 留下的), 不跳过它就会被当成
    # `untracked` 行重新出现在看板上, 与"删除后从默认看板消失"直接矛盾。
    tombstoned = {r["name"] for r in ls(conn, include_deleted=True)
                  if r.get("deleted_at")}
    for row in ls(conn, include_deleted=include_deleted):
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
        if name in seen or name in tombstoned:
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
def tombstones(conn: sqlite3.Connection) -> set:
    """墓碑 (已删除) 名字集合。

    默认清单 (`ls`) 与 manifest 都不含墓碑条目, 于是"服务器已删除"与"本地有、服务器
    从来没有" (untracked) 在同步状态里长得一模一样 —— 而后者会被 `publish --all`
    推上去, 推一个墓碑名等于经 `publish` 的复活路径**静默撤销那次删除**。
    """
    return {r["name"] for r in ls(conn, include_deleted=True) if r.get("deleted_at")}


def tombstones_of(backend) -> set:
    """后端墓碑集合 (两端同一语义); 缺该方法的自定义后端退回空集 (与本 change 之前一致)。"""
    fn = getattr(backend, "tombstones", None)
    return set(fn() or ()) if callable(fn) else set()


def status(remote: Dict[str, dict], cache: Optional[Path] = None,
           deleted: Optional[set] = None) -> List[dict]:
    """本地缓存相对服务器的状态, 六态:

      in-sync    本地内容 == 服务器当前版本
      behind     本地是**干净的旧版本** (manifest 记录的哈希与本地一致), 可安全 pull
      dirty      本地被改过 / 或与服务器内容不一致 → pull 会拒绝覆盖
      missing    服务器有, 本地没有
      untracked  本地有, 服务器**从来没有** (可 publish 上去)
      deleted    服务器已把该名字标为墓碑 (删除), 本地还留着副本

    `behind` 只看"本地是否干净"(与 manifest 哈希一致), 不看版本号大小 —— 回滚会让
    服务器当前版本号变小, 用版本号比较会把干净的本地文件误判成 dirty。

    `deleted` 必须与 `untracked` 分开: 墓碑名同时"不在默认清单"且"本地有文件", 但它
    SHALL NOT 被 `publish --all` 推上去 (那会静默复活被删资产), 恢复的唯一正路是
    `restore`。集合由调用方给出 (本地 `tombstones(conn)` / 远端 index?include_deleted=true),
    因为两个后端的 manifest 都不含墓碑 —— 这是本函数必须**额外**知道的一件事。
    """
    cache = cache or cache_dir(create=False)
    deleted = set(deleted or ())
    entries = read_manifest().get("entries", {})
    names = sorted(set(remote) | set(entries) | set(_local_files()) | deleted)
    out: List[dict] = []
    for n in names:
        r = remote.get(n)
        m = entries.get(n) or {}
        p = cache / n
        lh = local_sha(p)
        if n in deleted:
            st = "deleted"
        elif r is None:
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


def backend_status(backend, cache: Optional[Path] = None) -> List[dict]:
    """`status()` 的后端便捷入口: 清单与墓碑集合都从后端取 (CLI / publish_all 用)。"""
    return status(backend.manifest(), cache=cache, deleted=tombstones_of(backend))


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
                  project_id: Optional[int] = None,
                  base_version: Optional[int] = None) -> dict:
    """把本地缓存里的文件作为新版本推回服务器 (显式动作, 没有自动同步)。

    名字先过 `ensure_ext` 归一化 —— 否则 `noext` 会推成 `noext.txt`, 本地却按 `noext`
    记账, status 永远显示 untracked+missing (同时也堵住带 `/` 的路径穿越)。

    `base_version` 是乐观锁, 原样透传给后端 (None = 不校验)。
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
                          project_id=project_id, message=message,
                          base_version=base_version)
    man = read_manifest()
    entries = dict(man.get("entries", {}))
    entries[out["name"]] = {"version": out["version"], "hash": out["hash"],
                            "size": len(content.encode("utf-8")), "pulled_at": _now()}
    man["entries"] = entries
    write_manifest(man)
    return out


def publish_all(backend, message: str = "") -> Dict[str, List[dict]]:
    """把本地所有 dirty / untracked 文件一次推上去 (首次把本地手写的资产倒进服务器用)。

    `deleted` (服务器侧墓碑、本地还留副本) **必须跳过**: 不带 base_version 的 publish 会
    清掉墓碑, 即"推送 = 静默复活被删资产"。要恢复请显式 `lclone evolution restore`。
    """
    res: Dict[str, List[dict]] = {"published": [], "unchanged": [], "failed": []}
    for s in backend_status(backend):
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

    def tombstones(self) -> set:
        return tombstones(self.conn)

    def content(self, name: str, version: Optional[int] = None) -> Optional[str]:
        row = resolve(self.conn, name, version)
        return None if row is None else row["content"]

    def publish(self, name: str, content: Optional[str] = None, *, kind: str = "",
                project_id: Optional[int] = None, message: str = "",
                source_ref: str = "", ref: str = "",
                base_version: Optional[int] = None) -> dict:
        return publish(self.conn, name, content, kind=kind, project_id=project_id,
                       ref=ref, message=message, source_ref=source_ref,
                       base_version=base_version)

    def delete(self, name: str, base_version: Optional[int] = None) -> dict:
        return delete(self.conn, name, base_version=base_version)

    def restore(self, name: str) -> dict:
        return restore(self.conn, name)

    def rename(self, name: str, new_name: str,
               base_version: Optional[int] = None, message: str = "") -> dict:
        return rename(self.conn, name, new_name,
                      base_version=base_version, message=message)

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

    def tombstones(self) -> set:
        """远端墓碑集合: 显式带 include_deleted 取 index, 再看 deleted_at。

        `/api/evolution/manifest` 按设计不含墓碑, 所以同步状态必须另问一次 —— 否则
        "远端已删除"与"远端从来没有"分不开, `publish --all` 会把删除复活。
        """
        items = self._req("GET", "/api/evolution/index?include_deleted=true").get("items", [])
        return {x.get("name") for x in items if x.get("name") and x.get("deleted_at")}

    def content(self, name: str, version: Optional[int] = None) -> Optional[str]:
        import urllib.parse
        q = {"name": name}
        if version is not None:
            q["version"] = str(version)
        body = self._req("GET", "/api/evolution/content?" + urllib.parse.urlencode(q))
        return body.get("content")

    def publish(self, name: str, content: Optional[str] = None, *, kind: str = "",
                project_id: Optional[int] = None, message: str = "",
                source_ref: str = "", ref: str = "",
                base_version: Optional[int] = None) -> dict:
        return self._req("POST", "/api/evolution/publish", {
            "name": name, "content": content, "kind": kind,
            "project_id": project_id, "message": message,
            "source_ref": source_ref, "ref": ref,
            "base_version": base_version,
        }).get("result", {})

    def delete(self, name: str, base_version: Optional[int] = None) -> dict:
        return self._req("POST", "/api/evolution/delete",
                         {"name": name, "base_version": base_version}).get("result", {})

    def restore(self, name: str) -> dict:
        return self._req("POST", "/api/evolution/restore",
                         {"name": name}).get("result", {})

    def rename(self, name: str, new_name: str,
               base_version: Optional[int] = None, message: str = "") -> dict:
        return self._req("POST", "/api/evolution/rename",
                         {"name": name, "new_name": new_name,
                          "base_version": base_version,
                          "message": message}).get("result", {})

    def history(self, name: str) -> List[dict]:
        import urllib.parse
        return self._req("GET", "/api/evolution/history?"
                         + urllib.parse.urlencode({"name": name})).get("items", [])

    def rollback(self, name: str, to_version: int) -> dict:
        return self._req("POST", "/api/evolution/rollback",
                         {"name": name, "version": to_version}).get("result", {})

    def find_project(self, ref: Optional[str] = None, repo_path: str = "",
                     repo_remote: str = "") -> Optional[int]:
        """把项目名/id、**本机 git remote** 或**本机仓库路径**解析成服务器的 project_id。

        远端大脑下服务端看不到客户端路径, 归属必须在客户端解析后随请求上报
        (与 DSH 插件的 resolveProject 同规则): 先按名字/id 命中, 再按归一化 remote,
        最后按 path 最长前缀 (无 remote 的仓库才用得上)。
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
        if repo_remote:
            from .projects import normalize_remote
            want = normalize_remote(repo_remote)
            if want:
                for p in items:
                    if p.get("remote") and normalize_remote(p["remote"]) == want:
                        return p.get("id")
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

    "已收录"必须**含墓碑名字**: 墓碑资产的本地副本可能仍在缓存目录里, 若把它当成
    未收录文件重新 publish, 就会经 `publish()` 的复活路径静默清掉墓碑 (删除被撤销)
    并追加一条同内容版本 —— 所以墓碑名字在这里也要跳过。
    """
    known = {row["name"] for row in ls(conn, include_deleted=True)}
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
