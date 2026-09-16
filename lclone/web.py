"""Web 面板: FastAPI + 单页 HTML。任何电脑浏览器打开即可访问大脑。

两个页面 (共享 CSS):
  /     记忆工作台: 层级树 + 卡片流; 拖拽卡片到左侧层级节点 = 上升/下降;
        右上角「+ 添加记忆」弹窗写入。所有记忆即 spec, 界面不做区分。
  /ask  问答页: 带记忆聊天 + 边界监督, 与记忆管理完全分开。
"""

from __future__ import annotations

import sqlite3
from typing import Optional

from . import chat as chat_mod
from . import config
from . import db as db_mod
from . import evolutions as evo_mod
from . import llm
from . import memory as mem_mod
from . import projects as proj_mod
from . import supervise as sup_mod
from . import auth
from . import mcp_server as mcp_srv

# 注意: 模型必须定义在模块级。若定义在 create_app 内部, 配合
# `from __future__ import annotations` 会产生未解析的 ForwardRef, 导致
# FastAPI 无法生成 schema、请求体会被误判为 query 参数。

from pydantic import BaseModel
from typing import Optional


class AskIn(BaseModel):
    question: str
    project_id: Optional[int] = None
    thread_id: Optional[str] = None
    k: int = 5
    with_specs: bool = True


class RememberIn(BaseModel):
    content: str
    level: str = "insight"
    project_id: Optional[int] = None
    reason: str = ""


class CaptureIn(BaseModel):
    text: str
    title: str = ""
    project_id: Optional[int] = None
    cwd: str = ""
    session_key: str = ""
    global_fallback: bool = False


class ReviewIn(BaseModel):
    id: int
    action: str = "keep"
    content: Optional[str] = None


class DemoteIn(BaseModel):
    project_id: int


class RecallIn(BaseModel):
    query: str
    project_id: Optional[int] = None
    k: int = 5


class SuperviseIn(BaseModel):
    proposal: str
    project_id: int


class ProjectIn(BaseModel):
    name: str
    path: str = ""
    charter: str = ""


class EvoPublishIn(BaseModel):
    name: str
    content: Optional[str] = None
    kind: str = ""
    project_id: Optional[int] = None
    message: str = ""
    ref: str = ""
    source_ref: str = ""
    base_version: Optional[int] = None
    only_if_new: bool = False


class EvoDeleteIn(BaseModel):
    name: str
    base_version: Optional[int] = None


class EvoRestoreIn(BaseModel):
    name: str


class EvoRenameIn(BaseModel):
    name: str
    new_name: str
    base_version: Optional[int] = None
    message: str = ""


class EvoRollbackIn(BaseModel):
    name: str
    version: int


# ================================================================ 冲突映射 / 可编辑性
def _evo_conflict(e: Exception):
    """领域异常 → HTTPException: 乐观锁/命名冲突一律 409, 其余 (ValueError) 400。

    **调用方必须窄捕获** (`VersionConflict`/`NameConflict`/`ValueError`): 其余异常
    (sqlite3 故障、未来改动引入的 TypeError 等) 是服务端故障, 应冒泡成 500,
    不得经由本函数伪装成"客户端请求有问题"的 400。
    """
    from fastapi import HTTPException
    if isinstance(e, evo_mod.VersionConflict):
        return HTTPException(409, {"error": str(e),
                                   "current_version": e.current_version,
                                   "deleted": getattr(e, "deleted", False)})
    if isinstance(e, evo_mod.NameConflict):
        return HTTPException(409, {"error": str(e), "name": e.name})
    return HTTPException(400, str(e))


def _editability_of(row: dict):
    """行 → (editable, editable_reason)。原因码仅 "", binary, too_large, ref, missing。

    必须走 `get_blob_bytes` 拿**原始字节**: `get_blob` 用 errors="replace" 解码,
    非法 UTF-8 会被替换成替换字符, 拿去判定会把二进制资产误判成可编辑。
    """
    if row.get("ref"):
        return False, "ref"
    raw = evo_mod.get_blob_bytes(row.get("hash") or "")
    if raw is None:
        return False, "missing"
    return evo_mod.editability(raw)


