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

# ---- B 自动捕获: 记录直接生效, 决策进草稿待确认 ----
ids_note = mem_mod.capture(conn, "一条过程性记录, 无需确认", project_id=pid)
row = conn.execute("SELECT status FROM memories WHERE id=?",
                   (ids_note[0],)).fetchone()
check("7 capture note 直接 active", row["status"] == "active", str(row["status"]))

# 模拟分类器返回 decision → 应进 pending 待确认
import lclone.llm as llm_mod
_orig_extract = llm_mod.extract_memories
llm_mod.extract_memories = lambda t: [{"level": "decision",
                                       "content": "确定 6月1日上线", "confidence": 0.9}]
ids_dec = mem_mod.capture(conn, "确定 6月1日上线", project_id=pid, title="方案讨论")
llm_mod.extract_memories = _orig_extract
row = conn.execute("SELECT status FROM memories WHERE id=?",
                   (ids_dec[0],)).fetchone()
check("8 capture decision 进 pending", row["status"] == "pending", str(row["status"]))
pend = mem_mod.pending_memories(conn)
check("9 待确认列表", len(pend) >= 1, f"{len(pend)} 条")
mem_mod.review(conn, ids_dec[0], "keep")
row = conn.execute(
    "SELECT status, confirmed_at FROM memories WHERE id=?", (ids_dec[0],)
).fetchone()
check("10 决策确认后生效", row["status"] == "active" and row["confirmed_at"] is not None)

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

# ---- 上升 / 下降 (生命周期) ----
m_up = mem_mod.remember(conn, "项目A独有的决策: 上线后立即灰度", level="decision",
                        project_id=pid)
mem_mod.promote(conn, m_up)
row = conn.execute("SELECT project_id FROM memories WHERE id=?",
                   (m_up,)).fetchone()
check("25 promote 升到全局层", row["project_id"] is None)
items_g = mem_mod.recall(conn, "灰度上线", follow_links=False)
check("26 上升后全局可召回", any(i["id"] == m_up for i in items_g),
      str([i["id"] for i in items_g]))

pid2 = proj_mod.add_project(conn, "projB", str(demo_root), "第二个项目")
mem_mod.demote(conn, m_up, pid2)
row = conn.execute("SELECT project_id FROM memories WHERE id=?",
                   (m_up,)).fetchone()
check("27 demote 降到项目B", row["project_id"] == pid2)
items_b = mem_mod.recall(conn, "灰度", project_id=pid2, follow_links=False)
check("28 下降后项目B可召回", any(i["id"] == m_up for i in items_b))
mem_mod.demote(conn, m_up, pid)  # 项目 B -> 项目 A (横向搬移)
row = conn.execute("SELECT project_id FROM memories WHERE id=?",
                   (m_up,)).fetchone()
check("29 demote 支持项目间横搬", row["project_id"] == pid)

try:
    mem_mod.demote(conn, m_up, 9999)
    check("30 demote 目标项目不存在报错", False)
except ValueError:
    check("30 demote 目标项目不存在报错", True)

# ---- 记忆链接 [[m:N]] ----
m_global = mem_mod.remember(conn, "健身打卡: 每周三晚跑步", level="note")
m_link = mem_mod.remember(conn, f"链接测试内容 见 [[m:{m_global}]]",
                          level="note", project_id=pid)
links = conn.execute(
    "SELECT target_id FROM memory_links WHERE source_id=?", (m_link,)
).fetchall()
check("31 链接写入 memory_links",
      any(r["target_id"] == m_global for r in links), str(links))
items_l = mem_mod.recall(conn, "链接测试内容", project_id=pid, k=5,
                         follow_links=True)
check("32 召回自动跟随链接",
      any(i.get("via_link") and i["id"] == m_global for i in items_l),
      str([(i["id"], i.get("via_link")) for i in items_l]))
items_nf = mem_mod.recall(conn, "链接测试内容", project_id=pid, k=5,
                          follow_links=False)
check("33 --no-follow 不跟随链接",
      all(i["id"] != m_global for i in items_nf),
      str([i["id"] for i in items_nf]))

# ---- 删除提示 suggest ----
dup_a = mem_mod.remember(conn, "完全相同的重复内容样本", level="note")
dup_b = mem_mod.remember(conn, "完全相同的重复内容样本", level="note")
# note 现在直接 active, 造一条 pending 决策草稿来测"长期未确认"
_orig_extract2 = llm_mod.extract_memories
llm_mod.extract_memories = lambda t: [{"level": "decision",
                                       "content": "一个从未确认的旧草稿", "confidence": 0.9}]
mem_mod.capture(conn, "一个从未确认的旧草稿", project_id=pid)
llm_mod.extract_memories = _orig_extract2
stale = conn.execute("SELECT MAX(id) mid FROM memories WHERE status='pending'"
                     ).fetchone()["mid"]
conn.execute("UPDATE memories SET created_at=datetime('now','-30 days')"
             " WHERE id=?", (stale,))
