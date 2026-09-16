"""离线自测: 无需 API Key, 无需第三方依赖 (BRAIN_LLM=dummy)。

运行: python tests/test_offline.py
"""

import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request

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
os.environ["LCLONE_EVO_DIR"] = os.path.join(tmp, "evo")  # 本地物化缓存目录 (指向临时目录)
os.environ["LCLONE_EVO_BLOB_DIR"] = os.path.join(tmp, "blobs")  # 内容寻址库 (临时)
# 离线测试必须确定性地走本地 DB —— 开发机的 shell 可能 export 了远端大脑地址
os.environ.pop("LCLONE_WEB_URL", None)
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

# ---- C 主动触发: decision 默认待确认, confirmed=True 直接生效 ----
mid = mem_mod.remember(
    conn,
    "后端使用 FastAPI, 数据库用 SQLite, 边界: 单用户部署",
    level="insight", project_id=pid, confirmed=True,
)
row = conn.execute(
    "SELECT status, source_type FROM memories WHERE id=?", (mid,)
).fetchone()
check("6 主动记忆 confirmed 直接生效", row["status"] == "active" and row["source_type"] == "manual")

# ---- B 自动捕获: 只产出 insight, 进草稿待确认 (note 通道已废弃) ----
ids_cap = mem_mod.capture(conn, "一条过程性记录, 无需确认", project_id=pid)
row = conn.execute("SELECT level, status FROM memories WHERE id=?",
                   (ids_cap[0],)).fetchone()
check("7 capture 只产出 insight(待确认)",
      row["level"] == "insight" and row["status"] == "pending", str(dict(row)))