# ================================================================ FastAPI
def create_app(db_path: Optional[str] = None):
    from pathlib import Path
    from fastapi import Body, Depends, FastAPI, HTTPException
    from fastapi.responses import FileResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles
    from fastapi.middleware.cors import CORSMiddleware

    # 前后台分离: 前端可被插件(DSH)等其它源 serve, 直接跨域调本后端; 故开放 CORS。
    app = FastAPI(title="外置大脑", version="0.3.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
    )

    # 解析一次数据库路径 (未显式传参时取 config), 供初始化 / 请求 / 鉴权共用
    resolved_db = db_path or config.db_path()

    # 启动时确保 schema 存在; 每个请求使用独立连接 (FastAPI 同步接口跑在线线程池)
    db_mod.init(resolved_db)

    def get_db():
        # 每个请求只连库, 不重新执行 schema 初始化 (启动时已 init 一次)
        conn = db_mod.connect(resolved_db)
        try:
            yield conn
        finally:
            conn.close()

    # 鉴权中间件: 保护 /api/* 与 /mcp (env key 或库中受管 token)

    @app.middleware("http")
    async def auth_mw(request, call_next):
        return await auth.enforce(request, call_next, db_path=resolved_db)
    # 前端为独立静态资源 (lclone/frontend/), 由 FileResponse 服务; 后端不做内联 HTML。

    @app.post("/mcp")
    async def mcp_endpoint(body: dict = Body(...)):
        """MCP over HTTP: JSON-RPC 请求, 复用 mcp_server.handle_message 分发。"""
        resp = mcp_srv.handle_message(body)
        if resp is None:
            return JSONResponse(None, status_code=202)
        return JSONResponse(resp)

    # 前后台分离: 前端是独立静态资源 (lclone/frontend/), 后端只做 REST/MCP; 由文件服务。
    frontend = Path(__file__).resolve().parent / "frontend"

    @app.get("/")
    def index():
        return FileResponse(frontend / "index.html",
                            headers={"Cache-Control": "no-store"})

    @app.get("/ask")
    def ask_page():
        return FileResponse(frontend / "ask.html",
                            headers={"Cache-Control": "no-store"})

    @app.get("/api/health")
    def health(conn: sqlite3.Connection = Depends(get_db)):
        return {"ok": True, "backend": llm.backend(),
                "db": conn.execute("select sqlite_version()").fetchone()[0]}

    @app.get("/api/projects")
    def projects(conn: sqlite3.Connection = Depends(get_db)):
        return {"items": [dict(r) for r in proj_mod.list_projects(conn)]}

    @app.post("/api/projects")
    def add_project(body: ProjectIn, conn: sqlite3.Connection = Depends(get_db)):
        try:
            pid = proj_mod.add_project(conn, body.name, body.path, body.charter)
        except sqlite3.IntegrityError:
            raise HTTPException(400, "项目名已存在")
        return {"id": pid}

    @app.post("/api/projects/{pid}/sync")
    def sync_project(pid: int, conn: sqlite3.Connection = Depends(get_db)):
        try:
            return proj_mod.sync_project(conn, pid)
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.post("/api/projects/{pid}/remove")
    def remove_project(pid: int, conn: sqlite3.Connection = Depends(get_db)):
        """墓碑式移除项目: 项目从列表消失、记忆停止加载, 可恢复。"""
        try:
            proj_mod.remove_project(conn, pid)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"ok": True}

    @app.post("/api/projects/{pid}/restore")
    def restore_project(pid: int, conn: sqlite3.Connection = Depends(get_db)):
        """复活被移除的项目。"""
        try:
            proj_mod.restore_project(conn, pid)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"ok": True}

    @app.post("/api/remember")
    def remember(body: RememberIn, conn: sqlite3.Connection = Depends(get_db)):
        pid = body.project_id
        # Web 手动添加 = 用户当场显式确认 → decision 直接生效
        mid = mem_mod.remember(conn, body.content, level=body.level,
                               project_id=pid, reason=body.reason,
                               confirmed=True)
        return {"id": mid}

    @app.post("/api/capture")
    def capture(body: CaptureIn, conn: sqlite3.Connection = Depends(get_db)):
        pid = body.project_id
        if pid is None and body.cwd:
            status, pid = proj_mod.resolve_project(conn, cwd=body.cwd)
            if status == "no_git":
                if not body.global_fallback:
                    raise HTTPException(422, "未归属: 无 git 仓库")
                pid = None
        rep = mem_mod.capture_report(conn, body.text, project_id=pid, title=body.title,
                                     session_key=body.session_key or "")
        return rep

    @app.get("/api/bootstrap")
    def bootstrap(cwd: str = "", query: str = "", k: int = 5,
                  conn: sqlite3.Connection = Depends(get_db)):
        pid = None
        if cwd:
            status, pid = proj_mod.resolve_project(conn, cwd=cwd)
            if status == "no_git":
                pid = None
        text = mem_mod.bootstrap(conn, query=query, project_id=pid, k=k)
        return {"text": text}

    @app.get("/api/pending")
    def pending(conn: sqlite3.Connection = Depends(get_db)):
        return {"items": [dict(r) for r in mem_mod.pending_memories(conn)]}

    @app.get("/api/stats")
    def stats(days: int = 7, conn: sqlite3.Connection = Depends(get_db)):
        """准入质量指标 (队列精确率/复核负担/复用率)。

        内部相对指标: 只在准入改动前后对比时有效, 没有公开基准可作绝对标尺
        (见 docs/记忆准入门控调研.md §3)。无数据时字段为 null, 不是 0。
        """
        return mem_mod.queue_metrics(conn, days=days)

    @app.get("/api/memories")
    def memories(project_id: Optional[int] = None,
                 level: Optional[str] = None, status: str = "active",
                 limit: int = 20, layer: Optional[str] = None,
                 conn: sqlite3.Connection = Depends(get_db)):
        items = mem_mod.list_memories(conn, project_id=project_id, level=level,
                                      status=status, limit=limit, layer=layer)
        return {"items": [dict(r) for r in items]}

    @app.get("/api/evolutions")
    def evolutions(name: Optional[str] = None, include_deleted: bool = False,
                   conn: sqlite3.Connection = Depends(get_db)):
        """进化资产目录树 (含 content/size/mtime)。

        响应形状**保持不变** (前端零改动), 但底层已从"扫目录"换成"读版本索引 + blob":
        每个条目额外带 version/hash/kind/untracked, 便于看板展示版本与未收录文件。
        `include_deleted=True` 时把墓碑资产一并列出 (形状不变, 只是多几行)。
        """
        def add_content(node):
            if node.get("is_dir"):
                node["children"] = [add_content(c) for c in node.get("children", [])]
            else:
                node["content"] = mem_mod.read_evolution_file(node["name"], conn) or ""
            return node
        items = [add_content(f) for f in
                 mem_mod.list_evolution_files(conn, include_deleted=include_deleted)]
        return {"items": items}

    # ------------------------------------------------ 进化资产: 版本化存储 (服务器权威)
    @app.get("/api/evolution/index")
    def evo_index(include_deleted: bool = False,
                  conn: sqlite3.Connection = Depends(get_db)):
        """当前版本清单 (每个进化资产一行) + 服务器侧目录。

        `dirs` 是**服务器**的真实路径 —— 看板由服务器提供, 该显示服务器的库位置,
        而不是写死一个客户端相对路径。

        每项追加可编辑性判定 (`editable`/`editable_reason`) 与乐观锁所需的
        `base_version` (= 当前版本号, 供前端写操作回传)、墓碑字段 (`deleted_at`/
        `renamed_to`)。判定结果由服务端唯一权威下发, 前端只镜像。
        """
        items = []
        for row in evo_mod.ls(conn, include_deleted=include_deleted):
            row = dict(row)
            ok, reason = _editability_of(row)
            row["editable"] = ok
            row["editable_reason"] = reason
            row["base_version"] = row.get("version")
            # 反向引用: 谁在用这个资产 (纯追加字段, /api/evolutions 形状不受影响)
            _refs = mem_mod.insights_for_evolution(conn, row["name"])
            row["ref_count"] = len(_refs)
            row["refs"] = [{"id": r["id"], "project_id": r["project_id"],
                            "project_name": r["project_name"]} for r in _refs]
            row["deleted_at"] = row.get("deleted_at") or ""
            row["renamed_to"] = row.get("renamed_to") or ""
            items.append(row)
        return {"items": items,
                "dirs": {"content": str(evo_mod.blob_dir()),
                         "cache": str(evo_mod.cache_dir(create=False))}}

    @app.get("/api/evolution/manifest")
    def evo_manifest(conn: sqlite3.Connection = Depends(get_db)):
        """客户端同步清单: name → {version, hash, size, kind, project_id}。"""
        return {"items": evo_mod.manifest_index(conn)}

    @app.get("/api/evolution/content")
    def evo_content(name: str, version: Optional[int] = None,
                    conn: sqlite3.Connection = Depends(get_db)):
        """取某版本的原文 (version 省略取当前版本)。

        返回形状在既有 `name/version/hash/content/ref` 之上**追加** `editable`/
        `editable_reason`/`base_version`/`deleted_at`/`renamed_to`。
        `base_version` 恒为**当前版本号** (`current()` 的 version, 与请求的 version
        无关) —— 前端据此回传写操作做乐观锁; 读历史版本时改的仍是当前版本。
        """
        row = evo_mod.resolve(conn, name, version)
        if row is None:
            raise HTTPException(404, f"进化资产不存在: {name}")
        cur = evo_mod.current(conn, name) or {}
        ok, reason = _editability_of(row)
        return {"name": row["name"], "version": row["version"], "hash": row["hash"],
                "content": row["content"], "ref": row["ref"],
                "editable": ok, "editable_reason": reason,
                "base_version": cur.get("version"),
                "deleted_at": cur.get("deleted_at") or "",
                "renamed_to": cur.get("renamed_to") or ""}

    @app.get("/api/evolution/history")
    def evo_history(name: str, conn: sqlite3.Connection = Depends(get_db)):
        """版本历史 (新→旧)。"""
        return {"items": evo_mod.history(conn, name)}

    @app.post("/api/evolution/publish")
    def evo_publish(body: EvoPublishIn, conn: sqlite3.Connection = Depends(get_db)):
        """发布一版内容 (内容未变则不新增版本); ref 类只记引用。

        `base_version` 为乐观锁 (None = 不校验): 陈旧视图 → 409, **绝不静默覆盖**。
        `only_if_new` 为"新建"语义: 目标名已是活跃资产 → 409 (名字冲突, 不追加版本);
        墓碑名字不拒绝 (按既有的"重新激活"路径续用自身版本号)。
        """
        try:
            out = evo_mod.publish(conn, body.name, body.content, kind=body.kind,
                                     project_id=body.project_id, ref=body.ref,
                                     message=body.message, source_ref=body.source_ref,
                                     base_version=body.base_version,
                                     only_if_new=body.only_if_new)
        except (evo_mod.VersionConflict, evo_mod.NameConflict, ValueError) as e:
            # 窄捕获: 只把**领域异常**翻成 409/400。其余 (sqlite3.OperationalError
            # "database is locked"、未来的 TypeError/AttributeError 等) 是服务端故障,
            # 必须冒泡成 500 —— 否则真故障被报成"请求有问题", 且 5xx 永不进日志/指标。
            raise _evo_conflict(e)
        return {"result": out}

    @app.post("/api/evolution/delete")
    def evo_delete(body: EvoDeleteIn, conn: sqlite3.Connection = Depends(get_db)):
        """墓碑删除 (可恢复)。带 `base_version` 时对**已墓碑**资产同样判 409。

        该行为是刻意的: 带 base_version 的重复删除不是幂等 200 —— 调用方读到的是
        "当时还活着"的视图, 返回 200 会让它误以为删除是本次生效的 (lost update)。
        """
        try:
            out = evo_mod.delete(conn, body.name, base_version=body.base_version)
        except (evo_mod.VersionConflict, evo_mod.NameConflict, ValueError) as e:
            # 窄捕获: 只把**领域异常**翻成 409/400。其余 (sqlite3.OperationalError
            # "database is locked"、未来的 TypeError/AttributeError 等) 是服务端故障,
            # 必须冒泡成 500 —— 否则真故障被报成"请求有问题", 且 5xx 永不进日志/指标。
            raise _evo_conflict(e)
        return {"result": out}

    @app.post("/api/evolution/restore")
    def evo_restore(body: EvoRestoreIn, conn: sqlite3.Connection = Depends(get_db)):
        """恢复墓碑资产 (清 deleted_at / renamed_to), 幂等。"""
        try:
            out = evo_mod.restore(conn, body.name)
        except (evo_mod.VersionConflict, evo_mod.NameConflict, ValueError) as e:
            # 窄捕获: 只把**领域异常**翻成 409/400。其余 (sqlite3.OperationalError
            # "database is locked"、未来的 TypeError/AttributeError 等) 是服务端故障,
            # 必须冒泡成 500 —— 否则真故障被报成"请求有问题", 且 5xx 永不进日志/指标。
            raise _evo_conflict(e)
        return {"result": out}

    @app.post("/api/evolution/rename")
    def evo_rename(body: EvoRenameIn, conn: sqlite3.Connection = Depends(get_db)):
        """改名 = 新名字发 v1 (继承当前内容) + 旧名墓碑记 renamed_to; 历史不迁移。"""
        if not (body.new_name or "").strip():
            raise HTTPException(400, "new_name 不能为空")
        try:
            out = evo_mod.rename(conn, body.name, body.new_name,
                                 base_version=body.base_version, message=body.message)
        except (evo_mod.VersionConflict, evo_mod.NameConflict, ValueError) as e:
            # 窄捕获: 只把**领域异常**翻成 409/400。其余 (sqlite3.OperationalError
            # "database is locked"、未来的 TypeError/AttributeError 等) 是服务端故障,
            # 必须冒泡成 500 —— 否则真故障被报成"请求有问题", 且 5xx 永不进日志/指标。
            raise _evo_conflict(e)
        return {"result": out}

    @app.post("/api/evolution/rollback")
    def evo_rollback(body: EvoRollbackIn, conn: sqlite3.Connection = Depends(get_db)):
        """回滚当前指向到某个历史版本 (不改任何 blob)。"""
        try:
            out = evo_mod.rollback(conn, body.name, body.version)
        except ValueError as e:
            raise HTTPException(404, str(e))
        return {"result": out}

    @app.get("/api/links")
    def links(conn: sqlite3.Connection = Depends(get_db)):
        """记忆链接表 (架构图连线用)。"""
        rows = conn.execute(
            "SELECT source_id, target_id FROM memory_links ORDER BY id"
        ).fetchall()
        return {"items": [dict(r) for r in rows]}

    @app.post("/api/review")
    def review(body: ReviewIn, conn: sqlite3.Connection = Depends(get_db)):
        try:
            mem_mod.review(conn, body.id, body.action, new_content=body.content)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"ok": True}

    @app.post("/api/memories/{mid}/promote")
    def promote(mid: int, conn: sqlite3.Connection = Depends(get_db)):
        """上升: 项目记忆 -> 全局层。"""
        try:
            mem_mod.promote(conn, mid)
        except ValueError as e:
            raise HTTPException(404, str(e))
        return {"ok": True, "id": mid, "project_id": None}

    @app.post("/api/memories/{mid}/demote")
    def demote(mid: int, body: DemoteIn,
               conn: sqlite3.Connection = Depends(get_db)):
        """下降: 挂到指定项目。"""
        try:
            mem_mod.demote(conn, mid, body.project_id)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"ok": True, "id": mid, "project_id": body.project_id}

    @app.get("/api/suggest")
    def suggest(conn: sqlite3.Connection = Depends(get_db)):
        """删除提示: 算法扫描候选, 删除由用户决定。"""
        return {"items": mem_mod.suggest(conn)}

    @app.post("/api/organize")
    def organize(conn: sqlite3.Connection = Depends(get_db)):
        """整理: LLM 语义合并相近记忆 (不能跨项目/等级/模块)。"""
        return mem_mod.organize(conn)

    @app.post("/api/recall")
    def recall(body: RecallIn, conn: sqlite3.Connection = Depends(get_db)):
        items = mem_mod.recall(conn, body.query, k=body.k,
                               project_id=body.project_id)
        return {"items": items}

    @app.post("/api/supervise")
    def supervise(body: SuperviseIn, conn: sqlite3.Connection = Depends(get_db)):
        res = sup_mod.supervise(conn, body.proposal, project_id=body.project_id)
        if not res["ok"]:
            raise HTTPException(400, res["error"])
        return res

    @app.post("/api/ask")
    def ask(body: AskIn, conn: sqlite3.Connection = Depends(get_db)):
        try:
            res = chat_mod.ask(conn, body.question, project_id=body.project_id,
                               thread_id=body.thread_id, k=body.k,
                               with_specs=body.with_specs)
        except Exception as e:
            raise HTTPException(500, f"{type(e).__name__}: {e}")
        return res

    @app.get("/api/threads/{tid}/messages")
    def thread_messages(tid: str, conn: sqlite3.Connection = Depends(get_db)):
        rows = conn.execute(
            "SELECT role, content, created_at FROM messages"
            " WHERE thread_id=? ORDER BY id", (tid,)
        ).fetchall()
        return {"items": [dict(r) for r in rows]}

    return app


def run(host: Optional[str] = None, port: Optional[int] = None) -> None:
    import uvicorn
    app = create_app()
    uvicorn.run(app, host=host or config.get("BRAIN_HOST"),
                port=port or config.get_int("BRAIN_PORT", 8000))