conn.commit()
unused = mem_mod.remember(conn, "从未被召回过的新记忆", level="note")
sug = mem_mod.suggest(conn, stale_days=7, unused_days=30)
sug_ids = {s["id"] for s in sug}
check("34 suggest 发现重复", dup_a in sug_ids and dup_b in sug_ids,
      str(sorted(sug_ids)))
check("35 suggest 发现长期未确认草稿", stale in sug_ids)
check("36 suggest 发现长期未召回", unused in sug_ids)
check("37 suggest 每条都带删除命令",
      all(s["hint"].startswith("lclone review --id") for s in sug))

# ---- 项目墓碑: 移除后不再加载, 可 restore ----
mem_mod.remember(conn, "projB 的独有记忆: B计划细节", level="decision",
                 project_id=pid2)
proj_mod.remove_project(conn, pid2)
check("38 移除后项目从列表消失",
      all(r["id"] != pid2 for r in proj_mod.list_projects(conn)))
items_after = mem_mod.recall(conn, "B计划", follow_links=False)
check("39 移除后记忆停止加载",
      all(i["project_id"] != pid2 for i in items_after))
sug2 = mem_mod.suggest(conn)
check("40 suggest 提示已移除项目记忆",
      any("已移除" in s["reason"] for s in sug2),
      str([s["reason"] for s in sug2]))
proj_mod.restore_project(conn, pid2)
check("41 restore 复活后列表恢复",
      any(r["id"] == pid2 for r in proj_mod.list_projects(conn)))
items_back = mem_mod.recall(conn, "B计划", follow_links=False)
check("42 restore 后记忆恢复加载",
      any(i["project_id"] == pid2 for i in items_back))

# ---- 新命令 CLI 冒烟 ----
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    cli.main(["promote", str(m_up), "--db", dbp])
check("43 CLI promote", "上升至全局层" in buf.getvalue())

buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    cli.main(["demote", str(m_up), "--project", str(pid), "--db", dbp])
check("44 CLI demote", "下降至项目" in buf.getvalue())

buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    cli.main(["suggest", "--db", dbp, "--stale-days", "7"])
check("45 CLI suggest", "建议清理" in buf.getvalue())

buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    cli.main(["proj", "rm", "projB", "--db", dbp])
check("46 CLI proj rm 墓碑提示", "不再加载" in buf.getvalue())
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    cli.main(["proj", "restore", "projB", "--db", dbp])
check("47 CLI proj restore", "复活" in buf.getvalue())

# ---- 删除回归: FTS 触发器修复 (删除记忆不报 SQL logic error) ----
del_target = mem_mod.remember(conn, "待删除的回归测试记忆", level="note")
mem_mod.review(conn, del_target, "delete")
check("48 删除记忆成功 (FTS 触发器修复)",
      conn.execute("SELECT COUNT(*) c FROM memories WHERE id=?",
                   (del_target,)).fetchone()["c"] == 0)
check("49 删除后 FTS 同步清理",
      conn.execute("SELECT COUNT(*) c FROM memories_fts WHERE rowid=?",
                   (del_target,)).fetchone()["c"] == 0)

# ---- 等级收窄: 只留 decision/note + 分类器补 note 写路径 ----
from lclone import llm as llm_mod
check("50 LEVELS 不含 milestone",
      "milestone" not in mem_mod.LEVELS, str(mem_mod.LEVELS))
check("51 LEVELS 只含 decision/note",
      set(mem_mod.LEVELS) == {"note", "decision"}, str(mem_mod.LEVELS))
mem_items = llm_mod.extract_memories("确定用 SQLite; 顺带记下: 明天补测试")
check("52 extract_memories 返回结构化条目",
      isinstance(mem_items, list) and mem_items
      and all("level" in m and "content" in m for m in mem_items), str(mem_items))
check("53 dummy 后端分类为 note",
      mem_items and mem_items[0]["level"] == "note", str(mem_items))
cap_ids = mem_mod.capture(conn, "一条值得记的过程性事实", project_id=pid)
cap_levels = [conn.execute("SELECT level FROM memories WHERE id=?",
                           (i,)).fetchone()["level"] for i in cap_ids]
check("54 capture 产出 note 草稿", "note" in cap_levels, str(cap_levels))

# ---- bootstrap 会话引导 (CLI + 共享函数) ----
bs = mem_mod.bootstrap(conn, query="数据库", project_id=pid, k=3)
check("55 bootstrap 含项目方向", "示例项目" in bs, bs[:60])
check("56 bootstrap 无条件注入全局记忆", "先跑通再优化" in bs, bs[:120])
check("57 bootstrap 返回非空", bool(bs.strip()), "")
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    cli.main(["bootstrap", "数据库", "--project", str(pid), "--db", dbp])
check("58 CLI bootstrap 输出", "示例项目" in buf.getvalue(), buf.getvalue()[:80])

