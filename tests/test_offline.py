"""离线自测: 无需 API Key, 无需第三方依赖 (BRAIN_LLM=dummy)。

运行: python tests/test_offline.py
"""

import json
import os
import pathlib
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
      gate.classify("今天看了一下午的日志文件内容").kind == gate.UNCERTAIN)
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
_rep2 = mem_mod.capture_report(conn, "今天看了一下午的日志文件内容", project_id=pid)
check("133 uncertain 档经 LLM 判定后仍可成卡",
      _rep2["gate"]["kind"] == "uncertain", str(_rep2["gate"]))

_orig_ex_cap = llm_mod.extract_memories
llm_mod.extract_memories = lambda t: [
    {"level": "insight", "content": f"决定统一口径第 {i} 版"} for i in range(5)]
_cap_ids = mem_mod.capture(conn, "决定统一口径五条一起来", project_id=pid)
llm_mod.extract_memories = _orig_ex_cap
check("134 单轮成卡上限 2 条", len(_cap_ids) == 2, f"{len(_cap_ids)} 条")

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

print()
if fails:
    print("FAILED:", fails)
    sys.exit(1)
print("ALL OFFLINE TESTS PASSED")
