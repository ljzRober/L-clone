# Evolution On-Demand Load Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让全局层的 `[[evo:名字]]` 指路卡在项目会话里也能被召回命中，从而顺边带出资产正文；并把「见到 `[[evo:]]` 必须先取正文」写进 skill。

**Architecture:** `recall()` 增加 `include_global` 开关（默认 False，保住既有函数级语义），面向会话的三个入口（MCP recall / `POST /api/recall` / bootstrap 的【相关记忆】）传 True。不内联正文、不改打分与去重规则。

**Tech Stack:** Python 3 / SQLite / FastAPI / MCP / lclone-memory skill（仓库源 + `~/.agents/skills/` 安装副本）

**Spec:** `openspec/changes/evolution-on-demand-load/proposal.md` + `openspec/changes/evolution-on-demand-load/specs/memory-capture/spec.md`

## Global Constraints

- 扩大候选集 SHALL NOT 改打分公式（`alpha` 加权）、相似度阈值、`link_extra` 限量、按资产名去重。
- 库内函数默认（不传 `include_global`）SHALL 保持「只召回该项目」；既有断言 `check("12 召回限定项目")` 必须继续通过。
- 【全局记忆】全量注入 SHALL NOT 改变（`global_limit=100`、「每会话只注入一次」）；本变更只影响按 query 的【相关记忆】段。
- 无 query 时 SHALL NOT 额外加载任何资产正文。

---

### Task 1: `recall(include_global)` 与顺边带出

**Files:**
- Modify: `lclone/memory.py:728-748`（`recall` 签名与 WHERE）
- Test: `tests/test_offline.py`

**Interfaces:**
- Produces: `recall(conn, query, k=5, project_id=None, alpha=0.7, status="active", follow_links=True, link_extra=3, include_global=False)`

- [ ] **Step 1: 写失败测试**

```python
# ---- 364+: 会话召回覆盖全局层 ----
_ig = db_mod.init(os.path.join(tmp, "incglobal.db"))
_ig_pid = proj_mod.add_project(_ig, "igproj", str(demo_root), "")
mem_mod.remember(_ig, "要点：全局指路卡，写代码前先读 [[evo:ig-tool.md]]。\n"
                      "背景/为什么：验证全局层参与召回。\n影响/以后注意：顺边带正文。",
                 level="insight", project_id=None, confirmed=True)
mem_mod.remember(_ig, "要点：项目卡，讲别的。\n背景/为什么：占位。\n影响/以后注意：无。",
                 level="insight", project_id=_ig_pid, confirmed=True)
_ig_evo = mem_mod.create_evolution(_ig, name="ig-tool.md", kind="model",
                                   content="IG 工具正文内容", reason="测试")
_ig_def = mem_mod.recall(_ig, "全局指路卡 写代码前先读", project_id=_ig_pid,
                         follow_links=False)
check("364 函数默认仍只召回本项目",
      all(i["project_id"] == _ig_pid for i in _ig_def), str([i["id"] for i in _ig_def]))
_ig_all = mem_mod.recall(_ig, "全局指路卡 写代码前先读", project_id=_ig_pid,
                         follow_links=False, include_global=True)
check("365 include_global 后全局卡参与召回",
      any(i["project_id"] is None for i in _ig_all), str([i["id"] for i in _ig_all]))
check("366 顺边带出 evo 正文",
      any(i.get("via_evolution") and i["name"] == "ig-tool.md"
          and "IG 工具正文内容" in i["content"] for i in _ig_all),
      str([(i.get("name"), i.get("via_evolution")) for i in _ig_all]))
_ig.close()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `BRAIN_LLM=dummy .venv/bin/python tests/test_offline.py 2>&1 | tail -10`
Expected: `TypeError: recall() got an unexpected keyword argument 'include_global'`

- [ ] **Step 3: 实现**

```python
def recall(conn, query, k=5, project_id=None, alpha=0.7, status="active",
           follow_links=True, link_extra=3, include_global=False):
    """... include_global=True 且 project_id 给定时, 候选集 = 该项目 + 全局层。
    函数默认 False: 保持「只召回指定项目」的既有语义。"""
    qv = llm.embed_one(query)
    where = ("m.status=? AND m.level='insight' AND m.embedding IS NOT NULL"
             + _alive_filter())
    params: list = [status]
    if project_id is not None:
        if include_global:
            where += " AND (m.project_id=? OR m.project_id IS NULL)"
        else:
            where += " AND m.project_id=?"
        params.append(project_id)
    rows = conn.execute(
        "SELECT m.id, m.project_id, m.level, m.content, m.reason, m.source_ref,"
        " m.created_at, m.embedding, p.name AS project_name"
        " FROM memories m LEFT JOIN projects p ON p.id = m.project_id"
        f" WHERE {where}", tuple(params)).fetchall()