# ---- 接入向导 + 自检 (presets / install / doctor) ----
from lclone import presets, doctor, install as install_mod
check("59 deepseek 预设 embedding 走本地",
      presets.env_for("deepseek")["BRAIN_EMBED_BACKEND"] == "local")
check("60 openai 预设 embedding 走 api",
      presets.env_for("openai")["BRAIN_EMBED_BACKEND"] == "api")
check("61 provider 反推",
      presets.recognize_provider("https://api.deepseek.com/v1", "api") == "deepseek")
check("62 dummy 反推", presets.recognize_provider("", "dummy") == "dummy")
tmp_home = pathlib.Path(tempfile.mkdtemp(prefix="brain_home_"))
res = install_mod.install_skill(tmp_home)
check("63 install_skill 装到临时家目录",
      "已安装" in res and (tmp_home / ".agents/skills/lclone-memory/SKILL.md").exists())
items = doctor.check_all(home=tmp_home)
names = {i["name"] for i in items}
check("64 doctor 返回清单", "skill 已装" in names and "配置 .env" in names)
skill_ok = next(i for i in items if i["name"] == "skill 已装")
check("65 doctor 识别 skill 已装", skill_ok["ok"] is True)

# ---- 服务化: MCP 分发 + 鉴权 ----
from lclone import mcp_server as mcp_srv, auth as auth_mod
resp = mcp_srv.handle_message({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
check("66 MCP tools/list", bool(resp["result"]["tools"]) and resp["id"] == 1)
resp = mcp_srv.handle_message({"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {}})
check("67 MCP initialize", resp["result"]["serverInfo"]["name"] == "lclone")
resp = mcp_srv.handle_message({"jsonrpc": "2.0", "id": 3, "method": "ping"})
check("68 MCP ping", resp["result"] == {})
resp = mcp_srv.handle_message({"jsonrpc": "2.0", "id": 4, "method": "nope"})
check("69 MCP 未知方法报错", resp["error"]["code"] == -32601)

os.environ["LCLONE_API_KEY"] = "testkey"
check("70 鉴权: 无 key 拒绝", auth_mod.check({}) is False)
check("71 鉴权: Bearer 通过", auth_mod.check({"authorization": "Bearer testkey"}) is True)
check("72 鉴权: X-API-Key 通过", auth_mod.check({"x-api-key": "testkey"}) is True)
check("73 鉴权: 错 key 拒绝", auth_mod.check({"authorization": "Bearer wrong"}) is False)
os.environ.pop("LCLONE_API_KEY", None)
check("74 鉴权: 未设 key 恒通过", auth_mod.check({}) is True)

# ---- 在线备份 ----
bpath = db_mod.backup(db_path=dbp, dest_dir=os.path.join(tmp, "bak"))
check("75 backup 生成快照", os.path.exists(bpath) and bpath.endswith(".db"))

# ---- 记录聚合: 同一 session_key 只一条 note, 逐轮追加 ----
c1 = mem_mod.capture(conn, "聚合测试事实A", project_id=pid, session_key="agg1")
c2 = mem_mod.capture(conn, "聚合测试事实B", project_id=pid, session_key="agg1")
check("76 同 session 追加到同一 note", bool(c1) and bool(c2) and c1[0] == c2[0],
      f"{c1} vs {c2}")
note = conn.execute("SELECT content FROM memories WHERE id=?", (c1[0],)).fetchone()
check("77 note 内容累计", "事实A" in note["content"] and "事实B" in note["content"],
      note["content"][:60])
c3 = mem_mod.capture(conn, "聚合测试事实C", project_id=pid, session_key="agg2")
check("78 新 session_key 新 note", bool(c3) and c3[0] != c1[0], f"{c3} vs {c1}")

# ---- note 滚动压缩: 超长时摘要 ----
summ = llm_mod.summarize("长" * 500, max_chars=100)
check("79 summarize 截断到上限", len(summ) == 100, str(len(summ)))
_orig_sum = llm_mod.summarize
llm_mod.summarize = lambda t, max_chars=400: "压缩摘要"
c4 = mem_mod.capture(conn, "压缩事实D", project_id=pid, session_key="agg3",
                     note_compact_threshold=5)
c5 = mem_mod.capture(conn, "压缩事实E", project_id=pid, session_key="agg3",
                     note_compact_threshold=5)
llm_mod.summarize = _orig_sum
note3 = conn.execute("SELECT content FROM memories WHERE id=?", (c4[0],)).fetchone()
check("80 超长 note 触发压缩", note3["content"] == "压缩摘要", note3["content"])

# ---- Web 冒烟 (fastapi 可选) ----
try:
    from lclone.web import create_app
    app = create_app(dbp)
    routes = {r.path for r in app.routes}
    check("24 Web 路由", "/api/ask" in routes and "/api/supervise" in routes
          and "/api/memories" in routes and "/mcp" in routes)
except ImportError:
    print("SKIP 24 Web (fastapi 未安装, 装依赖后自动启用)")

print()
if fails:
    print("FAILED:", fails)
    sys.exit(1)
print("ALL OFFLINE TESTS PASSED")
