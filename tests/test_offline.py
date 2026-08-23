"""离线自测: 无需 API Key, 无需第三方依赖 (BRAIN_LLM=dummy)。

运行: python tests/test_offline.py
"""

import os
import pathlib
import sys
import tempfile

os.environ["BRAIN_LLM"] = "dummy"
os.environ.pop("OPENAI_API_KEY", None)

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lclone import chat as chat_mod
from lclone import cli
from lclone import db as db_mod
from lclone import memory as mem_mod
from lclone import projects as proj_mod
from lclone import supervise as sup_mod

fails = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""))
    if not cond:
        fails.append(name)


tmp = tempfile.mkdtemp(prefix="brain_test_")
dbp = os.path.join(tmp, "t.db")
demo_root = ROOT / "examples" / "demo_project"

conn = db_mod.init(dbp)
check("1 schema init", True)

# ---- 竖向分层: 项目注册 + spec 格式无关索引 ----
pid = proj_mod.add_project(
    conn, "demo", str(demo_root), "示例项目: 验证外置大脑的竖向分层"
)
check("2 项目注册", pid == 1)

res = proj_mod.sync_project(conn, pid)
check("3 spec 索引发现文件", res["added"] >= 2, str(res))
fmts = {r["format"] for r in conn.execute("SELECT format FROM specs_index")}
check("4 格式识别 (openspec/adr)", "adr" in fmts and "openspec" in fmts, str(fmts))
readme_idx = conn.execute(
    "SELECT COUNT(*) c FROM specs_index WHERE rel_path LIKE '%README%'"
).fetchone()["c"]
check("5 普通 README 不入索引", readme_idx == 0, f"readme 索引数={readme_idx}")

# ---- C 主动触发: 直接生效 ----
mid = mem_mod.remember(
    conn,
    "后端使用 FastAPI, 数据库用 SQLite, 边界: 单用户部署",
    level="decision", project_id=pid,
)
row = conn.execute(
    "SELECT status, source_type FROM memories WHERE id=?", (mid,)
).fetchone()
check("6 主动记忆立即生效", row["status"] == "active" and row["source_type"] == "manual")

# ---- B 自动捕获: 进草稿待确认 ----
ids = mem_mod.capture(
    conn,
    "讨论后确定: 6月1日上线; 放弃微服务改用单体; 部署用 Docker Compose",
    project_id=pid, title="方案讨论",
)
check("7 自动捕获生成草稿", len(ids) >= 1, str(ids))
row = conn.execute("SELECT status FROM memories WHERE id=?", (ids[0],)).fetchone()
check("8 草稿状态 pending", row["status"] == "pending")
pend = mem_mod.pending_memories(conn)
check("9 待确认列表", len(pend) >= 1, f"{len(pend)} 条")
mem_mod.review(conn, ids[0], "keep")
row = conn.execute(
    "SELECT status, confirmed_at FROM memories WHERE id=?", (ids[0],)
).fetchone()
check("10 确认后生效", row["status"] == "active" and row["confirmed_at"] is not None)

# ---- 回顾环 ----
items = mem_mod.recall(conn, "FastAPI 数据库", project_id=pid)
check("11 回顾检索命中", len(items) >= 1,
      str([i["content"][:18] for i in items]))
check("12 召回限定项目", all(i["project_id"] == pid for i in items))

# ---- 规范环 ----
res = sup_mod.supervise(conn, "把数据库换成 PostgreSQL", project_id=pid)
check("13 边界监督出报告", res["ok"] and len(res["report"]) > 5, res["report"][:40])

# ---- 回顾环问答 ----
res = chat_mod.ask(conn, "我们这个项目昨天定了什么?", project_id=pid)
check("14 问答有回复", len(res["answer"]) > 0)
check("15 线程 id", len(res["thread_id"]) == 32)

# ---- 个人区 (project_id=NULL) ----
mem_mod.remember(conn, "我的原则: 先跑通再优化", level="note")
items_p = mem_mod.recall(conn, "跑通")
check("16 个人区召回", len(items_p) >= 1,
      str([i["content"][:10] for i in items_p]))

# ---- 列出记忆 ----
rows = mem_mod.list_memories(conn, status="active")
check("17 列出正式记忆", len(rows) >= 3, f"{len(rows)} 条")
rows_p = mem_mod.list_memories(conn, project_id=pid, level="decision",
                               status="active")
check("18 按项目/等级过滤",
      len(rows_p) >= 1 and all(r["level"] == "decision" for r in rows_p))
pend_rows = mem_mod.list_memories(conn, status="pending")
check("19 草稿也能列出", all(r["status"] == "pending" for r in pend_rows))

# ---- CLI 冒烟 ----
import contextlib
import io
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    cli.main(["init", "--db", dbp])
check("20 CLI init", "数据库已初始化" in buf.getvalue())

buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    cli.main(["proj", "list", "--db", dbp])
check("21 CLI proj list", "demo" in buf.getvalue())

buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    cli.main(["recall", "FastAPI", "--db", dbp])
check("22 CLI recall", "FastAPI" in buf.getvalue())

buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    cli.main(["memories", "--db", dbp, "--limit", "5"])
check("23 CLI memories", "FastAPI" in buf.getvalue())

# ---- Web 冒烟 (fastapi 可选) ----
try:
    from lclone.web import create_app
    app = create_app(dbp)
    routes = {r.path for r in app.routes}
    check("24 Web 路由", "/api/ask" in routes and "/api/supervise" in routes
          and "/api/memories" in routes)
except ImportError:
    print("SKIP 24 Web (fastapi 未安装, 装依赖后自动启用)")

print()
if fails:
    print("FAILED:", fails)
    sys.exit(1)
print("ALL OFFLINE TESTS PASSED")
