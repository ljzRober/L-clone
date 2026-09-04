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

    # 启动时确保 schema 存在; 每个请求使用独立连接 (FastAPI 同步接口跑在线线程池)
    db_mod.init(db_path)

    def get_db():
        # 每个请求只连库, 不重新执行 schema 初始化 (启动时已 init 一次)
        conn = db_mod.connect(db_path)
        try:
            yield conn
        finally:
            conn.close()

    # 鉴权中间件: 设了 LCLONE_API_KEY 时保护 /api/* 与 /mcp

    @app.middleware("http")
    async def auth_mw(request, call_next):
        return await auth.enforce(request, call_next)
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
        ids = mem_mod.capture(conn, body.text, project_id=pid, title=body.title,
                              session_key=body.session_key or "")
        return {"ids": ids}

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

    @app.get("/api/memories")
    def memories(project_id: Optional[int] = None,
                 level: Optional[str] = None, status: str = "active",
                 limit: int = 20, layer: Optional[str] = None,
                 conn: sqlite3.Connection = Depends(get_db)):
        items = mem_mod.list_memories(conn, project_id=project_id, level=level,
                                      status=status, limit=limit, layer=layer)
        return {"items": [dict(r) for r in items]}

    @app.get("/api/evolutions")
    def evolutions(name: Optional[str] = None):
        """进化资产 (文件式): 返回 ~/.lclone/evolutions/ 的文件目录树 (含 content/size/mtime)。"""
        def add_content(node):
            if node.get("is_dir"):
                node["children"] = [add_content(c) for c in node.get("children", [])]
            else:
                node["content"] = mem_mod.read_evolution_file(node["name"]) or ""
            return node
        items = [add_content(f) for f in mem_mod.list_evolution_files()]
        return {"items": items}

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