```

（其余打分、顺链、顺边 evo 逻辑一行不改。）

- [ ] **Step 4: 跑测试确认通过**

Run: `BRAIN_LLM=dummy .venv/bin/python tests/test_offline.py 2>&1 | tail -8`
Expected: 364-366 PASS，既有 `12 召回限定项目` 仍 PASS

- [ ] **Step 5: Commit**

```bash
git add lclone/memory.py tests/test_offline.py
git commit -m "feat(memory): recall can include global layer without changing function default"
```

---

### Task 2: 会话入口传 `include_global=True`

**Files:**
- Modify: `lclone/memory.py:886-891`（`bootstrap` 的【相关记忆】段）
- Modify: `lclone/mcp_server.py:342-348`（`recall` 分支）
- Modify: `lclone/web.py`（`/api/recall`）
- Modify: `lclone/cli.py`（`recall` 子命令新增 `--global/--no-global`，默认 global）
- Test: `tests/test_offline.py`

**Interfaces:**
- Consumes: `recall(..., include_global=)`（Task 1）
- Produces: `bootstrap()` 的【相关记忆】覆盖全局层；`POST /api/recall` 接受 `include_global`（默认 true）；MCP `recall` 默认 true

- [ ] **Step 1: 写失败测试**

```python
_bg = db_mod.init(os.path.join(tmp, "bootglobal.db"))
_bg_pid = proj_mod.add_project(_bg, "bgproj", str(demo_root), "")
mem_mod.remember(_bg, "要点：boot 全局指路卡 [[evo:bg-tool.md]]。\n背景/为什么：验证。\n"
                      "影响/以后注意：注入相关记忆。",
                 level="insight", project_id=None, confirmed=True)
mem_mod.create_evolution(_bg, name="bg-tool.md", kind="model", content="BG 正文", reason="t")
_bg_out = mem_mod.bootstrap(_bg, query="boot 全局指路卡", project_id=_bg_pid)
check("367 bootstrap 相关记忆带出全局卡与资产",
      "BG 正文" in _bg_out, _bg_out[-120:])
_bg.close()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `BRAIN_LLM=dummy .venv/bin/python tests/test_offline.py 2>&1 | tail -8`
Expected: `367` FAIL

- [ ] **Step 3: 实现**

- `memory.py` 的 bootstrap：`items = recall(conn, q, k=k, project_id=project_id, include_global=True)`。
- `mcp_server.py` recall 分支：`mem_mod.recall(..., include_global=True)`。
- `web.py` `/api/recall`：`include_global: bool = True` 入参透传。
- `cli.py`：`recall` 子命令加 `--no-global`（`action="store_false", dest="include_global", default=True`），传给 `mem_mod.recall`。

- [ ] **Step 4: 跑测试确认通过**

Run: `BRAIN_LLM=dummy .venv/bin/python tests/test_offline.py 2>&1 | tail -8`
Expected: 367 PASS

- [ ] **Step 5: Commit**

```bash
git add lclone/memory.py lclone/mcp_server.py lclone/web.py lclone/cli.py tests/test_offline.py
git commit -m "feat(recall): session-facing recall entries cover global layer"
```

---

### Task 3: skill 取正文纪律 + 安装副本同步

**Files:**
- Modify: `integrations/skill/SKILL.md`（新增规则 10）
- Modify: `~/.agents/skills/lclone-memory/SKILL.md`（安装副本，cp 同步）
- Modify: `lclone/cli.py`（`proj list` 输出 `remote`，便于按 remote 传 `project`）

- [ ] **Step 1: 加规则**

在「自动记忆规则」表后追加：

```markdown
10. **进化资产必须取正文**：注入的卡片里出现 `[[evo:名字]]` 时，动手前必须先用
    `mcporter call lclone.evolution_content name=<名字>`（或 `lclone evolution content <名字>`）
    取到资产正文；不得凭卡片里的一行摘要猜资产内容。取不到（名字写错 / 资产已删）时如实说明，
    不要编造资产内容。本地缓存（`~/.lclone/evolution/`）可能落后，优先走服务器版本库。
```

- [ ] **Step 2: 同步并校验**

```bash
cp integrations/skill/SKILL.md ~/.agents/skills/lclone-memory/SKILL.md
diff -q integrations/skill/SKILL.md ~/.agents/skills/lclone-memory/SKILL.md && echo SYNCED
grep -c "evolution_content" ~/.agents/skills/lclone-memory/SKILL.md
```

- [ ] **Step 3: 文档澄清**

`docs/CLI.md` / `docs/CONCEPTS.md` 里「召回限定项目」改为「函数级默认只召回指定项目；会话入口（recall/bootstrap 相关记忆）覆盖 该项目 + 全局层」。

- [ ] **Step 4: Commit**

```bash
git add integrations/skill/SKILL.md docs/CLI.md docs/CONCEPTS.md
git commit -m "docs(skill): require fetching evolution body when a card references [[evo:]]"
```

---

### Task 4: 回归

- [ ] **Step 1:** `BRAIN_LLM=dummy .venv/bin/python tests/test_offline.py 2>&1 | tail -5` → 全 PASS
- [ ] **Step 2:** `node tests/frontend_evo_test.js 2>&1 | tail -3` → 全 PASS
- [ ] **Step 3:** 线上验证（部署后）：
  `mcporter call lclone.recall query="偷懒阶梯 编码准则" project=lclone k=3` → 必须同时出现 `[[evo:code-laziness-ladder.md]]` 指路卡与其正文。

## Self-Review

- **Spec coverage**：召回覆盖全局层（Task 1/2）、分类加载（Task 1）、skill 纪律（Task 3，对应 proposal 的 What Changes 第 4 条）。
- **Placeholder scan**：无 TBD。
- **Type consistency**：`include_global` 在 memory/mcp/web/cli 四处名称与默认值一致（库内 False，会话入口 True）。