# 模拟分类器返回 decision → 应进 pending 待确认
import lclone.llm as llm_mod
_orig_extract = llm_mod.extract_memories
llm_mod.extract_memories = lambda t, existing_modules=None: [{"level": "insight",
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
check("10 洞察确认后生效", row["status"] == "active" and row["confirmed_at"] is not None)

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
mem_mod.remember(conn, "我的原则: 先跑通再优化", level="insight", confirmed=True)
items_p = mem_mod.recall(conn, "跑通")
check("16 个人区召回", len(items_p) >= 1,
      str([i["content"][:10] for i in items_p]))

# ---- 列出记忆 ----
rows = mem_mod.list_memories(conn, status="active")
check("17 列出正式记忆", len(rows) >= 3, f"{len(rows)} 条")
rows_p = mem_mod.list_memories(conn, project_id=pid, level="insight",
                               status="active")
check("18 按项目/等级过滤",
      len(rows_p) >= 1 and all(r["level"] == "insight" for r in rows_p))
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
m_up = mem_mod.remember(conn, "项目A独有的洞察: 上线后立即灰度", level="insight",
                        project_id=pid, confirmed=True)
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
m_global = mem_mod.remember(conn, "健身打卡: 每周三晚跑步", level="insight", confirmed=True)
m_link = mem_mod.remember(conn, f"链接测试内容 见 [[m:{m_global}]]",
                          level="insight", confirmed=True, project_id=pid)
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
dup_a = mem_mod.remember(conn, "完全相同的重复内容样本", level="insight", confirmed=True)
dup_b = mem_mod.remember(conn, "完全相同的重复内容样本", level="insight", confirmed=True)
# note 现在直接 active, 造一条 pending 洞察草稿来测"长期未确认"
_orig_extract2 = llm_mod.extract_memories
llm_mod.extract_memories = lambda t, existing_modules=None: [{"level": "insight",
                                                               "content": "决定：一个从未确认的旧草稿", "confidence": 0.9}]
mem_mod.capture(conn, "决定了要保留这个从未确认的旧草稿", project_id=pid)
llm_mod.extract_memories = _orig_extract2
stale = conn.execute("SELECT MAX(id) mid FROM memories WHERE status='pending'"
                     ).fetchone()["mid"]
conn.execute("UPDATE memories SET created_at=datetime('now','-30 days')"
             " WHERE id=?", (stale,))
conn.commit()
unused = mem_mod.remember(conn, "从未被召回过的新记忆", level="insight", confirmed=True)
sug = mem_mod.suggest(conn, stale_days=7, unused_days=30)
sug_ids = {s["id"] for s in sug}
check("34 suggest 发现重复", dup_a in sug_ids and dup_b in sug_ids,
      str(sorted(sug_ids)))
check("35 suggest 发现长期未确认草稿", stale in sug_ids)
check("36 suggest 发现长期未召回", unused in sug_ids)
check("37 suggest 每条都带删除命令",
      all(s["hint"].startswith("lclone review --id") for s in sug))

# ---- 项目墓碑: 移除后不再加载, 可 restore ----
mem_mod.remember(conn, "projB 的独有记忆: B计划细节", level="insight",
                 project_id=pid2, confirmed=True)
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
del_target = mem_mod.remember(conn, "待删除的回归测试记忆", level="insight", confirmed=True)
mem_mod.review(conn, del_target, "delete")
check("48 删除记忆成功 (FTS 触发器修复)",
      conn.execute("SELECT COUNT(*) c FROM memories WHERE id=?",
                   (del_target,)).fetchone()["c"] == 0)
check("49 删除后 FTS 同步清理",
      conn.execute("SELECT COUNT(*) c FROM memories_fts WHERE rowid=?",
                   (del_target,)).fetchone()["c"] == 0)

# ---- 等级收窄: 只留 insight; 分类器只产出 insight (note 通道废弃) ----
from lclone import llm as llm_mod
check("50 LEVELS 不含 milestone",
      "milestone" not in mem_mod.LEVELS, str(mem_mod.LEVELS))
check("51 LEVELS 只含 insight",
      set(mem_mod.LEVELS) == {"insight"}, str(mem_mod.LEVELS))
mem_items = llm_mod.extract_memories("确定用 SQLite; 顺带记下: 明天补测试")
check("52 extract_memories 返回结构化条目",
      isinstance(mem_items, list) and mem_items
      and all("level" in m and "content" in m for m in mem_items), str(mem_items))
check("53 dummy 后端分类为 insight",
      mem_items and mem_items[0]["level"] == "insight", str(mem_items))
cap_ids = mem_mod.capture(conn, "确定了一条值得记的过程性事实", project_id=pid)
cap_levels = [conn.execute("SELECT level FROM memories WHERE id=?",
                           (i,)).fetchone()["level"] for i in cap_ids]
check("54 capture 只产出 insight", "insight" in cap_levels and "note" not in cap_levels,
      str(cap_levels))

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
check("62b claude 预设 embedding 走本地",
      presets.env_for("claude")["BRAIN_EMBED_BACKEND"] == "local")
check("62c gemini 预设存在",
      presets.env_for("gemini")["BRAIN_BASE_URL"].startswith("https://generativelanguage"))
check("62d copilot 预设存在",
      presets.env_for("copilot")["BRAIN_CHAT_MODEL"] == "gpt-4o-mini")
check("62e kimi 预设 embedding 走本地",
      presets.env_for("kimi")["BRAIN_EMBED_BACKEND"] == "local")
check("62f minimax 预设存在",
      presets.env_for("minimax")["BRAIN_BASE_URL"].startswith("https://api.minimaxi.com"))
tmp_home = pathlib.Path(tempfile.mkdtemp(prefix="brain_home_"))
res = install_mod.install_skill(tmp_home)
check("63 install_skill 装到临时家目录",
      "已安装" in res and (tmp_home / ".agents/skills/lclone-memory/SKILL.md").exists())
items = doctor.check_all(home=tmp_home)
names = {i["name"] for i in items}
check("64 doctor 返回清单", "skill 已装" in names and "配置 .env" in names)
skill_ok = next(i for i in items if i["name"] == "skill 已装")
check("65 doctor 识别 skill 已装", skill_ok["ok"] is True)
backend_items = doctor.check_backend(db_path=dbp)
check("65b backend 自检不含前端项",
      all(i["name"] not in ("skill 已装", "DSH 插件", "Claude Code hooks")
          for i in backend_items))
integ_items = doctor.check_integration(home=tmp_home)
check("65c integration 自检含 skill",
      "skill 已装" in {i["name"] for i in integ_items})

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

# ---- evolution 进化资产: 服务器版本库 + 本地只读缓存 (~/.lclone/evolution/), [[evo:name.ext]] 指向 ----
ev = mem_mod.create_evolution(
    conn, name="build-spec-map", kind="script",
    content="bash <sp-spec>/scripts/build-spec-map.sh --repo-root \"$PWD\"",
    reason="构建 L1 spec 地图, 常驻会话作索引", project_id=pid)
_evonames = {e["name"] for e in mem_mod.list_evolution_files()}
check("76 create_evolution 写入文件", ev == "build-spec-map.sh" and "build-spec-map.sh" in _evonames,
      f"{ev} {sorted(_evonames)}")
# insight → evolution 链接 = insight 内容里的 [[evo:文件名]]
_ins = mem_mod.remember(conn, "L1 地图用脚本构建, 避免全量读 spec 撑爆上下文 [[evo:build-spec-map.sh]]",
                        level="insight", project_id=pid, confirmed=True)
_ins_update = _ins  # remember 已确认 -> active
evos = mem_mod.evolutions_for_insight(conn, _ins)
check("77 insight→evolution 链接(经 [[evo:...]])", any(e["name"] == ev for e in evos),
      str([e["name"] for e in evos]))
ins = mem_mod.insights_for_evolution(conn, ev)
check("78 evolution 反向取 insight", any(i["id"] == _ins for i in ins),
      str([i["id"] for i in ins]))
# 复写文件 (改脚本)
mem_mod.update_evolution(conn, ev, content="bash build-spec-map.sh --repo-root .")
evc = mem_mod.read_evolution_file(ev)
check("79 update_evolution 同步(改脚本)", evc and "build-spec-map.sh --repo-root ." in evc, evc[:40])
ev2 = mem_mod.create_evolution(conn, name="gen-tool", kind="tool", content="通用小工具",
                               project_id=None)
check("79b 项目无关 evolution content 存文件", ev2 == "gen-tool.py"
      and mem_mod.read_evolution_file(ev2) == "通用小工具", ev2)

# ---- 归属判定代码强制 (git 自动注册 / fail-closed) ----
st, pid_l = proj_mod.resolve_project(conn, cwd=str(ROOT))
check("81 git 检测到未注册仓库自动注册", st == "created" and pid_l is not None)
st2, pid_l2 = proj_mod.resolve_project(conn, cwd=str(ROOT))
check("82 再次解析命中已注册 (matched)", st2 == "matched" and pid_l2 == pid_l)
no_git_dir = os.path.join(tmp, "plain_dir")
os.makedirs(no_git_dir, exist_ok=True)
st3, pid_none = proj_mod.resolve_project(conn, cwd=no_git_dir)
check("83 无 git 返回 no_git 且不落库", st3 == "no_git" and pid_none is None)

# ---- remember(decision) 默认 pending (洞察强确认) ----
_mid = mem_mod.remember(conn, "一个默认待确认的洞察", level="insight", project_id=pid)
check("84 remember decision 默认 pending",
      conn.execute("SELECT status FROM memories WHERE id=?",
                   (_mid,)).fetchone()["status"] == "pending")

# ---- module 轴已移除: 无 modules 表, capture 不写 module 列 ----
_tbl = conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table' AND name='modules'"
).fetchone()
check("85 module 轴已删除 (无 modules 表)", _tbl is None)
_orig3 = llm_mod.extract_memories
llm_mod.extract_memories = lambda t: [
    {"level": "note", "content": "一条过程性记录内容"},
    {"level": "insight", "content": "决定了归属方案"},
]
ids_mod = mem_mod.capture(conn, "确定了模块轴的归属口径", project_id=pid, session_key="modtest")
llm_mod.extract_memories = _orig3
rows_mod = {r["level"] for r in conn.execute(
    "SELECT level FROM memories WHERE id IN (%s)"
    % ",".join("?" * len(ids_mod)), ids_mod)}
check("86 capture 只产出 insight (note 被过滤)", rows_mod == {"insight"}, f"{rows_mod}")
conn.commit()

# ---- 记忆准入条件 (代码强制过滤) ----
_f = mem_mod._filter_item
check("88 做了什么(修复)被排除",
      _f({"level": "insight", "content": "修复了分页 bug"}) is None)
check("89 洞察无信号仍保留为 insight",
      _f({"level": "insight", "content": "Web 面板分页每行三个"})["level"] == "insight")
check("90 洞察含信号保留",
      _f({"level": "insight", "content": "决定了 Web 面板分页每行三个"})["level"] == "insight")
check("91 琐碎内容丢弃", _f({"level": "insight", "content": "嗯"}) is None)
conn.commit()

# ---- Web 冒烟 (fastapi 可选) ----
try:
    from lclone.web import create_app
    app = create_app(dbp)
    routes = {r.path for r in app.routes}
    check("24 Web 路由", "/api/ask" in routes and "/api/supervise" in routes
          and "/api/memories" in routes and "/mcp" in routes)
except ImportError:
    print("SKIP 24 Web (fastapi 未安装, 装依赖后自动启用)")

# ---- recall 跟随 insight→evolution 边 (命中带 [[evo:...]] 的洞察, 带出进化文件) ----
_ev_recall = mem_mod.remember(conn, "实践中沉淀的 build-spec-map 工具用于构建 spec 地图索引 [[evo:build-spec-map.sh]]",
                              level="insight", project_id=pid, confirmed=True)
_li = mem_mod.recall(conn, "构建 spec 地图", project_id=pid, k=5, follow_links=True)
check("94 recall 命中相关洞察", any(i.get("id") == _ev_recall for i in _li),
      str([i.get("id") for i in _li]))
_check_evo = any(i.get("via_evolution") and i.get("evo_name") == "build-spec-map.sh" for i in _li)
check("95 recall 顺边带出 evolution(文件)", _check_evo,
      str([(i.get("id"), i.get("evo_name")) for i in _li]))
cli_buf = io.StringIO()
with contextlib.redirect_stdout(cli_buf):
    cli.main(["evolution", "list", "--db", dbp])
check("96 CLI evolution list", "build-spec-map.sh" in cli_buf.getvalue(),
      cli_buf.getvalue()[:80])
cli_buf = io.StringIO()
with contextlib.redirect_stdout(cli_buf):
    cli.main(["evolution", "add", "gen-tool2", "--content", "通用小工具B", "--db", dbp])
check("97 CLI evolution add", "已沉淀进化资产" in cli_buf.getvalue(),
      cli_buf.getvalue()[:80])

# ---- ingest 剥噪: capture 前剥离宿主注入的标签块 ----
_noisy = "用户：帮我看下这个 bug。<system-reminder>你是一个 coding agent……</system-reminder>\n<private>这是私密信息</private>"
_clean = mem_mod._strip_ingest_noise(_noisy)
check("100 ingest 剥噪(系统提示/私有块)",
      "帮我看下这个 bug" in _clean and "coding agent" not in _clean
      and "私密信息" not in _clean, _clean[:60])
_noisy2 = "用户：正常讨论内容\n<claude-mem-context>注入记忆段</claude-mem-context>"
_clean2 = mem_mod._strip_ingest_noise(_noisy2)
check("101 ingest 剥噪(claude-mem-context)",
      "正常讨论内容" in _clean2 and "注入记忆段" not in _clean2, _clean2[:60])
# 不影响正常内容
check("102 ingest 剥噪不动正常文本",
      mem_mod._strip_ingest_noise("决定 6月1日上线") == "决定 6月1日上线")

# ---- 记忆矛盾检测: 找疑似互相矛盾的洞察对 (LLM 判定) ----
_ci_a = mem_mod.remember(conn, "决定: 记忆用 SQLite 存储", level="insight",
                         project_id=pid, confirmed=True)
_ci_b = mem_mod.remember(conn, "决定: 记忆改用 PostgreSQL 存储", level="insight",
                         project_id=pid, confirmed=True)
_orig_cj = llm_mod.chat_json
llm_mod.chat_json = lambda prompt, temperature=None: [
    {"a": _ci_a, "b": _ci_b, "conflict": True, "reason": "存储选型前后矛盾"}]
_con = mem_mod.find_conflicts(conn, project_id=pid, threshold=0.0)
llm_mod.chat_json = _orig_cj
check("103 矛盾检测发现冲突对",
      any(c["a"] == _ci_a and c["b"] == _ci_b for c in _con), str(_con))
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    cli.main(["conflicts", "--db", dbp])
check("104 CLI conflicts", "未发现疑似矛盾" in buf.getvalue(),
      buf.getvalue()[:60])

# ---- 鉴权: env key + 受管 token (哈希存储, 可吊销) ----
from lclone import auth as auth_mod  # noqa: E402

_orig_key = os.environ.pop("LCLONE_API_KEY", None)
from lclone import config as cfg_mod  # noqa: E402
cfg_mod._loaded = False

_tok_cols = {r["name"] for r in conn.execute("PRAGMA table_info(access_tokens)")}
check("105 access_tokens 表存在",
      {"id", "name", "token_hash", "created_at", "last_used_at", "revoked_at"} <= _tok_cols,
      str(sorted(_tok_cols)))

check("106 无 token 无 env key -> 未启用/免鉴权",
      auth_mod.enabled(conn) is False and auth_mod.check({}, conn) is True)

_tok = auth_mod.create_token(conn, "laptop")
check("107 create 返回带前缀明文", _tok.startswith(auth_mod.TOKEN_PREFIX), _tok[:14])
_row = conn.execute("SELECT token_hash FROM access_tokens WHERE name='laptop'").fetchone()
check("108 库中只存哈希不存明文",
      _row["token_hash"] == auth_mod.hash_token(_tok) and _tok not in _row["token_hash"])
check("109 有活跃 token -> 启用",
      auth_mod.enabled(conn) is True and auth_mod.check({}, conn) is False)
check("110 有效 token (X-API-Key/Bearer) 通过",
      auth_mod.check({"x-api-key": _tok}, conn) is True
      and auth_mod.check({"authorization": "Bearer " + _tok}, conn) is True)
check("111 无效 token 拒绝", auth_mod.check({"x-api-key": "lclone_bad"}, conn) is False)
_lu = conn.execute("SELECT last_used_at FROM access_tokens WHERE name='laptop'").fetchone()
check("112 last_used_at 更新", _lu["last_used_at"] is not None)
check("113 revoke 后该 token 失效",
      auth_mod.revoke_token(conn, name="laptop") == 1
      and auth_mod.check({"x-api-key": _tok}, conn) is False)

os.environ["LCLONE_API_KEY"] = "envkey-xyz"
cfg_mod._loaded = False
check("114 env key 兼容通过", auth_mod.check({"x-api-key": "envkey-xyz"}, conn) is True
      and auth_mod.check({"x-api-key": "wrong"}, conn) is False)
os.environ.pop("LCLONE_API_KEY", None)
cfg_mod._loaded = False

_buf = io.StringIO()
with contextlib.redirect_stdout(_buf):
    cli.main(["auth", "create", "desktop", "--db", dbp])
_out = _buf.getvalue()
check("115 CLI auth create 打印一次明文", "desktop" in _out and "lclone_" in _out, _out[:50])
_buf = io.StringIO()
with contextlib.redirect_stdout(_buf):
    cli.main(["auth", "list", "--db", dbp])
check("116 CLI auth list 显示 name 与状态",
      "desktop" in _buf.getvalue() and "active" in _buf.getvalue(), _buf.getvalue()[:60])
_buf = io.StringIO()
with contextlib.redirect_stdout(_buf):
    cli.main(["auth", "revoke", "desktop", "--db", dbp])
check("117 CLI auth revoke 生效", "1" in _buf.getvalue(), _buf.getvalue()[:40])

if _orig_key is not None:
    os.environ["LCLONE_API_KEY"] = _orig_key
    cfg_mod._loaded = False

# ---- 确定性准入闸门 (gate): 脚本先判定, LLM 只兜底 ----
from lclone import gate  # noqa: E402

check("118 gate 短文本跳过", gate.classify("嗯 好的").kind == gate.SKIP)
check("119 gate 疑问句跳过",
      gate.classify("这个方案应该怎么改才比较合适呢？").kind == gate.SKIP,
      gate.classify("这个方案应该怎么改才比较合适呢？").reason)
check("120 gate 寒暄跳过", gate.classify("好的 谢谢").kind == gate.SKIP)
check("121 gate 「做了什么」跳过",
      gate.classify("修复了分页 bug 并重构了查询层").kind == gate.SKIP)
check("122 gate 代码块剥离后过短跳过",
      gate.classify("看下这个\n```\nprint(1)\n```\n").kind == gate.SKIP)
_v123 = gate.classify("决定记忆统一用 SQLite 存")
check("123 gate 决策命中候选",
      _v123.kind == gate.CANDIDATE and "决定" in _v123.hits, str(_v123))
check("124 gate 教训命中候选",
      gate.classify("这次踩坑的原因在于没做归属判定，下次要先确认").kind == gate.CANDIDATE)
check("125 gate 否定作用域不计命中",
      gate.classify("这个不用统一，各家自己定就行，没有硬要求").kind == gate.UNCERTAIN,
      str(gate.classify("这个不用统一，各家自己定就行，没有硬要求")))
check("126 gate 显式「记住」旁路", gate.classify("记住：用 SQLite").kind == gate.CANDIDATE)
check("127 gate 短决策句不被长度误杀",
      gate.classify("决定统一口径").kind == gate.CANDIDATE)
check("128 gate 无信号判不确定",
      gate.classify("日志文件里的时间戳格式有点乱").kind == gate.UNCERTAIN)
check("128b gate 短时性措辞判跳过 (可重测的近况)",
      gate.classify("今天看了一下午的日志文件内容").kind == gate.SKIP
      and "今天" in gate.classify("今天看了一下午的日志文件内容").hits,
      str(gate.classify("今天看了一下午的日志文件内容")))
check("129 gate 只看用户轮",
      gate.classify("用户：决定统一口径\n\n助手：好的，我修复了三个 bug 并重构了模块")
      .kind == gate.CANDIDATE)
check("130 gate 剥离助手轮噪声",
      gate.classify("用户：这里随便写点什么内容都行，先放一放再说吧\n\n"
                    "助手：修复了三个 bug，重构了查询层，迁移了表结构").kind == gate.UNCERTAIN,
      str(gate.classify("用户：这里随便写点什么内容都行，先放一放再说吧\n\n"
                        "助手：修复了三个 bug，重构了查询层，迁移了表结构")))

# ---- capture 接入闸门: skip 不调 LLM / 诊断返回 / 上限 / 判重 ----
_calls = {"n": 0}
_orig_ex_g = llm_mod.extract_memories


def _count_ex(t):
    _calls["n"] += 1
    return _orig_ex_g(t)


llm_mod.extract_memories = _count_ex
_skip_ids = mem_mod.capture(conn, "修复了分页 bug 并重构了查询层", project_id=pid)
llm_mod.extract_memories = _orig_ex_g
check("131 gate skip 时完全不调 LLM",
      _skip_ids == [] and _calls["n"] == 0, f"calls={_calls['n']}")

_rep = mem_mod.capture_report(conn, "决定了记忆统一用 SQLite 存", project_id=pid)
check("132 capture_report 带闸门诊断",
      _rep["gate"]["kind"] == "candidate" and _rep["ids"], str(_rep))
_rep2 = mem_mod.capture_report(conn, "日志文件里的时间戳格式有点乱", project_id=pid)
check("133 uncertain 档经 LLM 判定后仍可成卡",
      _rep2["gate"]["kind"] == "uncertain", str(_rep2["gate"]))

_orig_ex_cap = llm_mod.extract_memories
llm_mod.extract_memories = lambda t: [
    {"level": "insight", "content": f"决定统一口径第 {i} 版"} for i in range(5)]
_cap_ids = mem_mod.capture(conn, "决定统一口径五条一起来", project_id=pid)
llm_mod.extract_memories = _orig_ex_cap
check("134 单轮成卡上限 1 条 (默认不产出)", len(_cap_ids) == 1, f"{len(_cap_ids)} 条")

check("135 归一化判重键忽略标点空白",
      mem_mod._norm_for_dup("决定了 凭证统一走网关鉴权。")
      == mem_mod._norm_for_dup("决定了凭证统一走网关鉴权"))
_dup1 = mem_mod.capture(conn, "决定了凭证统一走网关鉴权", project_id=pid)
_dup2 = mem_mod.capture(conn, "决定了凭证统一走网关鉴权。", project_id=pid)
check("136 归一化文本判重拦截重复捕获",
      len(_dup1) == 1 and _dup2 == [], f"{_dup1} / {_dup2}")

# ---- 首次种子内容: 幂等 + 不回灌 + 不覆盖用户改过的进化文件 ----
from lclone import seed as seed_mod  # noqa: E402

_r1 = seed_mod.apply(conn)
check("137 seed 种入通用洞察", len(_r1["insights_added"]) == 4, str(_r1["insights_added"]))
_seed_n = conn.execute(
    "SELECT COUNT(*) c FROM memories WHERE source_type='seed'"
    " AND status='active' AND project_id IS NULL"
).fetchone()["c"]
check("138 种子洞察落全局层且直接生效", _seed_n == 4, f"{_seed_n} 条")
check("139 种子进化文件已写入",
      len(_r1["evolutions_added"]) == 5
      and (pathlib.Path(os.environ["LCLONE_EVO_DIR"]) / "洞察格式模型.md").exists(),
      str(_r1["evolutions_added"]))
_r2 = seed_mod.apply(conn)
check("140 seed 幂等 (重复调用不重复种)",
      _r2["insights_added"] == [] and _r2["evolutions_added"] == [], str(_r2))

conn.execute("DELETE FROM memories WHERE source_type='seed' AND content LIKE '%删除纪律%'")
conn.commit()
_r3 = seed_mod.apply(conn)
check("141 用户删掉的种子洞察不回灌",
      "删除纪律" in _r3["insights_skipped"], str(_r3["insights_skipped"]))

_user_evo = pathlib.Path(os.environ["LCLONE_EVO_DIR"]) / "记忆准入标准.md"
_user_evo.write_text("我改过的内容", encoding="utf-8")
seed_mod.apply(conn, force=False)
check("142 不覆盖用户改过的进化文件", _user_evo.read_text(encoding="utf-8") == "我改过的内容")
seed_mod.apply(conn, force=True)
check("143 --force 才覆盖进化文件", "记忆准入标准" in _user_evo.read_text(encoding="utf-8"))

# ---- CLI: gate / seed ----
_gbuf = io.StringIO()
with contextlib.redirect_stdout(_gbuf):
    cli.main(["gate", "决定统一口径", "--db", dbp])
check("144 CLI gate 输出判定与命中",
      "candidate" in _gbuf.getvalue() and "决定" in _gbuf.getvalue(),
      _gbuf.getvalue()[:60])
_sbuf = io.StringIO()
with contextlib.redirect_stdout(_sbuf):
    cli.main(["seed", "--dry-run", "--db", dbp])
check("145 CLI seed --dry-run 不写入",
      "dry-run" in _sbuf.getvalue() or "已是最新" in _sbuf.getvalue(),
      _sbuf.getvalue()[:80])

# ---- gate 回归: 疑问句优先 / 词边界 / 泛词收紧 / 政策陈述 ----
check("146 疑问句含信号词也跳过",
      gate.classify("这个默认值要改吗？").kind == gate.SKIP,
      str(gate.classify("这个默认值要改吗？")))
check("147 「要不要」不再误命中「不要」",
      "不要" not in gate.classify("不确定要不要统一").hits
      and gate.classify("不确定要不要统一").kind == gate.SKIP,
      str(gate.classify("不确定要不要统一")))
_v148 = gate.classify("用 prefix 命名所有变量吧，保持可读")
check("148 拉丁词按词边界 (prefix 不命中 fix)",
      _v148.kind != gate.SKIP and "fix" not in _v148.hits, str(_v148))
_v149 = gate.classify("开启 debug 模式看看日志输出")
check("149 拉丁词按词边界 (debug 不命中 bug)",
      _v149.kind != gate.SKIP and "bug" not in _v149.hits, str(_v149))
check("150 拉丁词忽略大小写 (Fix 命中 fix)",
      "fix" in gate.classify("Fix 了分页查询里的空指针问题").hits,
      str(gate.classify("Fix 了分页查询里的空指针问题")))
check("151 政策陈述不被「回滚」误杀",
      gate.classify("回滚策略定为保留最近三个版本").kind == gate.CANDIDATE,
      str(gate.classify("回滚策略定为保留最近三个版本")))
check("152 泛词收紧 (原来 不再当教训信号)",
      gate.classify("原来是这样啊，我懂了").kind == gate.SKIP,
      str(gate.classify("原来是这样啊，我懂了")))
check("153 否定豁免 (不错 不算否定)",
      gate.classify("现在效果不错，统一按这个来").kind == gate.CANDIDATE,
      str(gate.classify("现在效果不错，统一按这个来")))
check("154 畸形角色标记回退原文",
      bool(gate.user_turns("用户：助手：决定统一口径").strip()))
check("154b 寒暄污染的弱教训信号不算数",
      gate.classify("嗯嗯明白了，那下次注意").kind == gate.SKIP
      and gate.classify("下次注意：迁移前先备份数据").kind == gate.CANDIDATE,
      str(gate.classify("嗯嗯明白了，那下次注意")))
# 正文里引用「用户：/助手：」不应把内容切碎 (真实 commit 正文就长这样)
_quoted = ("commit: fix(memory): 收窄判定顺序\n\n"
           "只看用户轮(按 用户：/助手： 切分)、疑问句优先\n"
           "- 修复了 gate 的判定顺序, 重构了 classify")
_vq = gate.classify(_quoted)
check("154c 正文引用的角色标记不算角色切换",
      _vq.kind == gate.SKIP and "修复" in _vq.hits, str(_vq))

# ---- seed: dry-run 真不写 / --no-seed / 打包缺失守卫 ----
check("155 种子包随包分发", seed_mod.available() is True,
      str(seed_mod.starter_dir()))
_dry_root = tempfile.mkdtemp(prefix="dryevo_")
_orig_evo_dir = os.environ.get("LCLONE_EVO_DIR")
os.environ["LCLONE_EVO_DIR"] = os.path.join(_dry_root, "evolutions")
try:
    _dry_conn = db_mod.init(os.path.join(tempfile.mkdtemp(), "dry.db"))
    _drep = seed_mod.apply(_dry_conn, dry_run=True)
    _dmem = _dry_conn.execute("SELECT COUNT(*) c FROM memories").fetchone()["c"]
    _dstate = _dry_conn.execute("SELECT COUNT(*) c FROM seed_state").fetchone()["c"]
    _devo = os.path.exists(os.environ["LCLONE_EVO_DIR"])
finally:
    if _orig_evo_dir is None:
        os.environ.pop("LCLONE_EVO_DIR", None)
    else:
        os.environ["LCLONE_EVO_DIR"] = _orig_evo_dir
check("156 seed --dry-run 不写库/不建目录",
      len(_drep["insights_added"]) == 4 and _dmem == 0 and _dstate == 0 and not _devo,
      f"ins={len(_drep['insights_added'])} mem={_dmem} state={_dstate} evo={_devo}")

_ns_root = tempfile.mkdtemp(prefix="noseed_")
_ns_db = os.path.join(_ns_root, "ns.db")
_orig_write_env = install_mod._write_env
_orig_cwd2 = os.getcwd()
install_mod._write_env = lambda provider, api_key, db_path: pathlib.Path(_ns_root) / ".env"
_ns_buf = io.StringIO()
try:
    os.chdir(_ns_root)
    with contextlib.redirect_stdout(_ns_buf):
        _ns_rc = install_mod.setup(provider="dummy", yes=True, db_path=_ns_db, no_seed=True)
finally:
    os.chdir(_orig_cwd2)
    install_mod._write_env = _orig_write_env
_ns_conn = db_mod.init(_ns_db)
_ns_seed = _ns_conn.execute(
    "SELECT COUNT(*) c FROM memories WHERE source_type='seed'").fetchone()["c"]
check("157 setup --no-seed 不种入种子",
      _ns_rc == 0 and _ns_seed == 0 and "no-seed" in _ns_buf.getvalue(),
      _ns_buf.getvalue()[-120:])

# 种入需要 embedding: 无可用 key 时必须降级为提示, 不能把一键接入搞崩
_nk_root = tempfile.mkdtemp(prefix="nokey_")
_nk_db = os.path.join(_nk_root, "nk.db")
_orig_llm_env = {k: os.environ.get(k) for k in ("BRAIN_LLM", "BRAIN_EMBED_BACKEND",
                                                "OPENAI_API_KEY")}
install_mod._write_env = lambda provider, api_key, db_path: pathlib.Path(_nk_root) / ".env"
_nk_buf = io.StringIO()
try:
    os.environ["BRAIN_LLM"] = "api"
    os.environ["BRAIN_EMBED_BACKEND"] = "api"
    os.environ.pop("OPENAI_API_KEY", None)
    cfg_mod._loaded = False
    os.chdir(_nk_root)
    with contextlib.redirect_stdout(_nk_buf):
        _nk_rc = install_mod.setup(provider="openai", api_key="", yes=True, db_path=_nk_db)
finally:
    os.chdir(_orig_cwd2)
    install_mod._write_env = _orig_write_env
    for _k, _v in _orig_llm_env.items():
        if _v is None:
            os.environ.pop(_k, None)
        else:
            os.environ[_k] = _v
    cfg_mod._loaded = False
check("158 无可用 key 时种入失败只降级提示",
      _nk_rc == 0 and "种子内容" in _nk_buf.getvalue() and "跳过" in _nk_buf.getvalue(),
      _nk_buf.getvalue()[-160:])

# ---- 备份覆盖两处存储: SQLite(洞察) + 文件式进化资产 ----
_bk_dest = tempfile.mkdtemp(prefix="bk_")
_bk_buf = io.StringIO()
with contextlib.redirect_stdout(_bk_buf):
    cli.main(["backup", "--db", dbp, "--dest", _bk_dest])
_bk_dbs = sorted(pathlib.Path(_bk_dest).glob("lclone-*.db"))
_bk_blobs = sorted(pathlib.Path(_bk_dest).glob("lclone-*.blobs"))
check("159 备份同时覆盖 DB 与进化资产内容库",
      len(_bk_dbs) == 1 and len(_bk_blobs) == 1 and _bk_blobs[0].is_dir()
      and any(p.is_file() for p in _bk_blobs[0].rglob("*")),
      _bk_buf.getvalue().strip().replace("\n", " | ")[:110])

# ---- 进化资产: 服务器权威的内容寻址版本化存储 ----
from lclone import evolutions as evo_store  # noqa: E402

_c0 = evo_store.blob_count()
_p1 = evo_store.publish(conn, "ver-demo.sh", "echo v1", message="首版")
check("160 publish 建 v1", _p1["version"] == 1 and _p1["changed"] and _p1["hash"],
      str(_p1))
_p1b = evo_store.publish(conn, "ver-demo.sh", "echo v1")
check("161 publish 幂等 (同内容不新增版本)",
      _p1b["version"] == 1 and _p1b["changed"] is False, str(_p1b))
check("162 同内容只存一份 blob (内容寻址去重)",
      evo_store.blob_count() == _c0 + 1, f"{_c0} -> {evo_store.blob_count()}")

_p2 = evo_store.publish(conn, "ver-demo.sh", "echo v2", message="改一版")
check("163 改内容 → v2", _p2["version"] == 2 and _p2["changed"], str(_p2))
_h = evo_store.history(conn, "ver-demo.sh")
check("164 版本历史只追加 (新→旧)", [h["version"] for h in _h] == [2, 1], str(_h))
check("165 旧版本内容仍可取回",
      evo_store.resolve(conn, "ver-demo.sh", 1)["content"] == "echo v1")
_c_before_rb = evo_store.blob_count()
_rb = evo_store.rollback(conn, "ver-demo.sh", 1)
check("166 回滚只改指向, 不动 blob",
      evo_store.resolve(conn, "ver-demo.sh")["content"] == "echo v1"
      and evo_store.blob_count() == _c_before_rb, str(_rb["version"]))
_rb_err = False
try:
    evo_store.rollback(conn, "ver-demo.sh", 99)
except ValueError:
    _rb_err = True
check("167 回滚到不存在的版本报错", _rb_err)

_p_ref = evo_store.publish(conn, "in-repo.sh", None, ref="scripts/foo.sh", kind="script")
check("168 ref 类只记引用 (hash 空 / 不进 manifest)",
      _p_ref["hash"] == "" and "in-repo.sh" not in evo_store.manifest_index(conn),
      str(_p_ref))
check("169 ref 类 resolve 返回指针而非内容",
      evo_store.resolve(conn, "in-repo.sh")["content"] is None)

# ---- 本地只读缓存: pull / status / publish ----
_backend = evo_store.LocalBackend(conn)
_res = evo_store.pull(_backend, all_=True)
check("170 pull --all 物化到本地缓存 + 写 manifest",
      "ver-demo.sh" in _res["written"]
      and evo_store.manifest_path().is_file()
      and (evo_store.cache_dir() / "ver-demo.sh").is_file(),
      str(_res["written"])[:80])
check("171 再 pull 无变化 → up_to_date",
      "ver-demo.sh" in evo_store.pull(_backend, all_=True)["up_to_date"])

_cache_file = evo_store.cache_dir() / "ver-demo.sh"
_before_dirty = _cache_file.read_text(encoding="utf-8")
_cache_file.write_text("echo 我手改的", encoding="utf-8")
_st = {r["name"]: r["state"] for r in evo_store.status(_backend.manifest())}
check("172 本地改过 → status=dirty", _st.get("ver-demo.sh") == "dirty", str(_st.get("ver-demo.sh")))
_dres = evo_store.pull(_backend, ["ver-demo.sh"])
check("173 pull 拒绝覆盖 dirty 文件",
      _dres["skipped_dirty"] == ["ver-demo.sh"]
      and _cache_file.read_text(encoding="utf-8") == "echo 我手改的", str(_dres))
_fres = evo_store.pull(_backend, ["ver-demo.sh"], force=True)
check("174 --force 才覆盖 (旧文件另存 .dirty.bak)",
      _fres["written"] == ["ver-demo.sh"]
      and _cache_file.read_text(encoding="utf-8") == "echo v1"
      and (_cache_file.with_name(_cache_file.name + ".dirty.bak")).is_file(),
      str(_fres))

_cache_file.write_text("echo 从本地推上去的新内容", encoding="utf-8")
_pub = evo_store.publish_local(_backend, "ver-demo.sh", message="从本地推")
check("175 publish_local 推新版本 v3", _pub["version"] == 3 and _pub["changed"], str(_pub))
_st2 = {r["name"]: r["state"] for r in evo_store.status(_backend.manifest())}
check("176 推送后回到 in-sync", _st2.get("ver-demo.sh") == "in-sync", str(_st2.get("ver-demo.sh")))

_orphan = evo_store.cache_dir() / "hand-made.md"
_orphan.write_text("本地手写的资产", encoding="utf-8")
_st3 = {r["name"]: r["state"] for r in evo_store.status(_backend.manifest())}
check("177 本地有服务器没有 → untracked", _st3.get("hand-made.md") == "untracked", str(_st3))
_allres = evo_store.publish_all(_backend, message="批量推")
check("178 publish --all 推送 dirty/untracked",
      "hand-made.md" in [x["name"] for x in _allres["published"]], str(_allres))

_mig = evo_store.cache_dir() / "legacy-tool.py"
_mig.write_text("print('legacy')", encoding="utf-8")
_mig_out = evo_store.migrate_cache_files(conn)
check("179 migrate 把存量文件摄入为 v1",
      [m["name"] for m in _mig_out] == ["legacy-tool.py"]
      and evo_store.current(conn, "legacy-tool.py")["version"] == 1, str(_mig_out))
check("180 migrate 幂等 (已收录的不再处理)",
      evo_store.migrate_cache_files(conn) == [])

# ---- CLI: evolution 子命令 (本地) ----
_cli_evo = io.StringIO()
with contextlib.redirect_stdout(_cli_evo):
    cli.main(["evolution", "history", "ver-demo.sh", "--local", "--db", dbp])
check("181 CLI evolution history", "v3" in _cli_evo.getvalue()
      and "v1" in _cli_evo.getvalue(), _cli_evo.getvalue()[:60])
_cli_evo = io.StringIO()
with contextlib.redirect_stdout(_cli_evo):
    cli.main(["evolution", "status", "--local", "--db", dbp])
check("182 CLI evolution status", "in-sync" in _cli_evo.getvalue(),
      _cli_evo.getvalue()[:60])
_cli_evo = io.StringIO()
with contextlib.redirect_stdout(_cli_evo):
    cli.main(["evolution", "rollback", "ver-demo.sh", "--to", "1", "--local", "--db", dbp])
check("183 CLI evolution rollback", "已回滚到 v1" in _cli_evo.getvalue(),
      _cli_evo.getvalue()[:60])

# ---- 远端路由: 设了 LCLONE_WEB_URL 就走 HTTP ----
_http_buf = io.StringIO()
_prev_env = {k: os.environ.get(k) for k in ("LCLONE_WEB_URL", "LCLONE_API_KEY")}
os.environ["LCLONE_WEB_URL"] = "http://brain.example:8000"
os.environ["LCLONE_API_KEY"] = "tok-123"
cfg_mod._loaded = False
try:
    with contextlib.redirect_stdout(_http_buf):
        _bk2, _cn2 = cli._evo_ctx(type("A", (), {"local": False, "db": dbp})())
finally:
    for _k, _v in _prev_env.items():
        if _v is None:
            os.environ.pop(_k, None)
        else:
            os.environ[_k] = _v
    cfg_mod._loaded = False
check("184 设了 LCLONE_WEB_URL → 选 HttpBackend 且不碰本地 DB",
      isinstance(_bk2, evo_store.HttpBackend) and _cn2 is None
      and "brain.example" in _http_buf.getvalue(),
      _http_buf.getvalue().strip()[:60])

# ---- HttpBackend 走 REST + 带鉴权头 (stub 掉 urlopen) ----
_seen = {}


class _FakeResp:
    def __init__(self, body):
        self._body = body.encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_urlopen(req, timeout=None):
    _seen["url"] = req.full_url
    _seen["auth"] = req.get_header("Authorization")
    if "/api/evolution/manifest" in req.full_url:
        return _FakeResp(json.dumps({"items": {"x.sh": {"version": 2, "hash": "h2",
                                                        "size": 3, "kind": "script",
                                                        "project_id": None}}}))
    if "/api/evolution/content" in req.full_url:
        return _FakeResp(json.dumps({"content": "echo x", "hash": "h2"}))
    if "/api/evolution/index" in req.full_url:
        return _FakeResp(json.dumps({"items": []}))
    return _FakeResp("{}")


_orig_urlopen = urllib.request.urlopen
urllib.request.urlopen = _fake_urlopen
try:
    _hb = evo_store.HttpBackend("http://brain.example:8000", "tok-xyz")
    _man = _hb.manifest()
    _cont = _hb.content("x.sh", 2)
finally:
    urllib.request.urlopen = _orig_urlopen
check("185 HttpBackend 解析 manifest/content",
      _man["x.sh"]["version"] == 2 and _cont == "echo x", f"{_man}")
check("186 HttpBackend 带 Bearer 鉴权头",
      _seen.get("auth") == "Bearer tok-xyz", str(_seen.get("auth")))

# ---- REST: /api/evolution/* + /api/evolutions 形状不变 ----
try:
    from fastapi.testclient import TestClient
    _web_dbp = os.path.join(tempfile.mkdtemp(prefix="evoapi_"), "w.db")
    from lclone import web as _web_mod
    _tc = TestClient(_web_mod.create_app(_web_dbp))
    check("187 /api/evolution/publish 建 v1",
          _tc.post("/api/evolution/publish",
                   json={"name": "api.sh", "content": "echo api"}).json()
          ["result"]["version"] == 1)
    check("188 /api/evolution/publish 幂等",
          _tc.post("/api/evolution/publish",
                   json={"name": "api.sh", "content": "echo api"}).json()
          ["result"]["changed"] is False)
    _tc.post("/api/evolution/publish", json={"name": "api.sh", "content": "echo api2"})
    check("189 /api/evolution/history 两版",
          [h["version"] for h in
           _tc.get("/api/evolution/history?name=api.sh").json()["items"]] == [2, 1])
    check("190 /api/evolution/rollback",
          _tc.post("/api/evolution/rollback",
                   json={"name": "api.sh", "version": 1}).json()["result"]["version"] == 1)
    _evo_items = _tc.get("/api/evolutions").json()["items"]
    _old_keys = {"name", "ext", "size", "mtime", "is_dir", "children", "content"}
    check("191 /api/evolutions 响应形状不变 (前端零改动)",
          _evo_items and _old_keys <= set(_evo_items[0].keys())
          and _evo_items[0]["content"] == "echo api",
          str(sorted(_evo_items[0].keys())))
except ImportError as e:  # 无 fastapi 环境跳过
    print(f"SKIP 187-191 (缺依赖: {e})")

# ---- 审查修复的回归用例 ----
_bad_content = "echo v1"
_bad_hash = evo_store.sha256_text(_bad_content)
evo_store.publish(conn, "heal.sh", _bad_content)
_bp = evo_store._blob_path(_bad_hash)
_bp.write_text("被篡改的内容", encoding="utf-8")
check("192 损坏内容读为缺失 (不返回被篡改内容)",
      evo_store.resolve(conn, "heal.sh")["content"] is None)
evo_store.publish(conn, "heal.sh", _bad_content)
check("193 再次发布同一内容 → 自愈恢复可读",
      evo_store.resolve(conn, "heal.sh")["content"] == _bad_content)


class _LieBackend(evo_store.LocalBackend):
    """模拟"传回来的内容与清单哈希不符"的后端。"""

    def content(self, name, version=None):
        return "内容被中间人改过"


_orig_blob = evo_store.cache_dir() / "lie.sh"
_orig_blob.write_text("本地内容(与服务器不同)", encoding="utf-8")
evo_store.publish(conn, "lie.sh", "远程内容")
_lie = evo_store.pull(_LieBackend(conn), ["lie.sh"], force=True)
check("194 pull 校验哈希失败 → 不落盘且不覆盖本地",
      _lie["hash_mismatch"] == ["lie.sh"]
      and _orig_blob.read_text(encoding="utf-8") == "本地内容(与服务器不同)", str(_lie))

_m1 = evo_store.publish(conn, "meta.sh", "echo meta", kind="script")
_m2 = evo_store.publish(conn, "meta.sh", "echo meta", kind="tool")
check("195 内容不变但元数据变了 → 记录新版本",
      _m2["changed"] and _m2["version"] == _m1["version"] + 1, str(_m2))
_m3 = evo_store.publish(conn, "meta.sh", "echo meta", kind="tool")
check("196 内容与元数据都没变 → 幂等", _m3["changed"] is False, str(_m3))

(evo_store.cache_dir() / "noext").write_text("echo noext", encoding="utf-8")
_noext = evo_store.publish_local(_backend, "noext")
_st_noext = {r["name"]: r["state"] for r in evo_store.status(_backend.manifest())}
check("197 无扩展名发布后按归一化名记账 (无幽灵 missing)",
      _noext["name"] == "noext.txt" and _st_noext.get("noext.txt") == "in-sync"
      and "noext.txt" not in [k for k, v in _st_noext.items() if v == "missing"],
      f"{_noext['name']} {_st_noext.get('noext.txt')}")

check("198 .dirty.bak 不算进化资产",
      all(not n.endswith(".dirty.bak") for n in evo_store._local_files())
      and not any("dirty.bak" in x["name"] for x in
                  evo_store.publish_all(_backend)["published"]))

evo_store.publish(conn, "behind.sh", "echo b1")
evo_store.publish(conn, "behind.sh", "echo b2")
evo_store.pull(_backend, ["behind.sh"])
evo_store.rollback(conn, "behind.sh", 1)
_st_b = {r["name"]: r["state"] for r in evo_store.status(_backend.manifest())}
check("199 回滚后干净的本地报 behind (与 pull 允许覆盖一致)",
      _st_b.get("behind.sh") == "behind", str(_st_b.get("behind.sh")))
check("200 publish --all 不会把回滚悄悄推回去",
      "behind.sh" not in [x["name"] for x in evo_store.publish_all(_backend)["published"]])

_ref_conflict = False
try:
    evo_store.publish(conn, "both.sh", "内容", ref="scripts/both.sh")
except ValueError:
    _ref_conflict = True
check("201 ref 与 content 不能同时给", _ref_conflict)

# upgrade 场景: 文件在、索引空 —— list 也要能看到 (否则用户以为文件丢了)
_up = tempfile.mkdtemp(prefix="upg_")
_up_db = os.path.join(_up, "up.db")
_up_conn = db_mod.init(_up_db)
_prev_evo_dir = os.environ.get("LCLONE_EVO_DIR")
_prev_blob_dir = os.environ.get("LCLONE_EVO_BLOB_DIR")
os.environ["LCLONE_EVO_DIR"] = os.path.join(_up, "evo")
os.environ["LCLONE_EVO_BLOB_DIR"] = os.path.join(_up, "blobs")
try:
    pathlib.Path(os.environ["LCLONE_EVO_DIR"]).mkdir(parents=True, exist_ok=True)
    (pathlib.Path(os.environ["LCLONE_EVO_DIR"]) / "old-asset.sh").write_text(
        "echo old", encoding="utf-8")
    _lbuf = io.StringIO()
    with contextlib.redirect_stdout(_lbuf):
        cli.main(["evolution", "list", "--local", "--db", _up_db])
    _pre = _lbuf.getvalue()
    _lbuf = io.StringIO()
    with contextlib.redirect_stdout(_lbuf):
        cli.main(["evolution", "migrate", "--local", "--db", _up_db])
    _mbuf = _lbuf.getvalue()
    _post = evo_store.current(_up_conn, "old-asset.sh")
finally:
    if _prev_evo_dir is None:
        os.environ.pop("LCLONE_EVO_DIR", None)
    else:
        os.environ["LCLONE_EVO_DIR"] = _prev_evo_dir
    if _prev_blob_dir is None:
        os.environ.pop("LCLONE_EVO_BLOB_DIR", None)
    else:
        os.environ["LCLONE_EVO_BLOB_DIR"] = _prev_blob_dir
check("202 索引为空时 list 仍列出本地未收录文件",
      "old-asset.sh" in _pre and "未收录" in _pre, _pre.strip()[:80])
check("203 升级路径: migrate 把既有文件摄入为 v1",
      _post is not None and _post["version"] == 1 and "v1" in _mbuf, _mbuf.strip()[:60])
check("203b migrate 按扩展名推断 kind (脚本/模型可区分)",
      _post is not None and _post["kind"] == "script", str(_post and _post["kind"]))

# ---- insight → evolution 链接: 引用真正写进洞察内容, 召回能顺边带出 ----
_lk_ins = mem_mod.remember(conn, "要点：用统一脚本跑 spec 地图。\n归属：无",
                           level="insight", project_id=pid, confirmed=True)
evo_store.publish(conn, "link-demo.sh", "echo linked")
mem_mod.link_insight_to_evolution(conn, _lk_ins, "link-demo.sh")
_lk_content = conn.execute("SELECT content FROM memories WHERE id=?",
                           (_lk_ins,)).fetchone()["content"]
check("204 链接写入 [[evo:...]] 引用",
      "[[evo:link-demo.sh]]" in _lk_content, _lk_content[-48:])
mem_mod.link_insight_to_evolution(conn, _lk_ins, "link-demo.sh")
_lk2 = conn.execute("SELECT content FROM memories WHERE id=?",
                    (_lk_ins,)).fetchone()["content"]
check("205 重复链接幂等 (不重复追加)", _lk2.count("[[evo:link-demo.sh]]") == 1)
check("206 链接后可顺边带出资产",
      any(e["name"] == "link-demo.sh"
          for e in mem_mod.evolutions_for_insight(conn, _lk_ins)))
_lk_err = False
try:
    mem_mod.link_insight_to_evolution(conn, 99999999, "link-demo.sh")
except ValueError:
    _lk_err = True
check("207 链接不存在的 insight 报错", _lk_err)

# MCP 的 insight 参数真的接线 (call_tool 走自己的连接, 临时指向测试库)
_lk_mcp = mem_mod.remember(conn, "要点：MCP 链接测试。\n归属：无",
                           level="insight", project_id=pid, confirmed=True)
_prev_bdp = os.environ.get("BRAIN_DB_PATH")
os.environ["BRAIN_DB_PATH"] = dbp
try:
    _mcp_out = mcp_srv.call_tool("evolution_add", {
        "name": "mcp-link.sh", "content": "echo mcp",
        "project": "global", "insight": [_lk_mcp]})
finally:
    if _prev_bdp is None:
        os.environ.pop("BRAIN_DB_PATH", None)
    else:
        os.environ["BRAIN_DB_PATH"] = _prev_bdp
_lk_mcp_content = conn.execute("SELECT content FROM memories WHERE id=?",
                               (_lk_mcp,)).fetchone()["content"]
check("208 MCP evolution_add 的 insight 参数建立链接",
      "[[evo:mcp-link.sh]]" in _lk_mcp_content and "已链接 insight" in _mcp_out,
      _mcp_out.strip()[:70])

# ---- 命名收敛: 默认路径 + 类型补正 ----
_prev_dirs = {k: os.environ.get(k) for k in ("LCLONE_EVO_DIR", "LCLONE_EVO_BLOB_DIR")}
os.environ.pop("LCLONE_EVO_DIR", None)
os.environ.pop("LCLONE_EVO_BLOB_DIR", None)
try:
    _def_cache = evo_store.cache_dir(create=False)
    _def_blob = evo_store.blob_dir()
finally:
    for _k, _v in _prev_dirs.items():
        if _v is not None:
            os.environ[_k] = _v
check("209 默认路径收敛为单数 evolution",
      _def_cache == pathlib.Path.home() / ".lclone" / "evolution"
      and _def_blob.name == "blobs" and _def_blob.parent.name == "evolution",
      f"{_def_cache} | {_def_blob}")

# 类型补正: kind=other 但扩展名可推断 → 发布一版修正 (保留历史)
evo_store.publish(conn, "rt.sh", "echo rt")          # kind 缺省 = other
_rt_out = evo_store.retype_default_kinds(_backend)
_rt_row = evo_store.current(conn, "rt.sh")
_rt_hist = evo_store.history(conn, "rt.sh")
check("210 retype 把 other 补正为 script 且保留历史",
      _rt_row["kind"] == "script" and [h["version"] for h in _rt_hist] == [2, 1]
      and any(x["name"] == "rt.sh" for x in _rt_out),
      f"kind={_rt_row['kind']} hist={[h['version'] for h in _rt_hist]}")
check("211 retype 幂等 (已正确的资产不再动作)",
      not any(x["name"] == "rt.sh" for x in evo_store.retype_default_kinds(_backend)))

# ---- 212-214: evo_current 墓碑列 + 旧库迁移幂等 ----
_ecols = {r["name"] for r in conn.execute("PRAGMA table_info(evo_current)")}
check("212 evo_current 含 deleted_at / renamed_to 两列",
      {"deleted_at", "renamed_to"} <= _ecols, str(sorted(_ecols)))
check("213 两列默认为空串 (既有行不因迁移变成已删除)",
      all((r["deleted_at"] == "" and r["renamed_to"] == "")
          for r in conn.execute("SELECT deleted_at, renamed_to FROM evo_current")),
      "存在非空默认值")
# 旧形状库迁移: 手工造一个没有这两列的库, 再 init 两次, 应被补齐且幂等
_olddb = os.path.join(tmp, "evomig.db")
_oc = db_mod.connect(_olddb)
_oc.executescript(
    "CREATE TABLE evo_versions (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,"
    " version INTEGER NOT NULL, hash TEXT NOT NULL DEFAULT '', size INTEGER NOT NULL DEFAULT 0,"
    " kind TEXT NOT NULL DEFAULT 'other', project_id INTEGER, ref TEXT NOT NULL DEFAULT '',"
    " message TEXT NOT NULL DEFAULT '', source_ref TEXT NOT NULL DEFAULT '',"
    " created_at TEXT NOT NULL DEFAULT (datetime('now')), UNIQUE(name, version));"
    "CREATE TABLE evo_current (name TEXT PRIMARY KEY, version INTEGER NOT NULL,"
    " updated_at TEXT NOT NULL DEFAULT (datetime('now')));"
    "INSERT INTO evo_current(name, version) VALUES ('legacy.txt', 1);"
)
_oc.commit(); _oc.close()
db_mod.init(_olddb)   # 迁移
db_mod.init(_olddb)   # 再跑一次: 必须幂等
_oc2 = db_mod.connect(_olddb)
_mcols2 = {r["name"] for r in _oc2.execute("PRAGMA table_info(evo_current)")}
_legacy = _oc2.execute(
    "SELECT deleted_at, renamed_to FROM evo_current WHERE name='legacy.txt'").fetchone()
check("214 旧库迁移补列且幂等 (既有行保持活跃)",
      {"deleted_at", "renamed_to"} <= _mcols2
      and _legacy["deleted_at"] == "" and _legacy["renamed_to"] == "",
      f"cols={sorted(_mcols2)} legacy={dict(_legacy) if _legacy else None}")
_oc2.close()

# ---- 215-220: 可编辑内容判定 (合法 UTF-8 + 尺寸上限, 服务端唯一权威) ----
check("215 合法 UTF-8 且不超限 -> 可编辑",
      evo_store.editability("你好 world\n".encode("utf-8")) == (True, ""),
      str(evo_store.editability("你好 world\n".encode("utf-8"))))
check("216 含 NUL 字节 -> binary 只读",
      evo_store.editability(b"abc\x00def") == (False, "binary"),
      str(evo_store.editability(b"abc\x00def")))
check("217 非法 UTF-8 -> binary 只读",
      evo_store.editability(b"\xff\xfe\x80\x81") == (False, "binary"),
      str(evo_store.editability(b"\xff\xfe\x80\x81")))
check("218 超阈值 -> too_large 只读",
      evo_store.editability(b"a" * (evo_store.DEFAULT_MAX_EDITABLE_BYTES + 1))[1] == "too_large",
      "len=" + str(evo_store.DEFAULT_MAX_EDITABLE_BYTES + 1))
check("219 恰好等于阈值 -> 仍可编辑 (边界)",
      evo_store.editability(b"a" * evo_store.DEFAULT_MAX_EDITABLE_BYTES) == (True, ""),
      "len=" + str(evo_store.DEFAULT_MAX_EDITABLE_BYTES))
# 阈值必须运行时可改 (读函数, 非模块级常量快照)
_prev_max = os.environ.get("LCLONE_EVO_MAX_EDIT_BYTES")
try:
    os.environ["LCLONE_EVO_MAX_EDIT_BYTES"] = "4"
    check("220 env 覆盖阈值 (且非法值回落默认)",
          evo_store.editability(b"abcd") == (True, "")
          and evo_store.editability(b"abcde") == (False, "too_large")
          and evo_store.max_editable_bytes() == 4,
          f"max={evo_store.max_editable_bytes()}")
    os.environ["LCLONE_EVO_MAX_EDIT_BYTES"] = "not-a-number"
    check("221 非法 env 值回落默认",
          evo_store.max_editable_bytes() == evo_store.DEFAULT_MAX_EDITABLE_BYTES,
          str(evo_store.max_editable_bytes()))
finally:
    if _prev_max is None:
        os.environ.pop("LCLONE_EVO_MAX_EDIT_BYTES", None)
    else:
        os.environ["LCLONE_EVO_MAX_EDIT_BYTES"] = _prev_max

# ---- 222-228: 墓碑删除与恢复 (evo_versions 与 blob 均不得变化) ----
_g_name = "tomb-demo.txt"
evo_store.publish(conn, _g_name, "v1 body")
evo_store.publish(conn, _g_name, "v2 body")
_ls_names = {x["name"] for x in evo_store.ls(conn)}
check("222 删除前在默认清单里", _g_name in _ls_names, str(sorted(_ls_names)))
_evc_before = conn.execute("SELECT COUNT(*) AS n FROM evo_versions").fetchone()["n"]
_blob_before = evo_store.blob_count()
_cur_before = evo_store.current(conn, _g_name)
_hist_before = evo_store.history(conn, _g_name)

_del = evo_store.delete(conn, _g_name)
check("223 删除返回 changed 且带时间戳",
      _del["changed"] is True and bool(_del["deleted_at"]), str(_del))
check("224 删除后从默认清单消失",
      _g_name not in {x["name"] for x in evo_store.ls(conn)},
      str(sorted(x["name"] for x in evo_store.ls(conn))))
check("225 删除不动 evo_versions 与 blob (历史仍完整可读)",
      conn.execute("SELECT COUNT(*) AS n FROM evo_versions").fetchone()["n"] == _evc_before
      and evo_store.blob_count() == _blob_before
      and [h["version"] for h in evo_store.history(conn, _g_name)] == [h["version"] for h in _hist_before]
      and evo_store.current(conn, _g_name)["version"] == _cur_before["version"],
      f"ver={_evc_before}->{conn.execute('SELECT COUNT(*) AS n FROM evo_versions').fetchone()['n']}"
      f" blob={_blob_before}->{evo_store.blob_count()}")

_del2 = evo_store.delete(conn, _g_name)
check("226 重复删除幂等 (不报错/不加版本)",
      _del2["changed"] is False
      and conn.execute("SELECT COUNT(*) AS n FROM evo_versions").fetchone()["n"] == _evc_before,
      str(_del2))

_inc = [x for x in evo_store.ls(conn, include_deleted=True) if x["name"] == _g_name]
check("227 显式含墓碑时可见且带墓碑字段",
      len(_inc) == 1 and bool(_inc[0].get("deleted_at")) and "renamed_to" in _inc[0],
      str(_inc))

_rest = evo_store.restore(conn, _g_name)
check("228 恢复后回到默认清单且当前版本不变",
      _rest["changed"] is True
      and _g_name in {x["name"] for x in evo_store.ls(conn)}
      and evo_store.current(conn, _g_name)["version"] == _cur_before["version"],
      str(_rest))
# 复活: 对已墓碑的名字再次 publish 应重新激活 (而非被"内容未变"早返回挡住)
evo_store.delete(conn, _g_name)
evo_store.publish(conn, _g_name, "v2 body")     # 与当前版本内容完全相同
check("229 对墓碑名字 publish 内容未变也应复活",
      _g_name in {x["name"] for x in evo_store.ls(conn)},
      str(sorted(x["name"] for x in evo_store.ls(conn))))
# 未知名字报错
try:
    evo_store.delete(conn, "no-such-asset-xyz.txt")
    _unknown_ok = False
except ValueError:
    _unknown_ok = True
check("230 删除未知名字抛 ValueError", _unknown_ok)

# ---- 231-235: 墓碑名字不得经本地缓存行重现 (tree) / 迁移不得静默复活 ----
# 复现条件: 一个已 materialize/pull 到本地缓存的名字被墓碑删除 —— 本地副本仍在盘上。
_tomb_cache_name = "tomb-cached.txt"
evo_store.publish(conn, _tomb_cache_name, "tomb cached body")
evo_store.materialize(conn, _tomb_cache_name)
check("231 墓碑前该名字在本地缓存目录里确有副本 (复现前提)",
      (evo_store.cache_dir() / _tomb_cache_name).is_file(),
      str(evo_store.cache_dir() / _tomb_cache_name))
evo_store.delete(conn, _tomb_cache_name)
check("232 有本地副本的墓碑名字不出现在默认 tree() (不得以 untracked 行重现)",
      _tomb_cache_name not in {x["name"] for x in evo_store.tree(conn)},
      str(sorted(x["name"] for x in evo_store.tree(conn)))[:200])
_tomb_inc = [x for x in evo_store.tree(conn, include_deleted=True)
             if x["name"] == _tomb_cache_name]
_tomb_ls_inc = [x for x in evo_store.ls(conn, include_deleted=True)
                if x["name"] == _tomb_cache_name]
check("233 include_deleted=True 时该名字重新出现 (索引行而非 untracked 缓存行, ls 带墓碑字段)",
      len(_tomb_inc) == 1 and _tomb_inc[0]["untracked"] is False
      and _tomb_inc[0]["version"] > 0
      and len(_tomb_ls_inc) == 1 and bool(_tomb_ls_inc[0].get("deleted_at")),
      str(_tomb_inc))
_tomb_ver_before = conn.execute(
    "SELECT COUNT(*) AS n FROM evo_versions WHERE name=?",
    (_tomb_cache_name,)).fetchone()["n"]
_mig_out2 = evo_store.migrate_cache_files(conn)
check("234 migrate_cache_files 不复活墓碑名字 (不加版本 / 不清墓碑 / 仍在默认清单外)",
      _tomb_cache_name not in [m["name"] for m in _mig_out2]
      and _tomb_cache_name not in {x["name"] for x in evo_store.ls(conn)}
      and bool(evo_store.current(conn, _tomb_cache_name)["deleted_at"])
      and conn.execute("SELECT COUNT(*) AS n FROM evo_versions WHERE name=?",
                       (_tomb_cache_name,)).fetchone()["n"] == _tomb_ver_before,
      f"mig={[m['name'] for m in _mig_out2]} ver={_tomb_ver_before}->"
      f"{conn.execute('SELECT COUNT(*) AS n FROM evo_versions WHERE name=?', (_tomb_cache_name,)).fetchone()['n']}")
# 没有本地副本的墓碑同样默认不可见、显式可见 (看板默认清单只认墓碑态)
evo_store.delete(conn, _g_name)
check("235 无本地副本的墓碑同样默认隐藏 / 显式可见",
      _g_name not in {x["name"] for x in evo_store.tree(conn)}
      and [x["name"] for x in evo_store.tree(conn, include_deleted=True)].count(_g_name) == 1,
      str([x["name"] for x in evo_store.tree(conn, include_deleted=True)])[:200])

# ---- 236-242: 乐观锁 (base_version 不一致即拒绝, 且不产生任何副作用) ----
_lk = "lock-demo.txt"
_lk_v1 = evo_store.publish(conn, _lk, "body one")
check("236 base_version 一致时放行",
      evo_store.publish(conn, _lk, "body two", base_version=_lk_v1["version"])["version"] == 2,
      str(evo_store.current(conn, _lk)["version"]))
_lk_v2 = evo_store.current(conn, _lk)["version"]
_evc_lock = conn.execute("SELECT COUNT(*) AS n FROM evo_versions WHERE name=?",
                         (_lk,)).fetchone()["n"]
try:
    evo_store.publish(conn, _lk, "body three", base_version=_lk_v1["version"])   # 陈旧
    _conflict_ok = False
    _conf = None
except evo_store.VersionConflict as e:
    _conflict_ok = True
    _conf = e
check("237 陈旧 base_version 抛 VersionConflict 并带当前版本号",
      _conflict_ok and _conf is not None and _conf.current_version == _lk_v2
      and _conf.base_version == _lk_v1["version"],
      f"{_conf!r}")
check("238 冲突不产生新版本、不改当前指针",
      conn.execute("SELECT COUNT(*) AS n FROM evo_versions WHERE name=?",
                   (_lk,)).fetchone()["n"] == _evc_lock
      and evo_store.current(conn, _lk)["version"] == _lk_v2,
      str(evo_store.current(conn, _lk)["version"]))
try:
    evo_store.publish(conn, "lock-new-never-exists.txt", "x", base_version=1)
    _new_conflict_ok = False
except evo_store.VersionConflict as e:
    _new_conflict_ok = (e.current_version is None)
check("239 对不存在的资产指定 base_version 也冲突 (current_version=None)",
      _new_conflict_ok)
check("240 base_version=None 时行为不变 (向后兼容)",
      evo_store.publish(conn, _lk, "body four", base_version=None)["version"] == _lk_v2 + 1,
      str(evo_store.current(conn, _lk)["version"]))
_lk_v3 = evo_store.current(conn, _lk)["version"]
try:
    evo_store.delete(conn, _lk, base_version=_lk_v1["version"])   # 陈旧
    _del_conflict_ok = False
except evo_store.VersionConflict:
    _del_conflict_ok = True
check("241 删除也受乐观锁保护 (陈旧 base_version 被拒)",
      _del_conflict_ok and _lk in {x["name"] for x in evo_store.ls(conn)},
      str(sorted(x["name"] for x in evo_store.ls(conn))))
check("242 删除带正确 base_version 时放行",
      evo_store.delete(conn, _lk, base_version=_lk_v3)["changed"] is True
      and _lk not in {x["name"] for x in evo_store.ls(conn)})

# ---- 243-245: 墓碑态下带 base_version 的写同样判冲突 (删除不产生新版本 → 版本号相同也代表视图过期) ----
# 复现: A 读到 v1; B 删除(墓碑, 版本号仍是 v1); A 拿 base_version=1 发布 —— 版本比对会通过,
# 若不额外判墓碑, A 的写会静默复活被删资产 (lost update)。这里要求判冲突且墓碑原样保留。
_tb = "lock-tomb-demo.txt"
evo_store.publish(conn, _tb, "tomb body one")
_tb_v1 = evo_store.current(conn, _tb)["version"]
evo_store.delete(conn, _tb)
_tb_ver_after_del = evo_store.current(conn, _tb)["version"]
try:
    evo_store.publish(conn, _tb, "tomb body two", base_version=_tb_v1)
    _tb_conflict_ok = False
    _tb_conf = None
except evo_store.VersionConflict as e:
    _tb_conflict_ok = True
    _tb_conf = e
check("243 墓碑名字带 stale-but-equal base_version 写入抛 VersionConflict 且 deleted is True",
      _tb_conflict_ok and _tb_conf is not None and _tb_conf.deleted is True
      and _tb_conf.current_version == _tb_v1 == _tb_ver_after_del
      and _tb_conf.base_version == _tb_v1,
      f"{_tb_conf!r} deleted={getattr(_tb_conf, 'deleted', None)}")
check("244 被拒的复活式写入不改变墓碑态 (仍在默认 ls 之外 / 不加版本 / 墓碑未清)",
      _tb not in {x["name"] for x in evo_store.ls(conn)}
      and bool(evo_store.current(conn, _tb)["deleted_at"])
      and conn.execute("SELECT COUNT(*) AS n FROM evo_versions WHERE name=?",
                       (_tb,)).fetchone()["n"] == 1,
      f"ls={sorted(x['name'] for x in evo_store.ls(conn))} "
      f"deleted_at={evo_store.current(conn, _tb)['deleted_at']!r} "
      f"versions={conn.execute('SELECT COUNT(*) AS n FROM evo_versions WHERE name=?', (_tb,)).fetchone()['n']}")
check("245 不带 base_version 的 publish 仍能复活墓碑名字 (刻意保留的 re-create 路径)",
      evo_store.publish(conn, _tb, "tomb body two")["changed"] is True
      and _tb in {x["name"] for x in evo_store.ls(conn)}
      and not evo_store.current(conn, _tb)["deleted_at"],
      f"deleted_at={evo_store.current(conn, _tb)['deleted_at']!r}")

# ---- 246-252: 改名语义 (新名字发 v1 + 旧名墓碑 + renamed_to, 历史不迁移) ----
_rn_old, _rn_new = "rename-old.txt", "rename-new.txt"
evo_store.publish(conn, _rn_old, "renamed body")
evo_store.publish(conn, _rn_old, "renamed body v2")
_rn_cur = evo_store.current(conn, _rn_old)
_rn_hist_old = [h["version"] for h in evo_store.history(conn, _rn_old)]

_rn = evo_store.rename(conn, _rn_old, _rn_new, base_version=_rn_cur["version"])
check("246 新名字以当前内容发布为 v1",
      _rn["new_name"] == _rn_new and _rn["version"] == 1
      and evo_store.resolve(conn, _rn_new)["content"] == "renamed body v2",
      f"{_rn}")
check("247 旧名字从默认清单消失且已墓碑",
      _rn_old not in {x["name"] for x in evo_store.ls(conn)}
      and bool(evo_store.current(conn, _rn_old)["deleted_at"]),
      str(evo_store.current(conn, _rn_old)))
_old_row = [x for x in evo_store.ls(conn, include_deleted=True) if x["name"] == _rn_old][0]
check("248 旧名字墓碑记录 renamed_to 指向新名字 (可追溯)",
      _old_row.get("renamed_to") == _rn_new, str(_old_row))
check("249 改名不迁移历史: 旧名历史不变, 新名历史从 v1 开始",
      [h["version"] for h in evo_store.history(conn, _rn_old)] == _rn_hist_old
      and [h["version"] for h in evo_store.history(conn, _rn_new)] == [1],
      f"old={[h['version'] for h in evo_store.history(conn, _rn_old)]}"
      f" new={[h['version'] for h in evo_store.history(conn, _rn_new)]}")
check("250 改名保留 kind",
      evo_store.current(conn, _rn_new)["kind"] == _rn_cur["kind"],
      f"{evo_store.current(conn, _rn_new)['kind']} vs {_rn_cur['kind']}")
# 目标名已是活跃资产 -> 拒绝, 且两侧都不变
_pn = "rename-busy.txt"
evo_store.publish(conn, _pn, "busy body")
_pn_cur = evo_store.current(conn, _pn)
try:
    evo_store.rename(conn, _rn_new, _pn)
    _busy_ok = False
except evo_store.NameConflict as e:
    _busy_ok = (e.name == _pn)
check("251 目标名冲突时拒绝且两侧均不变",
      _busy_ok
      and evo_store.current(conn, _pn)["version"] == _pn_cur["version"]
      and [h["version"] for h in evo_store.history(conn, _pn)] == [1]
      and _rn_new in {x["name"] for x in evo_store.ls(conn)},
      f"busy={evo_store.current(conn, _pn)['version']}")
# 改名旧名受乐观锁保护
try:
    evo_store.rename(conn, _rn_new, "rename-other.txt", base_version=999)
    _rn_lock_ok = False
except evo_store.VersionConflict:
    _rn_lock_ok = True
check("252 改名旧名受乐观锁保护 (陈旧 base_version 被拒)",
      _rn_lock_ok
      and _rn_new in {x["name"] for x in evo_store.ls(conn)}
      and "rename-other.txt" not in {x["name"] for x in evo_store.ls(conn)})

# ---- 253-259: 内容对象缺失/损坏时拒绝改名 (不静默产出空资产) + 守卫必须窄 ----
_rc_src, _rc_dst = "rename-corrupt-src.txt", "rename-corrupt-dst.txt"
_rc_body = "rename corrupt body"
_rc_ver = evo_store.publish(conn, _rc_src, _rc_body)["version"]
_rc_hash = evo_store.current(conn, _rc_src)["hash"]
# 篡改磁盘上的内容对象 → 哈希不匹配, get_blob 按设计返回 None
evo_store._blob_path(_rc_hash).write_text("tampered body", encoding="utf-8")
_rc_missing = evo_store.get_blob(_rc_hash) is None
try:
    evo_store.rename(conn, _rc_src, _rc_dst, base_version=_rc_ver)
    _rc_err = None
except ValueError as e:
    _rc_err = e
check("253 内容对象损坏 (get_blob 返回 None) 时改名抛 ValueError",
      _rc_missing and isinstance(_rc_err, ValueError)
      and "拒绝改名" in str(_rc_err),
      f"missing={_rc_missing} err={_rc_err!r}")
check("254 被拒的改名不产生目标名字 (默认清单无, 且无新版本行)",
      _rc_dst not in {x["name"] for x in evo_store.ls(conn)}
      and conn.execute("SELECT COUNT(*) AS n FROM evo_versions WHERE name=?",
                       (_rc_dst,)).fetchone()["n"] == 0,
      f"target_in_ls={_rc_dst in {x['name'] for x in evo_store.ls(conn)}}")
_rc_cur = evo_store.current(conn, _rc_src)
check("255 被拒的改名不半应用: 旧名仍活跃、墓碑未写、版本与历史不变",
      _rc_src in {x["name"] for x in evo_store.ls(conn)}
      and not (_rc_cur.get("deleted_at") or "")
      and not (_rc_cur.get("renamed_to") or "")
      and _rc_cur["version"] == _rc_ver
      and [h["version"] for h in evo_store.history(conn, _rc_src)] == [_rc_ver],
      f"deleted_at={_rc_cur.get('deleted_at')!r} renamed_to={_rc_cur.get('renamed_to')!r}"
      f" version={_rc_cur['version']}")
# 守卫必须窄: 合法空内容 (hash=sha256("")) 读回 "" 而非 None, 不得被拒
_rc_e_src, _rc_e_dst = "rename-empty-src.txt", "rename-empty-dst.txt"
_rc_e_ver = evo_store.publish(conn, _rc_e_src, "")["version"]
_rc_e = evo_store.rename(conn, _rc_e_src, _rc_e_dst, base_version=_rc_e_ver)
check("256 合法空内容改名仍成功 (空串 != 缺失, 守卫不误伤)",
      _rc_e["changed"] is True
      and evo_store.current(conn, _rc_e_dst)["hash"] == evo_store.sha256_text("")
      and evo_store.resolve(conn, _rc_e_dst)["content"] == "",
      f"{_rc_e}")
# 守卫必须窄: ref 类无 blob, 走引用搬运而非读内容
_rc_r_src, _rc_r_dst = "rename-ref-src.txt", "rename-ref-dst.txt"
evo_store.publish(conn, _rc_r_src, None, ref="scripts/run.sh")
_rc_r = evo_store.rename(conn, _rc_r_src, _rc_r_dst)
check("257 ref 类改名仍走引用搬运 (无 blob, 守卫不误伤)",
      _rc_r["changed"] is True
      and evo_store.current(conn, _rc_r_dst)["ref"] == "scripts/run.sh"
      and evo_store.current(conn, _rc_r_dst)["hash"] == ""
      and evo_store.resolve(conn, _rc_r_dst)["content"] is None,
      f"{_rc_r}")
# 守卫位置之后的原有路径: 同名改名幂等 (守卫之前的早返回)
_same = evo_store.rename(conn, _rn_new, _rn_new)
check("258 同名改名仍幂等返回 changed=False (守卫之前的早返回不变)",
      _same["changed"] is False
      and _same["version"] == evo_store.current(conn, _rn_new)["version"]
      and [h["version"] for h in evo_store.history(conn, _rn_new)] == [1],
      f"{_same}")
# 守卫不改变「墓碑目标名可作目的地」: 目标名续用自身历史 (历史不迁移的另一面)
_rc_t_src, _rc_t_dst = _rn_new, "rename-tomb-dst.txt"
evo_store.publish(conn, _rc_t_dst, "tomb dst body")
evo_store.delete(conn, _rc_t_dst)
_rc_t_hist = [h["version"] for h in evo_store.history(conn, _rc_t_dst)]
_rc_t = evo_store.rename(conn, _rc_t_src, _rc_t_dst)
check("259 墓碑目标名仍可作改名目的地 (续用自身历史, 墓碑被清)",
      _rc_t["changed"] is True and _rc_t["version"] == max(_rc_t_hist) + 1
      and [h["version"] for h in evo_store.history(conn, _rc_t_dst)]
      == [max(_rc_t_hist) + 1] + _rc_t_hist
      and not evo_store.current(conn, _rc_t_dst)["deleted_at"],
      f"{_rc_t} hist={_rc_t_hist}")

# ---- 260-274: REST 原地增删改查 + 乐观锁 409 + 可编辑性下发 ----
try:
    from fastapi.testclient import TestClient
    import tempfile as _tf2
    _dbp2 = os.path.join(_tf2.mkdtemp(prefix="evocrud_"), "w.db")
    from lclone import web as _wm2
    _tc2 = TestClient(_wm2.create_app(_dbp2))

    _r = _tc2.post("/api/evolution/publish", json={"name": "u.txt", "content": "v1"})
    _v1 = _r.json()["result"]["version"]
    check("260 REST publish 后 index 下发 editable/base_version",
          (lambda it: it["editable"] is True and it["editable_reason"] == ""
           and it["base_version"] == _v1)(
              [x for x in _tc2.get("/api/evolution/index").json()["items"]
               if x["name"] == "u.txt"][0]))
    # 乐观锁: 陈旧 base_version -> 409 且带 current_version
    _c = _tc2.post("/api/evolution/publish",
                   json={"name": "u.txt", "content": "v2", "base_version": 999})
    check("261 REST 陈旧 base_version -> 409",
          _c.status_code == 409 and _c.json()["detail"]["current_version"] == _v1,
          f"{_c.status_code} {_c.text[:80]}")
    check("262 REST 冲突不产生新版本",
          _tc2.get("/api/evolution/history?name=u.txt").json()["items"][0]["version"] == _v1)
    # 删除 -> 默认清单不可见 / include_deleted 可见
    _tc2.post("/api/evolution/delete", json={"name": "u.txt", "base_version": _v1})
    check("263 REST 删除后默认 index 不可见",
          "u.txt" not in [x["name"] for x in _tc2.get("/api/evolution/index").json()["items"]])
    _inc2 = [x for x in _tc2.get("/api/evolution/index?include_deleted=true").json()["items"]
             if x["name"] == "u.txt"]
    check("264 REST include_deleted 可见且带 deleted_at",
          len(_inc2) == 1 and bool(_inc2[0]["deleted_at"]), str(_inc2))
    # 对已墓碑资产带 base_version 的 DELETE -> 409 (不是幂等 200)
    _c2 = _tc2.post("/api/evolution/delete", json={"name": "u.txt", "base_version": _v1})
    check("265 REST 对已墓碑资产带 base_version 的 DELETE -> 409",
          _c2.status_code == 409 and _c2.json()["detail"]["deleted"] is True,
          f"{_c2.status_code} {_c2.text[:80]}")
    check("266 REST restore 恢复",
          _tc2.post("/api/evolution/restore", json={"name": "u.txt"}).json()["result"]["changed"] is True
          and "u.txt" in [x["name"] for x in _tc2.get("/api/evolution/index").json()["items"]])
    # 改名
    _rn2 = _tc2.post("/api/evolution/rename",
                     json={"name": "u.txt", "new_name": "u2.txt"}).json()["result"]
    check("267 REST 改名 -> 新名字 v1 且旧名消失",
          _rn2["new_name"] == "u2.txt" and _rn2["version"] == 1
          and "u.txt" not in [x["name"] for x in _tc2.get("/api/evolution/index").json()["items"]])
    check("268 REST 改名到空白目标 -> 400",
          _tc2.post("/api/evolution/rename",
                    json={"name": "u2.txt", "new_name": "   "}).status_code == 400)
    # 目标名冲突 -> 409
    _tc2.post("/api/evolution/publish", json={"name": "busy.txt", "content": "b"})
    check("269 REST 改名目标活跃 -> 409",
          _tc2.post("/api/evolution/rename",
                    json={"name": "u2.txt", "new_name": "busy.txt"}).status_code == 409)
    # 二进制 -> editable false / binary
    _tc2.post("/api/evolution/publish", json={"name": "bin.txt", "content": "abc\x00def"})
    _bin = [x for x in _tc2.get("/api/evolution/index").json()["items"] if x["name"] == "bin.txt"][0]
    check("270 REST 含 NUL 内容 -> editable=false / binary",
          _bin["editable"] is False and _bin["editable_reason"] == "binary", str(_bin))
    # content 也下发 editable/base_version
    _cc = _tc2.get("/api/evolution/content?name=busy.txt").json()
    check("271 REST content 下发 editable/base_version",
          _cc["editable"] is True and _cc["base_version"] == 1,
          str({k: _cc[k] for k in ("editable", "base_version")}))
    # /api/evolutions 形状不变
    _its = _tc2.get("/api/evolutions").json()["items"]
    _need = {"name", "ext", "size", "mtime", "is_dir", "children", "content"}
    check("272 REST /api/evolutions 形状不变",
          bool(_its) and _need <= set(_its[0].keys()), str(sorted(_its[0].keys())))

    # 关键陷阱回归: **非法 UTF-8 且无 NUL** —— 若用 get_blob (errors="replace") 判定,
    # 非法字节会被静默替换成替换字符, 于是永远判成可编辑。内容只能从 API 进 (JSON 必为
    # 合法 UTF-8), 所以直接造一个哈希匹配、字节非法的 blob 并挂上索引行来复现该场景。
    import hashlib as _hl2
    import sqlite3 as _sq2
    _bad_raw = b"abc\xff\xfe def"          # 非法 UTF-8, 且不含 NUL
    _bad_h = _hl2.sha256(_bad_raw).hexdigest()
    _bp2 = evo_store._blob_path(_bad_h)
    _bp2.parent.mkdir(parents=True, exist_ok=True)
    _bp2.write_bytes(_bad_raw)
    _db2 = _sq2.connect(_dbp2)
    _db2.execute("INSERT INTO evo_versions(name, version, hash, size, kind, project_id,"
                 " ref, message, source_ref) VALUES (?,?,?,?,?,?,?,?,?)",
                 ("bad-utf8.bin", 1, _bad_h, len(_bad_raw), "other", None, "", "", ""))
    _db2.execute("INSERT INTO evo_current(name, version, updated_at, deleted_at, renamed_to)"
                 " VALUES (?,?,?,'','')", ("bad-utf8.bin", 1, "2026-01-01 00:00:00"))
    _db2.commit()
    _db2.close()
    _badrow = [x for x in _tc2.get("/api/evolution/index").json()["items"]
               if x["name"] == "bad-utf8.bin"][0]
    check("273 REST 非法 UTF-8 (无 NUL) -> editable=false / binary",
          _badrow["editable"] is False and _badrow["editable_reason"] == "binary",
          str({k: _badrow[k] for k in ("editable", "editable_reason")}))
    check("274 get_blob(replace 解码) 掩盖非法 UTF-8, get_blob_bytes 暴露原始字节",
          evo_store.get_blob(_bad_h) is not None
          and evo_store.get_blob_bytes(_bad_h) == _bad_raw)

    # 274b/274c (final review I3): `ref` 与 `missing` 这两条**只可能由 web.py 的
    # `_editability_of` 产出**的原因码此前零断言 —— `evolutions.editability()` 只会返回
    # ""/too_large/binary, 而 delta spec「可编辑内容判定」给 ref 与 missing 各有一个场景。
    # 光凭"ref 资产能改名"证明不了原因码本身 (那证明的是别的需求)。
    _tc2.post("/api/evolution/publish", json={"name": "r.txt", "ref": "scripts/run.sh"})
    _refrow = [x for x in _tc2.get("/api/evolution/index").json()["items"]
               if x["name"] == "r.txt"][0]
    check("274b REST 引用类资产 -> editable=false / ref",
          _refrow["editable"] is False and _refrow["editable_reason"] == "ref",
          str({k: _refrow[k] for k in ("editable", "editable_reason")}))
    # missing: 内容对象缺失(或与其哈希不匹配)。这里直接**删掉**内容库里那个对象。
    # blob 路径按模块文档/基线 spec 的公开布局自己拼 (`<blob_dir>/<hash 前 2 位>/<hash>`),
    # 刻意不 import 私有 `_blob_path`; 并把"删之前它确实在"写进断言 —— 否则布局一变,
    # 这条检查会静默退化成"其实什么都没删"却依然绿。
    _miss_content = "missing-blob-payload-4f1c9d (unique)"
    _tc2.post("/api/evolution/publish", json={"name": "miss.txt", "content": _miss_content})
    _miss_h = [x for x in _tc2.get("/api/evolution/index").json()["items"]
               if x["name"] == "miss.txt"][0]["hash"]
    _miss_p = evo_store.blob_dir() / _miss_h[:2] / _miss_h
    _miss_existed = _miss_p.is_file() and evo_store.get_blob_bytes(_miss_h) is not None
    _miss_p.unlink()
    _missrow = [x for x in _tc2.get("/api/evolution/index").json()["items"]
                if x["name"] == "miss.txt"][0]
    check("274c REST 内容对象缺失 -> editable=false / missing",
          _miss_existed and _missrow["editable"] is False
          and _missrow["editable_reason"] == "missing",
          f"existed={_miss_existed} path={_miss_p} "
          + str({k: _missrow[k] for k in ("editable", "editable_reason")}))

    # ---- 275-280: 服务端故障必须 5xx, 领域异常保持既有 409/400 映射 ----
    # 端点的异常映射必须**窄**: 只把领域异常 (VersionConflict/NameConflict/ValueError)
    # 翻成 409/400; 其余 (sqlite3.OperationalError、未来改动引入的 TypeError 等) 是
    # 服务端故障, 必须冒泡成 500 —— 否则真故障会被报成"你的请求有问题", 且 5xx 永远
    # 不进日志/指标。TestClient 默认 raise_server_exceptions=True 会把未处理异常直接
    # 抛进测试进程 (看不到响应), 故同一 app 另起一个关掉该开关的客户端来观察 500。
    _tc5 = TestClient(_wm2.create_app(_dbp2), raise_server_exceptions=False)

    def _raise_fault(*_a, **_k):
        raise RuntimeError("模拟服务端故障: database is locked")

    _fault_cases = [
        ("275", "/api/evolution/publish", "publish", {"name": "fault.txt", "content": "x"}),
        ("276", "/api/evolution/delete", "delete", {"name": "fault.txt"}),
        ("277", "/api/evolution/restore", "restore", {"name": "fault.txt"}),
        ("278", "/api/evolution/rename", "rename",
         {"name": "fault.txt", "new_name": "fault2.txt"}),
    ]
    for _num, _path, _fn, _payload in _fault_cases:
        _orig_fn = getattr(evo_store, _fn)
        setattr(evo_store, _fn, _raise_fault)
        try:
            _rf = _tc5.post(_path, json=_payload)
        finally:
            setattr(evo_store, _fn, _orig_fn)  # 必须恢复, 否则后续检查全被污染
        check(f"{_num} REST {_fn} 内部故障 -> 500 (不伪装成 400)",
              _rf.status_code == 500, f"{_rf.status_code} {_rf.text[:80]}")

    # 领域异常仍按原样映射 (窄捕获不得把领域错误也变成 500)
    _nf = _tc2.post("/api/evolution/delete", json={"name": "no-such-asset.txt"})
    check("279 REST 删除不存在资产 (ValueError) -> 400",
          _nf.status_code == 400, f"{_nf.status_code} {_nf.text[:80]}")
    _tc2.post("/api/evolution/publish", json={"name": "stale.txt", "content": "s1"})
    _st = _tc2.post("/api/evolution/delete", json={"name": "stale.txt", "base_version": 999})
    check("280 REST 活跃资产陈旧 base_version 的 DELETE -> 409",
          _st.status_code == 409 and _st.json()["detail"]["current_version"] == 1,
          f"{_st.status_code} {_st.text[:80]}")
    # publish 内部重试版本碰撞后重抛的 sqlite3.IntegrityError 是**服务端故障**, 必须 500
    import sqlite3 as _sq3

    def _raise_integrity(*_a, **_k):
        raise _sq3.IntegrityError("UNIQUE constraint failed: evo_versions.name, version")

    _orig_pub = evo_store.publish
    evo_store.publish = _raise_integrity
    try:
        _ri = _tc5.post("/api/evolution/publish", json={"name": "fault.txt", "content": "y"})
    finally:
        evo_store.publish = _orig_pub
    check("281 REST publish 重抛 sqlite3.IntegrityError -> 500 (非领域异常不映射 400)",
          _ri.status_code == 500, f"{_ri.status_code} {_ri.text[:80]}")
except ImportError as e:  # 无 fastapi 环境跳过
    print(f"SKIP 260-281 (缺依赖: {e})")

# ---- 282-287: CLI / 后端适配器对齐 (delete / restore / rename + base_version 转发) ----
_lb = evo_store.LocalBackend(conn)
_lb.publish("cli-x.txt", "cli body")
_lbx_cur = _lb.index()
_lbx_v = [x for x in _lbx_cur if x["name"] == "cli-x.txt"][0]["version"]
check("282 LocalBackend.delete 墓碑",
      _lb.delete("cli-x.txt", base_version=_lbx_v)["changed"] is True
      and "cli-x.txt" not in {x["name"] for x in _lb.index()})
check("283 LocalBackend.restore 恢复",
      _lb.restore("cli-x.txt")["changed"] is True
      and "cli-x.txt" in {x["name"] for x in _lb.index()})
check("284 LocalBackend.rename 改名",
      _lb.rename("cli-x.txt", "cli-y.txt")["new_name"] == "cli-y.txt"
      and "cli-y.txt" in {x["name"] for x in _lb.index()})
# base_version 必须经适配器转发到领域层
try:
    _lb.publish("cli-y.txt", "other", base_version=999)
    _lb_bv_ok = False
except evo_store.VersionConflict:
    _lb_bv_ok = True
check("285 LocalBackend.publish 转发 base_version", _lb_bv_ok)

# HttpBackend: 用 monkeypatch urlopen 断言打到正确的端点 (照 183-186 的写法)
_seen2 = {}
_orig_urlopen2 = urllib.request.urlopen


class _FakeResp2:
    def __init__(self, payload):
        self._b = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_urlopen2(req, timeout=None):
    _seen2["url"] = req.full_url
    _seen2["method"] = req.get_method()
    _seen2["body"] = req.data.decode("utf-8") if req.data else ""
    if req.full_url.endswith("/api/evolution/rename"):
        return _FakeResp2({"result": {"old_name": "a.txt", "new_name": "b.txt",
                                      "version": 1, "hash": "h", "changed": True}})
    return _FakeResp2({"result": {"name": "a.txt", "changed": True,
                                  "deleted_at": "t", "version": 1}})


urllib.request.urlopen = _fake_urlopen2
try:
    _hb2 = evo_store.HttpBackend("http://x", token="t")
    _hb2.delete("a.txt", base_version=3)
    _del_url, _del_body = _seen2["url"], _seen2["body"]
    _hb2.rename("a.txt", "b.txt")
    _ren_url = _seen2["url"]
    _hb2.publish("a.txt", "c", base_version=4)
    _pub_body = _seen2["body"]
finally:
    urllib.request.urlopen = _orig_urlopen2
check("286 HttpBackend.delete/rename 打到正确端点",
      _del_url.endswith("/api/evolution/delete") and "/api/evolution/rename" in _ren_url,
      f"{_del_url} | {_ren_url}")
check("287 HttpBackend 转发 base_version",
      '"base_version": 3' in _del_body and '"base_version": 4' in _pub_body,
      f"{_del_body[:60]} | {_pub_body[:60]}")


# CLI 三个子命令
def _cli_evo(*argv):
    _buf = io.StringIO()
    with contextlib.redirect_stdout(_buf):
        cli.main(["evolution", *argv, "--db", dbp, "--local"])
    return _buf.getvalue()


cli_out = _cli_evo("add", "cli-z.txt", "--content", "z body")
cli_out = _cli_evo("delete", "cli-z.txt")
check("288 CLI evolution delete", "已墓碑" in cli_out or "删除" in cli_out, cli_out[:80])
cli_out = _cli_evo("restore", "cli-z.txt")
check("289 CLI evolution restore", "已恢复" in cli_out or "恢复" in cli_out, cli_out[:80])
cli_out = _cli_evo("rename", "cli-z.txt", "cli-w.txt")
check("290 CLI evolution rename", "cli-w.txt" in cli_out, cli_out[:80])

# ---- 291: HttpBackend.restore 打到正确端点 (此前零覆盖) ----
_seen3 = {}
_orig_urlopen3 = urllib.request.urlopen


def _fake_urlopen3(req, timeout=None):
    _seen3["url"] = req.full_url
    _seen3["body"] = req.data.decode("utf-8") if req.data else ""
    return _FakeResp2({"result": {"name": "a.txt", "changed": True, "version": 1}})


urllib.request.urlopen = _fake_urlopen3
try:
    _hb3 = evo_store.HttpBackend("http://x", token="t")
    _hb3.restore("a.txt")
    _rst_url, _rst_body = _seen3["url"], _seen3["body"]
finally:
    urllib.request.urlopen = _orig_urlopen3
check("291 HttpBackend.restore 打到 /api/evolution/restore",
      _rst_url.endswith("/api/evolution/restore") and '"name": "a.txt"' in _rst_body,
      f"{_rst_url} | {_rst_body[:50]}")

# ---- 292-295: 远端(HTTP)模式下领域冲突也必须是 SystemExit, 不得泄漏 traceback ----
# HttpBackend._req 把 HTTP 错误(含 Task 6 的 409)统一抛成 RuntimeError; CLI 若不捕获
# 就会裸 traceback 冒泡 —— 远端是本项目的常规生产路径, 因此必须与 rollback 同款处理。
import urllib.error  # noqa: E402  (文件顶部只 import 了 urllib.request)


def _fake_urlopen409(req, timeout=None):
    """复刻真实 409: HTTPError → HttpBackend._req 转 RuntimeError。"""
    body = json.dumps({"detail": "版本冲突: 基于旧版本"}).encode("utf-8")
    raise urllib.error.HTTPError(req.full_url, 409, "Conflict", {}, io.BytesIO(body))


_prev_env3 = {k: os.environ.get(k) for k in ("LCLONE_WEB_URL", "LCLONE_API_KEY")}
os.environ["LCLONE_WEB_URL"] = "http://brain409.example:8000"
os.environ["LCLONE_API_KEY"] = "tok-409"
cfg_mod._loaded = False
# publish_local 先读本地缓存文件再发请求, 所以要先落一个 (否则会提前 ValueError)
(pathlib.Path(os.environ["LCLONE_EVO_DIR"]) / "x.txt").write_text("remote body",
                                                                 encoding="utf-8")
_orig_urlopen4 = urllib.request.urlopen
urllib.request.urlopen = _fake_urlopen409


def _remote_cli(*argv):
    """跑一次远端 CLI; 返回 (SystemExit 消息, None) 或 (None, 泄漏出来的异常描述)。"""
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            cli.main(["evolution", *argv, "--db", dbp])
    except SystemExit as e:
        return str(e), None
    except BaseException as e:  # noqa: BLE001 - 抓的就是「不该冒出来的东西」
        return None, f"{type(e).__name__}: {e}"
    return None, "(没抛异常)"


try:
    _m_del, _l_del = _remote_cli("delete", "x.txt", "--base-version", "3")
    _m_rst, _l_rst = _remote_cli("restore", "x.txt")
    _m_rn, _l_rn = _remote_cli("rename", "x.txt", "y.txt", "--base-version", "3")
    _m_pub, _l_pub = _remote_cli("publish", "x.txt", "--base-version", "3")
finally:
    urllib.request.urlopen = _orig_urlopen4
    for _k, _v in _prev_env3.items():
        if _v is None:
            os.environ.pop(_k, None)
        else:
            os.environ[_k] = _v
    cfg_mod._loaded = False

# 「409」出现在消息里 = 请求确实走到了 HTTP (而不是本地提前报错), 且消息非空
check("292 CLI 远端 delete 409 → SystemExit(消息)",
      _l_del is None and "409" in (_m_del or ""), f"{_m_del!r} | {_l_del}")
check("293 CLI 远端 restore 409 → SystemExit(消息)",
      _l_rst is None and "409" in (_m_rst or ""), f"{_m_rst!r} | {_l_rst}")
check("294 CLI 远端 rename 409 → SystemExit(消息)",
      _l_rn is None and "409" in (_m_rn or ""), f"{_m_rn!r} | {_l_rn}")
check("295 CLI 远端 publish --base-version 409 → SystemExit(消息)",
      _l_pub is None and "409" in (_m_pub or ""), f"{_m_pub!r} | {_l_pub}")

# ---- 296-298: 前端进化面板编辑器 (无构建单文件 HTML, 由 node + DOM 桩直测行为) ----
_fe_html = ROOT / "lclone" / "frontend" / "index.html"
_fe_test = ROOT / "tests" / "frontend_evo_test.js"
_fe_text = _fe_html.read_text(encoding="utf-8")
# 前端行为 (可编辑→就地编辑 / 不可编辑→只读 / 409 不丢内容) 本身是 spec 要求, 故 node 缺失时
# 本检查**失败**而不是静默跳过: 静默 SKIP 会让"未验证"看起来像"已验证"。
_node = shutil.which("node")
if _node:
    _fe_run = subprocess.run([_node, str(_fe_test), str(_fe_html)],
                             capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=180)
    _fe_out = (_fe_run.stdout or "") + (_fe_run.stderr or "")
    _fe_ok = _fe_run.returncode == 0
else:
    _fe_ok, _fe_out = False, "node 不可用: 前端行为测试无法执行"
# extra 只带桩的末行 (FRONTEND OK n): 整段 _fe_out 会把子进程的 PASS 行灌进外层输出,
# 让"外层 PASS 计数"出现 313 vs 303 的歧义。
_fe_tail = _fe_out.strip().splitlines()[-1] if _fe_out.strip() else ""
check("296 前端进化面板行为契约 (node 执行内联脚本 + 最小 DOM 桩)", _fe_ok and "FRONTEND OK" in _fe_out,
      _fe_tail if _fe_ok else _fe_out[-600:])

# 前端引用的 /api/evolution/* 必须真实注册 (防打错 URL 直到浏览器里才暴露)
# 复用已有客户端 (再 create_app 一次会白建一个 app, 且断言的可能不是被服务的那份)
_evo_routes = {getattr(r, "path", "") for r in _tc2.app.routes}
_fe_called = sorted(set(re.findall(r"['\"](/api/evolution/[a-z]+)", _fe_text)))
check("297 前端引用的 /api/evolution/* 端点都已注册",
      bool(_fe_called) and all(p in _evo_routes for p in _fe_called),
      f"{_fe_called} vs {sorted(_evo_routes)}")

# 被测试的必须就是被服务的那份文件 (GET / 由 FileResponse 提供)
_ir = _tc2.get("/")
check("298 GET / 提供的就是被测试的 index.html",
      _ir.status_code == 200 and _ir.content == _fe_html.read_bytes(),
      f"status={_ir.status_code} served={len(_ir.content)} disk={len(_fe_html.read_bytes())}")

# ---- 299-300: 前端工具条所依赖的后端语义 (新建重名 409 / 墓碑列举) ----
_pn = _tc2.post("/api/evolution/publish", json={"name": "tn-new.txt", "content": "n1", "only_if_new": True})
_vn = _pn.json()["result"]["version"]
_pn2 = _tc2.post("/api/evolution/publish", json={"name": "tn-new.txt", "content": "n2", "only_if_new": True})
_h2 = _tc2.get("/api/evolution/history?name=tn-new.txt").json()["items"]
check("299 only_if_new: 新名字发布 v1, 活跃名再新建 -> 409 且不改动既有资产",
      _pn.status_code == 200 and _vn == 1 and _pn2.status_code == 409
      and _pn2.json()["detail"].get("name") == "tn-new.txt"
      and len(_h2) == 1 and _h2[0]["version"] == 1,
      f"{_pn.status_code}/{_vn} vs {_pn2.status_code} {_pn2.text[:80]} hist={[h['version'] for h in _h2]}")
# 墓碑名: only_if_new 不拒绝 (沿用自身历史递增, 即"重新激活"), 且新名字仍不受限
_tc2.post("/api/evolution/delete", json={"name": "tn-new.txt", "base_version": _vn})
_pn3 = _tc2.post("/api/evolution/publish", json={"name": "tn-new.txt", "content": "n3", "only_if_new": True})
_tn_l = [x for x in _tc2.get("/api/evolution/index?include_deleted=true").json()["items"]
         if x["name"] == "tn-new.txt"]
_tn = _tn_l[0] if _tn_l else {}   # 缺项 -> 空 dict, 让断言给出干净 FAIL 而不是 IndexError 回溯
check("299b only_if_new 对墓碑名放行 (续用历史版本号并清墓碑)",
      _pn3.status_code == 200 and _pn3.json()["result"]["version"] == _vn + 1 and _tn.get("deleted_at") == "",
      f"{_pn3.status_code} {_pn3.text[:80]} {_tn.get('deleted_at')!r}")

# 清单接口必须能显式列出墓碑 (Task 6 遗留未断言项; 前端「显示已删除」依赖它)
_tc2.post("/api/evolution/publish", json={"name": "tn-ren.txt", "content": "r"})
_tc2.post("/api/evolution/rename", json={"name": "tn-ren.txt", "new_name": "tn-fresh.txt"})
_tdef = {i["name"] for i in _tc2.get("/api/evolutions").json()["items"]}
_tinc = _tc2.get("/api/evolutions?include_deleted=true").json()["items"]
_keys = set(_tinc[0].keys()) if _tinc else set()
_tomb = [i for i in _tinc if i["name"] == "tn-ren.txt"]
_tren_l = [x for x in _tc2.get("/api/evolution/index?include_deleted=true").json()["items"]
           if x["name"] == "tn-ren.txt"]
_tren = _tren_l[0] if _tren_l else {}   # 同上: 前置取值不得让整测试炸成回溯
check("300 /api/evolutions?include_deleted=true 列出墓碑且形状不变, index 可追溯 renamed_to",
      "tn-ren.txt" not in _tdef and len(_tomb) == 1
      and {"name", "ext", "size", "mtime", "is_dir", "children", "content"} <= _keys
      and _tren.get("renamed_to") == "tn-fresh.txt",
      f"def={sorted(_tdef)} keys={sorted(_keys)}")

# ---- 301-302: 历史与回滚入口所依赖的后端契约 ----
_tc2.post("/api/evolution/publish", json={"name": "h1.txt", "content": "c1"})
_tc2.post("/api/evolution/publish", json={"name": "h1.txt", "content": "c2"})
_tc2.post("/api/evolution/publish", json={"name": "h1.txt", "content": "c3"})
_hh = _tc2.get("/api/evolution/history?name=h1.txt").json()["items"]
_blobdir = evo_store.blob_dir()
_blobs_before = len(list(_blobdir.glob("*"))) if _blobdir.exists() else 0
_rb = _tc2.post("/api/evolution/rollback", json={"name": "h1.txt", "version": 1})
_after = {x["name"]: x for x in _tc2.get("/api/evolution/index").json()["items"]}.get("h1.txt", {})
_blobs_after = len(list(_blobdir.glob("*"))) if _blobdir.exists() else 0
_pub4 = _tc2.post("/api/evolution/publish", json={"name": "h1.txt", "content": "c4"}).json()["result"]
check("301 回滚只改当前指针 (版本行与 blob 不变, 再发布按 max+1 续号)",
      _rb.status_code == 200 and [h["version"] for h in _hh] == [3, 2, 1]
      and _after.get("base_version") == 1
      and [h["version"] for h in _tc2.get("/api/evolution/history?name=h1.txt").json()["items"]]
      == [4, 3, 2, 1]
      and _pub4.get("version") == 4 and _blobs_after == _blobs_before,
      f"{_rb.status_code} cur={_after.get('base_version')} pub4={_pub4.get('version')} "
      f"blobs={_blobs_before}->{_blobs_after}")

# 历史版本内容可读, 且 base_version 恒为「当前」版本 (前端只读预览的依赖契约); 版本不存在 -> 404
_cv1 = _tc2.get("/api/evolution/content?name=h1.txt&version=1").json()
_c404 = _tc2.get("/api/evolution/content?name=h1.txt&version=999")
check("302 历史版本内容可取, base_version 恒为当前版本; 版本不存在 -> 404",
      _cv1.get("content") == "c1" and _cv1.get("version") == 1 and _cv1.get("base_version") == 4
      and _c404.status_code == 404,
      f"v1={_cv1.get('content')!r}/{_cv1.get('version')}/{_cv1.get('base_version')} 404={_c404.status_code}")

# ---- 303-307: Task 11 验证闸门 (前端静态规范 + 全链路端到端) ----
# 303 转义覆盖审计: 逐个 `innerHTML =` 语句取窗口, 看 `${...}` 插值是否经 esc()/evoChip()/Number()。
#     判据 = 未包裹者**恰好等于**冻结白名单 (多一个 = 有人往 innerHTML 里塞了未转义的动态值;
#     少一个 = 白名单腐烂, 也要复核)。窗口数下限防止本检查变成空转。
#
#     fix round 1 的两处收紧 (原判据的两个漏洞: "绿"被误读成"全量审计通过"):
#       F1 窗口结束条件从"该行含 ';'"改为"该行右去空以 ';' 结尾" —— 属性/内联样式里夹着的 ';'
#          不再把多行模板提前截断 (窗口只会变长, 原先捕到的插值一个都不会漏)。
#       F2 右边是**裸标识符**的 sink (`x.innerHTML = svg;` 这种拼装在别处的) 窗口内一个插值都没有,
#          旧版会静默算通过 —— 现在必须逐条登记在 _IDENT_SINKS, 新增即 FAIL。
#
#     fix round 2 的三处收紧 (F1 自己引入的 fail-open + 两类静默盲区):
#       F5 行尾注释 (`x.innerHTML = '';  // 说明`) 让"以 ';' 结尾"不成立 -> 窗口越过该行、
#          把下一条语句的 sink 吞进来; 而"取窗口后整段跳过"又让被吞的 sink 从不作为 sink 被审视。
#          三重根治: 结束条件剥离行尾注释 / 按**每处** `.innerHTML =` 建 sink / 兜底断言
#          "一个窗口里出现 >1 处 sink 就直接 FAIL"(swallow=), 防止将来再吞。
#       F6 分类 fail-closed: 每个 sink 必须"窗口内自带 ${...}(内联审计)" 或 "右侧是已登记的裸标识符"
#          或 "右侧是纯字面量(没有动态值)"; 其余(拼接/三元/调用等看不透的动态 sink) 必须按
#          (选择器, RHS 原文) 冻进 _DYN_SINKS。两张登记表都做**双向等号**(登记 == 实测), 防登记表腐烂。
#       F7 修正冻结依据文本: created_at 的 INSERT 实为 7 处, 且唯一写它的是一条**测试自身的** UPDATE。
_SAFE_INTERP = {
    "cntHtml": "调用方拼好的内部计数 HTML (只含数字与静态标记)",
    "msg": "上游已 esc(String(h.message)) (index.html:915)",
    "p.id": "DB 自增整数",
    "rail": "内部字面量 'global'/'project'",
    "v": "Number(h.version) || 0 (index.html:914)",
    # --- fix round 1 (F1 扩大可见面后新暴露的 #pending-list 两处, 逐条可证安全) ---
    "m.id": "memories.id = INTEGER PRIMARY KEY AUTOINCREMENT (db.py:39),"
            " /api/pending 原样下发 (web.py:281-283 dict(r)) -> 恒为整数, 不可能带 HTML",
    "(m.created_at||'').slice(0,16)":
        "memories.created_at = TEXT NOT NULL DEFAULT (datetime('now')) (db.py:48);"
        " 全仓 7 处 INSERT INTO memories 的列清单**都不含**该列"
        " (memory.py:105/112/283/1029, seed.py:128,"
        " scripts/migrate_note_to_insight.py:45, scripts/cleanup_memories.py:97);"
        " 唯一会写它的是**测试自身的** UPDATE memories SET created_at=datetime('now','-30 days')"
        " (tests/test_offline.py:214, 只作用于测试库), 取值仍是服务端时钟"
        " -> 恒为服务端时间戳, 用户输入进不来",
}

# F2/F6: 右边是**裸标识符**(拼装在别处)的 sink —— 必须逐条在此登记, 并说明它由谁审计或为何是本 change 之外的例外。
# 新增一条 = 新盲区 -> 必须让本检查失败, 而不是静默放过。双向等号: 登记了却不再出现 -> 也 FAIL。
_IDENT_SINKS = {
    "cntHtml": "内部计数 HTML; 由 renderSidebar 传入 ('∞' 字面量 index.html:551 /"
               " `记忆 <b>${p.mem_count}</b>${pendTag}` :555, 计数来自服务端) -> 见 _SAFE_INTERP",
    "TRASH_ICON": "文件内常量字面量 '<svg .../>' (index.html:517), 不含任何插值",
    "svg": "#graph 的 SVG 拼装 (字符串 bg 逐段累加, index.html:655-696, sink 即 :697"
           " `$('graph').innerHTML = svg;`) —— **sink 那一行本身**未被本 change 修改,"
           " 但这段拼装里**有**一处本 change 新增的插值 (:602"
           " `openEvo(${esc(JSON.stringify(m.evo.name))})`) —— 它走的正是 esc(), 并由桩检查"
           " 304 以 8 个名字 (含 \" < > \\ 真实换行 反引号+${ 实体 U+2028) 实体解码后编译往返"
           " 验证过; 其余为内部字面量与内部计数; 显式冻结为例外(非静默放过)",
    "html": "#evo-list 行拼装 —— 由检查 307 审计 (本 change 自己新增的渲染代码)",
}

# F6: 既不是内联审计(`${...}` 在窗口内)、也不是裸标识符的**动态** sink —— 值在别处拼装且形态看不透
# (拼接 / 三元 / 调用)。必须按 (选择器, RHS 原文) 冻结登记: RHS 一变 (例如把 `= svg` 改成
# `= '<svg>' + svg + '</svg>'`) 就匹配不上 -> FAIL。纯字面量 sink 无需登记 (没有动态值就没有转义问题)。
_DYN_SINKS = {
    ("#m-links", "build.length ? '链接：' + build.join('') : '链接：无'"):
        "#m-links 的链接串: 由同函数 build.push 逐段拼装 (index.html:736-737:"
        " onclick 里的 #{id} 是整数, 正文已 esc(content.slice(0,14))); 既有代码, 本 change 未触碰"
        " —— 显式冻结为例外",
    # --- 下面三条是**基线 52366a0 遗留**的未登记 sink (该 commit 只改 index.html, 没同步本登记表),
    #     与 insight-evolution-backlinks 无关; 三条都无新增转义面, 按本检查的规则显式冻结 ---
    ("#evo-list",
     'auth ? \'<div class="evo-empty">未授权：需要 API Key<br>'
     '<span style="color:var(--dim)">在顶部 API Key 框粘贴 LCLONE_API_KEY 后回车，页面会自动刷新。</span></div>\' : '
     '\'<div class="evo-empty">资产清单加载失败<br><span style="color:var(--dim)">'
     '检查后端服务，或点工具栏「刷新」重试。</span></div>\''):
        "#evo-list 的鉴权/失败态三元 (index.html:1299, 52366a0 引入): 两个分支都是"
        "**纯静态字面量**, 零插值、零用户输入 -> 无转义面; 显式冻结为例外",
    ("box.innerHTML = '<div class=\"empty\">读取失败：' + esc",
     "'<div class=\"empty\">读取失败：' + esc((e && e.message) || String(e)) + '</div>'"):
        "待确认队列读取失败提示 (index.html:1402): 唯一动态量是 esc((e && e.message) ||"
        " String(e)), 已由 esc 包裹; 其余为静态字面量; 显式冻结为例外",
    ("g.innerHTML = auth",
     'auth ? \'<div style="text-align:center;margin:90px 24px;color:var(--dim);line-height:1.9">\''
     ' + \'后端返回 <b>401 未授权</b>（后台已启用 LCLONE_API_KEY 鉴权，或当前 Key 已失效）。<br>\''
     ' + \'请在顶部 <b>API Key</b> 框粘贴 <code>LCLONE_API_KEY</code> 后回车，\''
     ' + \'页面会自动刷新并加载记忆工作台。\' + \'</div>\' : '
     '\'<div style="text-align:center;margin:90px 24px;color:var(--dim);line-height:1.9">\''
     ' + \'记忆数据加载失败。<br>\' + \'请确认后端服务在运行，然后点工具栏「刷新」重试。\' + \'</div>\''):
        "记忆工作台鉴权/失败态 (index.html:530, 52366a0 引入): 两个分支全是静态字面量,"
        " 无插值、无用户输入 -> 无转义面; 显式冻结为例外",
    # --- 本 change (insight-evolution-backlinks) 新增的一处 sink ---
    ("#evo-refs",
     "'<span class=\"evo-refs-sum\">← ' + refs.length + ' 条洞察引用它：</span>' + chips"):
        "#evo-refs 反向引用条外壳 (index.html:863, 本 change 新增): 动态量只有两个 ——"
        " refs.length (数组长度, 恒为整数) 与 chips (由同函数 refs.map 逐项拼装: r.id 是"
        " memories.id = INTEGER PRIMARY KEY AUTOINCREMENT, 只作 data-ref 整数值,"
        " 同 _SAFE_INTERP 的 m.id; r.project_name 先经 esc() 包裹、拼出的 who 再经 esc() 包裹;"
        " 其余为静态字面量)。外壳刻意用 + 拼接而不用 ${} 模板插值: 含 ${} 的 sink 会按"
        " unwrapped 归入 _unwrapped 白名单 (该表本 change 无权扩), 拼接形态才能在这里按"
        " (选择器, RHS) 显式冻结成有理由的例外; 该 sink 自带 `$('evo-refs')` 前缀, 故选择器为 #evo-refs",
}


def _strip_comment(ln):
    """剥离行尾 `//` 注释; **引号内**的 `//` 不是注释 —— index.html:696 的
    `xmlns="http://www.w3.org/2000/svg"` 就在字符串字面量里 (已 grep 确认全文件仅此一处),
    所以不能简单 split('//'), 必须引号感知地只截断**引号外**的 `//`。"""
    q, i = "", 0
    while i < len(ln):
        c = ln[i]
        if q:
            if c == "\\":
                i += 2
                continue
            if c == q:
                q = ""
        elif c in "'\"`":
            q = c
        elif c == "/" and i + 1 < len(ln) and ln[i + 1] == "/":
            return ln[:i]
        i += 1
    return ln


def _sink_window(lines, start, col=0):
    """sink 语句窗口: 从 (start, col) 扫到"花括号深度 <= 0 且**去掉行尾注释后**以 ';' 结尾"的第一行。
    F5: 注释必须剥离 —— `x.innerHTML = '';  // 说明` 的行尾不是 ';', 否则窗口会越过该行、
    把下一条语句的 sink 一并吞进来 (那时被吞的 sink 就再也不会被当成 sink 审视)。
    深度与结束判定只看 (start, col) 之后的部分, 但**首行原文照收**: 选择器 `$('#id')` 在 sink 左侧,
    截掉就报不出是哪个 sink 了。"""
    depth, buf = 0, []
    for j in range(start, min(start + 60, len(lines))):
        ln = lines[j]
        code = _strip_comment(ln[col:] if j == start else ln)
        depth += code.count("{") - code.count("}")
        buf.append(ln)
        if depth <= 0 and code.rstrip().endswith(";"):
            break
    return "\n".join(buf), j


def _sink_sites(lines):
    """每处 `.innerHTML =` 各算一个 sink (同一行出现多次也各算一条)。
    F5: 不再"取窗口后 i = j + 1 整段跳过" —— 那样被上一条窗口吞掉的 sink 永远不作为 sink 被审视。"""
    out = []
    for idx, ln in enumerate(lines):
        for m in re.finditer(r"\.innerHTML\s*=", ln):
            out.append((idx, m.start()))
    return out


_STR_LIT = re.compile(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"|`(?:[^`\\]|\\.)*`")
_BARE_IDENT = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")


def _sink_rhs(win):
    """该 sink 的右侧表达式文本: 去注释、去结尾 ';'、空白归一 (用作冻结指纹)。"""
    parts = re.split(r"\.innerHTML\s*=", win, maxsplit=1)
    if len(parts) < 2:
        return ""
    _txt = "\n".join(_strip_comment(x) for x in parts[1].split("\n"))
    return " ".join(_txt.strip().rstrip(";").split())


def _sink_selector(win):
    """报出是哪个 sink: 优先 `$('#id')`, 否则退回该行代码 (剥掉行尾注释, 免得把注释当选择器报出来)。"""
    _first = _strip_comment(win.split("\n")[0])
    _sel = re.search(r"\$\('([^']+)'\)", _first)
    return '#' + _sel.group(1) if _sel else _first.strip()[:48]


_lines = _fe_text.split("\n")
_windows = []
for _idx, _col in _sink_sites(_lines):
    _win, _end = _sink_window(_lines, _idx, _col)
    _windows.append((_idx + 1, _win))

_unwrapped = {}
_n_inline = 0          # 窗口内至少有一个插值的 sink 数 (覆盖面自报)
_ident_seen = {}       # 裸标识符 sink: 标识符 -> 该 sink 的选择器
_dyn_seen = set()      # 其余动态 sink: (选择器, RHS 原文)
_swallow = []          # F5 兜底: 一个窗口里出现 >1 处 sink = 又吞掉了下一条
for _ln, _win in _windows:
    _n_here = len(re.findall(r"\.innerHTML\s*=", _win))
    if _n_here > 1:
        _swallow.append(f"{_sink_selector(_win)}(L{_ln},{_n_here} sinks)")
    _sel = _sink_selector(_win)
    if re.search(r"\$\{", _win):
        _n_inline += 1
        for _m in re.finditer(r"\$\{([^{}]*)\}", _win):
            _expr = _m.group(1).strip()
            if not any(c in _expr for c in ("esc(", "evoChip(", "Number(")):
                _unwrapped.setdefault(_expr, []).append(_ln)
        continue                       # 内联审计过 -> 不再要求 ident/dyn 登记
    _rhs = _sink_rhs(_win)
    if _BARE_IDENT.match(_rhs):
        _ident_seen[_rhs] = _sel
    elif re.search(r"[A-Za-z_$][A-Za-z0-9_$]*", _STR_LIT.sub("", _rhs)):
        _dyn_seen.add((_sel, _rhs))    # 含标识符/调用 -> 动态且看不透, 必须冻结登记
    # else: 纯字面量 (剥掉字符串后没有标识符) -> 没有动态值, 无需登记

_ident_bad = sorted(set(_ident_seen) - set(_IDENT_SINKS))
_ident_stale = sorted(set(_IDENT_SINKS) - set(_ident_seen))
_dyn_bad = sorted(f"{_s} :: {_r}" for _s, _r in _dyn_seen - set(_DYN_SINKS))
_dyn_stale = sorted(f"{_s} :: {_r}" for _s, _r in set(_DYN_SINKS) - _dyn_seen)
check("303 前端 innerHTML 插值转义审计 (未包裹者必须等于冻结白名单; 每个 sink 必须内联审计或逐条登记)",
      len(_windows) >= 18 and set(_unwrapped) == set(_SAFE_INTERP)
      and not _ident_bad and not _ident_stale and not _dyn_bad and not _dyn_stale
      and not _swallow,
      f"sinks={len(_windows)} inline={_n_inline} ident={sorted(_ident_seen)} "
      f"extra={sorted(set(_unwrapped) - set(_SAFE_INTERP))} "
      f"missing={sorted(set(_SAFE_INTERP) - set(_unwrapped))} ident_bad={_ident_bad} "
      f"ident_stale={_ident_stale} dyn={sorted(_dyn_seen)} dyn_bad={_dyn_bad} "
      f"dyn_stale={_dyn_stale} swallow={_swallow}")

# 304 动效兜底与响应式断点不得被删
check("304 前端保留 prefers-reduced-motion 兜底与既有响应式断点",
      "prefers-reduced-motion: reduce" in _fe_text and "animation:none" in _fe_text
      and "transition:none" in _fe_text and "@media (max-width:760px)" in _fe_text,
      f"media={re.findall(r'@media[^{]*', _fe_text)}")

# 305 纯 JS 文件必须可解析; 无 TS 断言。
#     TS 类型断言/声明在 .js 里本就是语法错误, 故 node --check 才是真正的强制手段,
#     下面的 grep 只是把这条意图显式化 (审阅时一眼可见), 不假装它是独立防线。
_js_files = [p for p in subprocess.run(["git", "ls-files", "*.js"], cwd=str(ROOT),
             capture_output=True, text=True, encoding="utf-8").stdout.split("\n") if p.strip()]
_js_bad = []
for _rel in _js_files:
    _jr = subprocess.run([_node, "--check", _rel], cwd=str(ROOT), capture_output=True,
                         text=True, encoding="utf-8", errors="replace") if _node else None
    if _jr is None or _jr.returncode != 0:
        _js_bad.append(_rel + ": " + ("" if _jr is None else (_jr.stderr or "")[:80]))
_TS_ONLY = re.compile(r"(\bas\s+unknown\b|\bas\s+any\b|\bsatisfies\s+[A-Z]|\binterface\s+[A-Z]"
                      r"|\bimplements\s+[A-Z]|[A-Za-z0-9_$]!\s*[.;,)]"
                      r"|\bdeclare\s+(const|function|class)\b)")
_ts_hits = {_rel: _TS_ONLY.findall((ROOT / _rel).read_text(encoding="utf-8")) for _rel in _js_files}
check("305 纯 JS 文件可解析且无 TS 类型断言",
      _node is not None and bool(_js_files) and not _js_bad and not any(_ts_hits.values()),
      f"files={len(_js_files)} bad={_js_bad} ts={ {k: v for k, v in _ts_hits.items() if v} }")

# 306 端到端: 用真实 app 顺序走完看板能做的整条链路 (建/改/冲突/删/恢复/改名/历史/回滚/续号)
_e2c = TestClient(_wm2.create_app(os.path.join(tempfile.mkdtemp(prefix="e2e_"), "e.db")))
_steps = []
_r = _e2c.post("/api/evolution/publish",
               json={"name": "life.txt", "content": "v1 body", "only_if_new": True})
_steps.append(("新建 v1", _r.status_code == 200 and _r.json()["result"]["version"] == 1))
_r = _e2c.post("/api/evolution/publish",
               json={"name": "life.txt", "content": "dup", "only_if_new": True})
_steps.append(("重名新建 409", _r.status_code == 409))
_r = _e2c.post("/api/evolution/publish",
               json={"name": "life.txt", "content": "v2 body", "base_version": 1})
_steps.append(("编辑 v2", _r.status_code == 200 and _r.json()["result"]["version"] == 2))
_r = _e2c.post("/api/evolution/publish",
               json={"name": "life.txt", "content": "stale", "base_version": 1})
_hv = [h["version"] for h in _e2c.get("/api/evolution/history?name=life.txt").json()["items"]]
_steps.append(("陈旧 base_version 409 且不产生新版本",
               _r.status_code == 409 and _r.json()["detail"]["current_version"] == 2 and _hv == [2, 1]))
_cur = [x for x in _e2c.get("/api/evolution/index").json()["items"] if x["name"] == "life.txt"][0]
_r = _e2c.post("/api/evolution/delete",
               json={"name": "life.txt", "base_version": _cur["base_version"]})
_steps.append(("墓碑删除后默认清单消失、显式可见",
               _r.status_code == 200
               and "life.txt" not in {x["name"] for x in _e2c.get("/api/evolution/index").json()["items"]}
               and "life.txt" in {x["name"] for x in
                                  _e2c.get("/api/evolution/index?include_deleted=true").json()["items"]}))
_r = _e2c.post("/api/evolution/restore", json={"name": "life.txt"})
_steps.append(("恢复后回到默认清单且版本不变",
               _r.status_code == 200
               and [x for x in _e2c.get("/api/evolution/index").json()["items"]
                    if x["name"] == "life.txt"][0]["version"] == 2))
_r = _e2c.post("/api/evolution/rename",
               json={"name": "life.txt", "new_name": "life2.txt", "base_version": 2})
_tomb = [x for x in _e2c.get("/api/evolution/index?include_deleted=true").json()["items"]
         if x["name"] == "life.txt"]
_steps.append(("改名: 新名 v1 + 旧名墓碑指向新名 + 历史不迁移",
               _r.status_code == 200 and _r.json()["result"]["new_name"] == "life2.txt"
               and len(_tomb) == 1 and _tomb[0]["renamed_to"] == "life2.txt"
               and [h["version"] for h in
                    _e2c.get("/api/evolution/history?name=life2.txt").json()["items"]] == [1]))
_cv = _e2c.get("/api/evolution/content?name=life2.txt&version=1").json()
_rb = _e2c.post("/api/evolution/rollback", json={"name": "life2.txt", "version": 1})
_steps.append(("历史内容可读且回滚到 v1",
               _cv.get("content") == "v2 body" and _cv.get("base_version") == 1
               and _rb.status_code == 200))
_r = _e2c.post("/api/evolution/publish",
               json={"name": "life2.txt", "content": "v3 after rollback", "base_version": 1})
_steps.append(("回滚后再发布按 max+1 续号",
               _r.status_code == 200 and _r.json()["result"]["version"] == 2))
_bad = [n for n, ok in _steps if not ok]
check(f"306 端到端: 看板全链路 ({len(_steps)} 步)", len(_steps) == 9 and not _bad, f"failed={_bad}")

# 307 #evo-list 的拼装处审计 (本 change 自己新增的渲染代码)。
#     为什么必须单独查: `$('evo-list').innerHTML = html;` 右边是标识符, 303 的窗口看不见它;
#     而 html 由 evoRefreshList 里 `let html=''` + 内部 walk() 的 `s += \`…\`` 累加而来 ——
#     那正是服务端下发的资产名落地成 HTML 的地方, 也是转义最该被守住的地方。
#     函数体级审计会掺入 note/fetch 等非 sink 文本, 所以只取函数体内的 `s +=` 那些 HTML 拼装行。
def _function_body(text, name):
    """按花括号配平取 `function NAME(...) {` / `async function NAME(...) {` 的函数体。"""
    m = re.search(r"(?:async\s+)?function\s+" + re.escape(name) + r"\s*\([^)]*\)\s*\{", text)
    if not m:
        return ""
    i, depth = m.end(), 1
    while i < len(text) and depth > 0:
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
        i += 1
    return text[m.end():i]


_body = _function_body(_fe_text, "evoRefreshList")
# F8: 从 `\bs\s*+=` 放宽到 `\b\w+\s*+=` —— 任何累加变量都纳入审计 (将来有人写 `t += '…' + raw`
# 会因多出未登记的插值表达式而 FAIL, 而不是因为变量名不叫 s 就被漏掉)。下面的比较是**双向等号**。
_accum = "\n".join(ln for ln in _body.split("\n") if re.search(r"\b\w+\s*\+=", ln))
_accum_unwrapped = {m.group(1).strip() for m in re.finditer(r"\$\{([^{}]*)\}", _accum)
                    if not any(c in m.group(1) for c in ("esc(", "evoChip(", "Number("))}
# #evo-list 拼装行的未包裹插值: 逐条需能证明是内部量 (深度计数、由服务端布尔派生的内部字面量二选一)
_SAFE_ACCUM = {
    "'&nbsp;'.repeat(depth)": "内部缩进深度计数 (walk 的 depth 参数, 由本地递归层数决定)",
    "tomb ? ' tomb' : ''": "由 EVO_META 的 deleted_at 派生的布尔, 两支都是内部字面量",
}
check("307 #evo-list 拼装行的插值转义审计 (本 change 自己的渲染)",
      bool(_accum) and _accum_unwrapped == set(_SAFE_ACCUM),
      f"lines={len(_accum.splitlines())} extra={sorted(_accum_unwrapped - set(_SAFE_ACCUM))} "
      f"missing={sorted(set(_SAFE_ACCUM) - _accum_unwrapped)}")

# ---- 308 (final review I4): 墓碑必须自成一态, 不能被当成 untracked 而被 publish --all 复活 ----
# 根因: `manifest_index`/`ls()` 默认都**不含**墓碑 (Task 3 的墓碑过滤扩到了 tree() 与
# migrate_cache_files, 漏了 status() 这条链), 于是"服务器已删除"与"服务器从来没有"在
# 同步状态里长得一模一样 -> status 报 untracked -> publish_all 把它推上去 -> 不带
# base_version 的 publish 会清掉墓碑 = **静默复活被删资产**; 而且 `evolution list` 会打印
# "本地未收录 N 个: … 用 lclone evolution publish 上传", 等于指导用户复活自己刚删的东西。
_al = tempfile.mkdtemp(prefix="evotombst_")
_al_db = os.path.join(_al, "al.db")
_al_conn = db_mod.init(_al_db)
_prev_evo_dir3 = os.environ.get("LCLONE_EVO_DIR")
_prev_blob_dir3 = os.environ.get("LCLONE_EVO_BLOB_DIR")
os.environ["LCLONE_EVO_DIR"] = os.path.join(_al, "evo")
os.environ["LCLONE_EVO_BLOB_DIR"] = os.path.join(_al, "blobs")
try:
    _al_be = evo_store.LocalBackend(_al_conn)
    # 模拟"缓存过该资产"的机器: 发布 -> pull 到本地 -> 服务器侧墓碑删除
    evo_store.publish(_al_conn, "doomed.sh", "echo doomed")
    evo_store.pull(_al_be, ["doomed.sh"])
    evo_store.delete(_al_conn, "doomed.sh")
    _al_st = {r["name"]: r["state"] for r in evo_store.backend_status(_al_be)}
    _al_push = evo_store.publish_all(_al_be)
    _al_buf = io.StringIO()
    with contextlib.redirect_stdout(_al_buf):
        cli.main(["evolution", "list", "--local", "--db", _al_db])
    _al_list = _al_buf.getvalue()
    _al_tomb = evo_store.current(_al_conn, "doomed.sh")["deleted_at"]
    check("308 墓碑自成一态: status=deleted, publish --all 不复活, list 指向 restore",
          _al_st.get("doomed.sh") == "deleted"
          and "doomed.sh" not in [x.get("name") for x in _al_push["published"]]
          and bool(_al_tomb)
          and "已删除" in _al_list and "restore" in _al_list
          and "本地未收录" not in _al_list,
          f"state={_al_st.get('doomed.sh')} published={[x.get('name') for x in _al_push['published']]} "
          f"deleted_at={_al_tomb!r} list={_al_list.strip()[:160]}")
finally:
    if _prev_evo_dir3 is None:
        os.environ.pop("LCLONE_EVO_DIR", None)
    else:
        os.environ["LCLONE_EVO_DIR"] = _prev_evo_dir3
    if _prev_blob_dir3 is None:
        os.environ.pop("LCLONE_EVO_BLOB_DIR", None)
    else:
        os.environ["LCLONE_EVO_BLOB_DIR"] = _prev_blob_dir3

# ---- 309 (final review I5): 乐观锁必须在**排他事务**里做 check-then-act ----
# 只比较版本号是 check-then-act: 两个同 base_version 的写可以先后都通过校验。这里用两条
# 连接 + 一个"校验之后、DB 写入之前"的闸门**确定性地**构造那个交错 (钩在 put_blob 上 ——
# 它是每条写路径在校验与 INSERT 之间唯一的公共点, 不依赖内部读了几次 current):
#   B 通过校验后卡住 -> A 以同一个 base_version 完整跑完 -> 放 B 继续
# 修复后: A 在 BEGIN IMMEDIATE 上就**等着** B 提交, 随后看到 v2 而 409 (B 赢, A 被告知刷新);
# 修复前: A 也写成功 (v2), B 再补一条 v3 把指针推过 A —— 两个都"成功", 典型的 lost update。
import threading  # noqa: E402  (只有本块用)
import time  # noqa: E402

_rc_dir = tempfile.mkdtemp(prefix="evorace_")
_rc_db = os.path.join(_rc_dir, "race.db")
_rc_init = db_mod.init(_rc_db)
_rc_init.close()
_rc_a = db_mod.connect(_rc_db)
_rc_b = db_mod.connect(_rc_db)
evo_store.publish(_rc_a, "race.txt", "v1")
_orig_put_blob = evo_store.put_blob
_rc_entered = threading.Event()
_rc_open = threading.Event()
_rc_res = {}


def _rc_writer_a():
    try:
        _rc_res["A"] = evo_store.publish(_rc_a, "race.txt", "A-body", base_version=1)
    except BaseException as e:  # noqa: BLE001 - 测试要看清到底抛了什么
        _rc_res["A"] = e


def _rc_writer_b():
    try:
        _rc_res["B"] = evo_store.publish(_rc_b, "race.txt", "B-body", base_version=1)
    except BaseException as e:  # noqa: BLE001
        _rc_res["B"] = e


_rc_tb = threading.Thread(target=_rc_writer_b)


def _rc_hooked_put_blob(content):
    if threading.current_thread() is _rc_tb:   # 只卡 B, 卡在"校验已过、INSERT 未发"处
        _rc_entered.set()
        _rc_open.wait(5)
    return _orig_put_blob(content)


_rc_entered_ok = False
_rc_ta = threading.Thread(target=_rc_writer_a)
try:
    evo_store.put_blob = _rc_hooked_put_blob
    _rc_tb.start()
    _rc_entered_ok = _rc_entered.wait(5)
    _rc_ta.start()
    time.sleep(0.2)      # 给 A 时间抵达 BEGIN IMMEDIATE (无排他事务时它会直接写成功)
    _rc_open.set()
    _rc_ta.join(10)
    _rc_tb.join(10)
finally:
    _rc_open.set()
    evo_store.put_blob = _orig_put_blob

_rc_cur = evo_store.current(_rc_a, "race.txt")
_rc_hist = [h["version"] for h in evo_store.history(_rc_a, "race.txt")]
check("309 乐观锁在同一排他事务内: 同 base_version 的并发写不丢更新",
      _rc_entered_ok
      and isinstance(_rc_res.get("A"), evo_store.VersionConflict)
      and getattr(_rc_res.get("A"), "current_version", None) == 2
      and isinstance(_rc_res.get("B"), dict) and _rc_res["B"].get("version") == 2
      and _rc_cur["version"] == 2 and _rc_hist == [2, 1]
      and evo_store.resolve(_rc_a, "race.txt")["content"] == "B-body",
      f"entered={_rc_entered_ok} A={_rc_res.get('A')!r} B={_rc_res.get('B')!r} "
      f"cur=v{_rc_cur['version']} hist={_rc_hist}")

# ---- 回归: 宿主注入块不得算「用户轮」; 提炼器自报「空」不得成卡 (事故 #761) ----
# 现象: 插件把「skill 全文 + bootstrap 记忆」当 user 消息塞进会话, 闸门在它身上命中
# 「记住/记一下/remember」→ 走显式记忆旁路 → 每个新会话首轮都白跑一次提炼; 模型回
# 「空 + 一段解释」时又没有任何哨兵/形状校验, 于是元响应被存成一条待确认洞察。
_inj = ("【lclone-memory skill 全文】(会话主导)\n"
        "# L-clone 对话自动记忆\n"
        "触发词：「记住」「记一下」「上次做到哪」\n"
        "| `remember` | 主动记忆 |\n"
        "\n【记忆】\n【全局记忆】\n- 要点：示例卡片\n")
_v310 = gate.classify("用户：" + _inj + "\n\n助手：好的")
check("310 注入块不算用户轮 (不触发显式记忆旁路)",
      _v310.kind == gate.SKIP and _v310.hits == (), f"{_v310.kind} {_v310.hits}")
check("311 注入块与真实决策同轮时仍识别决策",
      gate.classify("用户：决定统一口径，以后都按这个来\n\n" + _inj + "\n\n助手：好").kind
      == gate.CANDIDATE,
      str(gate.classify("用户：决定统一口径，以后都按这个来\n\n" + _inj + "\n\n助手：好")))
check("311b 没有角色标记时也剥注入块",
      gate.hits(gate.user_turns(_inj), gate.EXPLICIT_MARKERS) == (),
      str(gate.hits(gate.user_turns(_inj), gate.EXPLICIT_MARKERS)))

_orig_chat = llm_mod.chat
_orig_backend = llm_mod.backend
llm_mod.backend = lambda: "api"
llm_mod.chat = lambda *a, **k: (
    "空\n\nSend to parent: 记忆提炼结果：空（未提炼任何 insight 卡片）。\n"
    "- 原因：本轮既无用户拍板的决策，也无助手确认/落地。")
_e312 = llm_mod.extract_memories("用户：x\n\n助手：y")
check("312 提炼器回「空 + 解释」不成卡", _e312 == [], str(_e312)[:80])
llm_mod.chat = lambda *a, **k: "这是一段普通叙述，没有卡片结构，也没有结论。"
_e313a = llm_mod.extract_memories("x")
llm_mod.chat = lambda *a, **k: (
    "要点：测试先行\n背景/为什么：先红后绿才证明断言有效\n"
    "影响/以后注意：回归可查\n归属：无")
_e313b = llm_mod.extract_memories("x")
llm_mod.chat, llm_mod.backend = _orig_chat, _orig_backend
check("313 无四段形状的回声不成卡; 四段卡照常成卡",
      _e313a == [] and len(_e313b) == 1, f"{len(_e313a)}/{len(_e313b)}")
check("314 元报告回声不进准入 (正常洞察不受影响)",
      mem_mod._filter_item({"level": "insight", "content": "空\n\nSend to parent: 记忆提炼结果：空"}) is None
      and mem_mod._filter_item({"level": "insight", "content": "Web 面板分页每行三个"}) is not None)
# 整链路回放: 注入块 + 真实用户轮 (命中强信号→candidate) + 模型回「空」→ 一条都不该落库
_orig_chat315 = llm_mod.chat
_orig_backend315 = llm_mod.backend
llm_mod.backend = lambda: "api"
llm_mod.chat = lambda *a, **k: "空\n\nSend to parent: 记忆提炼结果：空（未提炼任何 insight 卡片）。"
_ids315 = mem_mod.capture(conn, "用户：这份评审 brief 以后都按这个格式派发\n\n" + _inj,
                          project_id=pid, session_key="inc761")
llm_mod.chat, llm_mod.backend = _orig_chat315, _orig_backend315
check("315 事故回放: 注入块 + 模型回「空」→ 0 条落库", _ids315 == [], str(_ids315))

# ---- (a) 用户轮证据: 助手单方面查出的近况/常识不成卡, 用户拍板过的照常成卡 ----
check("316 助手单方面结论在用户轮里没有出处",
      not gate.has_user_evidence(
          "要点：DSH 里 skill 能否被管理取决于投递路径，散装 skill 只能手动覆盖。",
          "帮我把 sp-spec 这个 skill 的用法理一下"))
check("317 用户拍板过的主张有出处",
      gate.has_user_evidence("要点：记忆统一用 SQLite 存\n背景/为什么：单机部署",
                             "决定了记忆统一用 SQLite 存，以后都这样"))
_orig_ex_ev = llm_mod.extract_memories
llm_mod.extract_memories = lambda t: [
    {"level": "insight",
     "content": "要点：junction 直连可以让编辑立即生效\n背景/为什么：DSH 跟随符号链接\n"
                "影响/以后注意：仓库改动会立刻上线\n归属：无"}]
_ev_ids = mem_mod.capture(conn, "决定了 sp-spec 的发布方式改为镜像覆盖",
                          project_id=pid, session_key="ev316")
llm_mod.extract_memories = lambda t: [
    {"level": "insight",
     "content": "要点：发布方式改成镜像覆盖\n背景/为什么：目录没有 .git 只能整体覆盖\n"
                "影响/以后注意：每次发布前核对差分为空\n归属：无"}]
_ev_ids2 = mem_mod.capture(conn, "决定了发布方式改成镜像覆盖整个目录",
                           project_id=pid, session_key="ev317")
llm_mod.extract_memories = _orig_ex_ev
check("318 近况类卡片在 capture 链路被拦下", _ev_ids == [], str(_ev_ids))
check("319 有用户轮出处的卡片照常成卡", len(_ev_ids2) == 1, str(_ev_ids2))
# 用户显式点名要记时豁免证据检查 (人说"记一下"就是背书, 不该因为措辞不同被丢)
llm_mod.extract_memories = lambda t: [
    {"level": "insight",
     "content": "要点：覆盖发布前必须先备份\n背景/为什么：镜像覆盖不可逆\n"
                "影响/以后注意：脚本里自动备份\n归属：无"}]
_ev_ids3 = mem_mod.capture(conn, "记一下", project_id=pid, session_key="ev318")
llm_mod.extract_memories = _orig_ex_ev
check("320 用户显式要求记忆时豁免证据检查", len(_ev_ids3) == 1, str(_ev_ids3))

# ---- 第 0 步三条规则 + 两个度量 (调研落地, 见 docs/记忆准入门控调研.md §5) ----
# ① 短时性措辞: 只在没有决定性信号时才算负信号 (「现在效果不错，统一按这个来」是规则)
check("321 短时性措辞不与决策信号同现时判跳过",
      gate.classify("这次先这样，明天再看看服务还稳不稳").kind == gate.SKIP
      and gate.classify("这次决定统一用 SQLite 存").kind == gate.CANDIDATE,
      str(gate.classify("这次先这样，明天再看看服务还稳不稳")))
# ② 自包含性: 只有一句「要点」的残卡不成卡
_orig_chat_s = llm_mod.chat
_orig_backend_s = llm_mod.backend
llm_mod.backend = lambda: "api"
llm_mod.chat = lambda *a, **k: "要点：测试先行\n归属：无"
_e321a = llm_mod.extract_memories("x")
llm_mod.chat = lambda *a, **k: "要点：测试先行\n背景/为什么：先红后绿\n影响/以后注意：可回归\n归属：无"
_e321b = llm_mod.extract_memories("x")
# ③ 归属为空 → 结构性拒绝
llm_mod.chat = lambda *a, **k: "要点：测试先行\n背景/为什么：先红后绿\n归属："
_e321c = llm_mod.extract_memories("x")
llm_mod.chat, llm_mod.backend = _orig_chat_s, _orig_backend_s
check("322 残卡(只有要点)不成卡; 四段齐备照常成卡",
      _e321a == [] and len(_e321b) == 1, f"{len(_e321a)}/{len(_e321b)}")
check("323 归属为空 → 结构性拒绝", _e321c == [], str(_e321c)[:60])

# ④ 人工确认留痕: delete 会真删记忆行, 留痕必须活下来 (否则精确率永远算不出)
_m_keep = mem_mod.remember(conn, "指标测试用洞察 A", project_id=pid)
_m_del = mem_mod.remember(conn, "指标测试用洞察 B", project_id=pid)
mem_mod.review(conn, _m_keep, "keep")
mem_mod.review(conn, _m_del, "delete")
_left = conn.execute("SELECT COUNT(*) c FROM memories WHERE id=?", (_m_del,)).fetchone()["c"]
_logged = {r["memory_id"]: r["action"] for r in conn.execute(
    "SELECT memory_id, action FROM review_log WHERE memory_id IN (?, ?)",
    (_m_keep, _m_del))}
check("324 确认动作留痕且删除后仍在",
      _left == 0 and _logged.get(_m_keep) == "keep" and _logged.get(_m_del) == "delete",
      f"left={_left} logged={_logged}")

_met = mem_mod.queue_metrics(conn, days=7)
check("325 queue_metrics 算出精确率/负担/复用率",
      _met["reviewed"]["keep"] >= 1 and _met["reviewed"]["delete"] >= 1
      and 0 < _met["queue_precision"] < 1 and _met["review_burden"] is not None
      and _met["reuse_rate"] is not None, str(_met))
_empty_conn = db_mod.init(os.path.join(tmp, "metrics_empty.db"))
_me = mem_mod.queue_metrics(_empty_conn, days=7)
check("326 无拍板留痕时指标为 None (不把'没数据'读成 0)",
      _me["queue_precision"] is None and _me["review_burden"] is None
      and _me["reuse_rate"] is None, str(_me))
_empty_conn.close()

_cli_buf = io.StringIO()
with contextlib.redirect_stdout(_cli_buf):
    cli.main(["stats", "--db", dbp, "--days", "7"])
check("327 CLI stats 打印四个指标",
      "队列精确率" in _cli_buf.getvalue() and "复核负担" in _cli_buf.getvalue()
      and "复用率" in _cli_buf.getvalue(), _cli_buf.getvalue()[:120])
try:
    check("328 /api/stats 已注册 (远端可查真实指标)",
          "/api/stats" in {r.path for r in app.routes})
except NameError:
    print("SKIP 328 (fastapi 未安装)")

# ---- 跨层去重 (全局层 ↔ 项目层) + 进化资产反向引用 (仅 active) ----
_cl_conn = db_mod.init(os.path.join(tmp, "crosslayer.db"))
_cl_pid = proj_mod.add_project(_cl_conn, "cl", str(demo_root), "")
_doc = ("要点：跨层去重测试卡。\n背景/为什么：验证全局层与项目层互查。\n"
        "影响/以后注意：同义内容跨层不再重复写入。\n归属：无")
mem_mod.remember(_cl_conn, _doc, level="insight", project_id=None, confirmed=True)
_gemb = mem_mod.llm.embed_one(_doc)   # 同文本 -> 与已落库那条余弦必为 1.0 (与 embedder 实现无关)
check("329 项目卡跨层扫描命中全局层同义卡",
      mem_mod._is_duplicate(_cl_conn, _gemb, _cl_pid, cross_layer=True) is True, "")
check("330 不给 cross_layer 时仍是同域语义 (现有行为不变)",
      mem_mod._is_duplicate(_cl_conn, _gemb, _cl_pid) is False, "")
check("331 全局卡仍只比全局层",
      mem_mod._is_duplicate(_cl_conn, _gemb, None) is True, "")
check("332 文本级跨层同规则",
      mem_mod._is_text_duplicate(_cl_conn, _doc, _cl_pid, cross_layer=True) is True
      and mem_mod._is_text_duplicate(_cl_conn, _doc, _cl_pid) is False, "")
# 覆盖面规则的反向: 全局侧跨层扫描要能看见"只存在于项目层"的等价卡
_pdoc = _doc + "\n项目侧补充：只存在于项目层。"
mem_mod.remember(_cl_conn, _pdoc, level="insight", project_id=_cl_pid, confirmed=True)
_pemb = mem_mod.llm.embed_one(_pdoc)
check("333 全局侧跨层扫描看得见项目层独有卡",
      mem_mod._is_duplicate(_cl_conn, _pemb, None, cross_layer=True) is True
      and mem_mod._is_duplicate(_cl_conn, _pemb, None) is False, "")
# 反向引用只取 active (pending 不进看板引用条)
_pend = mem_mod.remember(_cl_conn,
                         "要点：待确认引用卡 [[evo:rev-test.py]]。\n背景/为什么：验证状态过滤。\n"
                         "影响/以后注意：pending 不该出现在反向引用里。\n归属：无",
                         level="insight", project_id=None, confirmed=False)
_act = mem_mod.remember(_cl_conn,
                        "要点：已确认引用卡 [[evo:rev-test.py]]。\n背景/为什么：验证状态过滤。\n"
                        "影响/以后注意：active 应出现在反向引用里。\n归属：无",
                        level="insight", project_id=None, confirmed=True)
check("334 反向引用只取 active",
      [r["id"] for r in mem_mod.insights_for_evolution(_cl_conn, "rev-test.py")] == [_act],
      f"pend={_pend} act={_act}")
_cl_conn.close()

# ---- 335-337: index 的 ref_count/refs 在 REST 层留痕 (含零引用与 /api/evolutions 形状) ----
try:
    from fastapi.testclient import TestClient as _TCRef
    _ref_root = tempfile.mkdtemp(prefix="evoref_")
    _ref_dbp = os.path.join(_ref_root, "ref.db")
    _ref_conn = db_mod.init(_ref_dbp)
    _ref_pid = proj_mod.add_project(_ref_conn, "clref", str(demo_root), "")
    _ref_mid = mem_mod.remember(
        _ref_conn,
        "要点：反向引用 REST 卡 [[evo:ref-smoke.txt]]。\n背景/为什么：验证 index 下发引用。\n"
        "影响/以后注意：ref_count/refs 必须能反查。\n归属：无",
        level="insight", project_id=_ref_pid, confirmed=True)
    _ref_conn.close()
    from lclone import web as _wm_ref
    _tc_ref = _TCRef(_wm_ref.create_app(_ref_dbp))
    _tc_ref.post("/api/evolution/publish", json={"name": "ref-smoke.txt", "content": "v1"})
    _tc_ref.post("/api/evolution/publish", json={"name": "ref-orphan.txt", "content": "v1"})
    _ref_items = {x["name"]: x for x in _tc_ref.get("/api/evolution/index").json()["items"]}
    _ref_hit, _ref_orphan = _ref_items["ref-smoke.txt"], _ref_items["ref-orphan.txt"]
    check("335 index 下发 ref_count/refs 且 refs 带 project_name",
          _ref_hit["ref_count"] == 1 and len(_ref_hit["refs"]) == 1
          and _ref_hit["refs"][0] == {"id": _ref_mid, "project_id": _ref_pid,
                                      "project_name": "clref"},
          str(_ref_hit.get("refs")))
    check("336 零引用资产是 0/[] (不是 null 也不是字段缺失)",
          _ref_orphan.get("ref_count") == 0 and _ref_orphan.get("refs") == [],
          f"ref_count={_ref_orphan.get('ref_count')!r} refs={_ref_orphan.get('refs')!r}")
    _ref_ev = [x for x in _tc_ref.get("/api/evolutions").json()["items"]
               if x.get("name") == "ref-smoke.txt"]
    check("337 /api/evolutions 形状不变 (条目不含 ref_count/refs)",
          bool(_ref_ev) and "ref_count" not in _ref_ev[0] and "refs" not in _ref_ev[0],
          "未找到 ref-smoke.txt" if not _ref_ev else str(sorted(_ref_ev[0])))
except ImportError as _e_ref:  # 无 fastapi 环境跳过
    print(f"SKIP 335-337 (fastapi 未安装: {_e_ref})")

# ---- 338: seed dry_run 不依赖 embedder 可达 (桩化 embed_one 必须不被调用) ----
_stub_conn = db_mod.init(os.path.join(tmp, "seed_dry_stub.db"))
_orig_embed_one = mem_mod.llm.embed_one
_stub_calls: list = []


def _boom_embed_one(_text):
    _stub_calls.append(_text)
    raise AssertionError("dry_run 不应调用 embedder")


try:
    mem_mod.llm.embed_one = _boom_embed_one
    _stub_rep = seed_mod.apply(_stub_conn, dry_run=True)
    _stub_err = None
except Exception as _e_stub:  # noqa: BLE001 - 桩抛出的异常即失败信号
    _stub_rep, _stub_err = {}, _e_stub
finally:
    mem_mod.llm.embed_one = _orig_embed_one
check("338 seed dry_run 不调用 embedder (无 embedder 也能出报告)",
      _stub_err is None and not _stub_calls
      and _stub_rep.get("starter_missing") is False
      and len(_stub_rep.get("insights_added", [])) == 4,
      f"err={_stub_err!r} calls={len(_stub_calls)} added={len(_stub_rep.get('insights_added', []))}")
_stub_conn.close()

print()
if fails:
    print("FAILED:", fails)
    sys.exit(1)
print("ALL OFFLINE TESTS PASSED")
