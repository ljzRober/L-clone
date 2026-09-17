# 洞察卡三段化 + 引用就地 + 上限 100 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** 把洞察卡模板从四段（要点/背景/影响/归属）改成三段，引用改为就地写在正文里；删掉「归属非空」的结构性拒绝；修掉三处引用重复；全局层注入上限默认 20 → 100。

**Architecture:** 改动集中在两个后端文件（`llm.py` 负责提示词与卡片形状判定，`memory.py` 负责注入上限、引用去重与链接助手）、一个前端文件（芯片去重）与测试。契约为 `openspec/changes/insight-three-section-card/proposal.md`。

**Tech Stack:** Python 3 / SQLite / FastAPI、原生 JS 单文件看板、零依赖离线测试（`BRAIN_LLM=dummy`）。

**Spec:** `openspec/changes/insight-three-section-card/proposal.md`

## Global Constraints

- `lclone/gate.py` **一行不动**（准入信号词表、阈值、分档是 SSOT，本次与它无关）。
- 自包含性规则**必须保留**：卡片必须含「要点」且至少含「背景」或「影响」。**只删**「归属非空」这一条。
- 向量去重阈值 `0.92`、归一化文本前 80 字规则**不变**。
- `organize` 的「只能合并 同项目 + 同等级」**不得放宽**。
- `/api/evolutions` 响应形状**不变**。
- 改进化资产必须走 `publish`（append-only 新版本），不得原地改写、不得绕过版本库写本地缓存。
- 前端动态内容必须经 `esc()`；可点元素必须键盘可达；不得把 `data-evo` + 事件委托回退成内联 `onclick`（上一变更刚修掉存储型 XSS）。
- 转义审计（检查 303）不得放松：`_SAFE_INTERP`、`_IDENT_SINKS`、审计逻辑不许改；`_DYN_SINKS` 只能按实测 RHS 同步。
- 全局层默认改 100 **不得**动 `project_limit=20`，也不得改变「每会话只注入一次」语义。

---

### Task 1: 三段卡 + 引用就地 + 三处去重 + 上限 100

**Files:**
- Modify: `lclone/llm.py`（提示词、`CARD_SECTIONS`、删 `CARD_SCOPE_RE` 与它的判定、docstring 措辞）
- Modify: `lclone/memory.py`（`bootstrap` 默认值、`evolutions_for_insight` 去重、`recall` 边扩展去重、`link_insight_to_evolution` 改就地追加）
- Modify: `lclone/frontend/index.html`（`openMem` 的 evo 芯片按名字去重）
- Test: `tests/test_offline.py`

**Interfaces:**
- Produces: `llm.CARD_SECTIONS == ("要点", "背景", "影响")`；`llm.extract_memories` 不再要求「归属」段。
- Produces: `bootstrap(conn, query="", project_id=None, k=5, global_limit=100, project_limit=20)`。
- Produces: `evolutions_for_insight(conn, insight_id)` 对同一资产名只返回一次。
- Produces: `recall(...)` 返回的进化资产条目按名字唯一。

- [ ] **Step 1: 写失败测试**（在 `tests/test_offline.py` 汇总块之前插入）

```python
# ---- 345+: 三段卡 / 引用就地 / 去重 / 全局层上限 100 ----
check("345 提示词骨架为三段且不再要求归属",
      llm_mod.CARD_SECTIONS == ("要点", "背景", "影响")
      and not hasattr(llm_mod, "CARD_SCOPE_RE"), str(llm_mod.CARD_SECTIONS))
_three = "要点：结论。\n背景/为什么：因为。\n影响/以后注意：所以。"
llm_mod.chat = lambda *a, **k: _three
_e3 = llm_mod.extract_memories("用户：随便\n助手：随便")
check("346 无归属段的三段卡照常成卡", len(_e3) == 1 and "归属" not in _e3[0]["content"], str(_e3)[:80])
llm_mod.chat = lambda *a, **k: "要点：只有结论。"
check("347 残卡(只有要点)仍会被拒", llm_mod.extract_memories("用户：x\n助手：y") == [])
llm_mod.chat = lambda *a, **k: "要点：结论。\n背景/为什么：因为。\n影响/以后注意：所以。\n归属："
check("348 归属为空不再构成拒绝 (旧规则已删)", len(llm_mod.extract_memories("用户：x\n助手：y")) == 1)

# 引用去重: 同一张卡重复提及同一资产 → 只带出一次
_dup_conn = db_mod.init(os.path.join(tmp, "dupevo.db"))
_dup_pid = proj_mod.add_project(_dup_conn, "dup", str(demo_root), "")
mem_mod.create_evolution(_dup_conn, name="dup-tool.py", kind="tool", content="print(1)",
                         project_id=None)
_dup_ins = mem_mod.remember(_dup_conn,
    "要点：用 dup-tool 跑；再提一次 [[evo:dup-tool.py]]，正文里又说 [[evo:dup-tool.py]]。\n"
    "背景/为什么：验证去重。\n影响/以后注意：只应带出一次。", level="insight",
    project_id=None, confirmed=True)
_evs = mem_mod.evolutions_for_insight(_dup_conn, _dup_ins)
check("349 evolutions_for_insight 按资产名去重", len(_evs) == 1, f"n={len(_evs)}")
_rl = mem_mod.recall(_dup_conn, "dup-tool 去重", k=5, project_id=None, follow_links=True)
_evo_hits = [x for x in _rl if x.get("via_evolution")]
check("350 recall 边扩展同一资产只出现一次",
      len(_evo_hits) == len({x.get("evo_name") for x in _evo_hits}), f"hits={len(_evo_hits)}")
_dup_conn.close()

# 全局层上限默认 100
import inspect as _insp
check("351 bootstrap 全局层默认上限 100",
      _insp.signature(mem_mod.bootstrap).parameters["global_limit"].default == 100
      and _insp.signature(mem_mod.bootstrap).parameters["project_limit"].default == 20)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /Users/didi/github/L-clone && PYTHONIOENCODING=utf-8 .venv/bin/python tests/test_offline.py 2>&1 | grep -E "^(PASS|FAIL) 3(4[5-9]|5[01])"`
Expected: 345/346/348/349/350/351 FAIL（`归属` 仍在、无去重、默认仍 20）。

- [ ] **Step 3: 改 `lclone/llm.py`**

1. `CARD_SECTIONS = ("要点", "背景", "影响")`（删 `"归属"`），并把上方注释里的「四段分行 (要点/背景·为什么/影响·以后注意/归属)」改为「三段分行 (要点/背景·为什么/影响·以后注意)」。
2. **删除** `CARD_SCOPE_RE` 常量及其注释块（归属字段那段）。
3. 在 `extract_memories` 里**删除**归属判定两行：
```python
        # 归属: 必须有归属段且值非空 (填不出来 = 连归属都说不清, 结构性拒绝)
        if not CARD_SCOPE_RE.search(body):
            continue
```
4. 提示词骨架改为：
```python
        "每条 insight SHALL 按「三段分行」写, 自带背景与后果, 让人独立读懂 (共 2-4 句):\n"
        "  要点：<一句话结论>\n"
        "  背景/为什么：<为什么这么定/背景/推理>\n"
        "  影响/以后注意：<带来什么/以后注意什么>\n"
        "若这条洞察指向某个进化资产 / 契约 / 源文件, 就在**提到它的那句话里**写 [[evo:名字]] / "
        "[[spec:标识]] / [[src:路径]]; 不要单独起一行做引用列表。\n"
```
5. `extract_memories` docstring 里那段「归属: 若某 insight 明确对应仓库内某具体 spec/文件…」改为「引用: 若某 insight 明确对应仓库内某具体 spec/文件/进化资产, **就地**在正文里写 `[[spec:id]]`/`[[src:path]]`/`[[evo:名字]]`（link, not copy）；全局级记忆无仓库上下文时不标此类链接（只有 `[[m:N]]` 跨记忆链接）。」

- [ ] **Step 4: 改 `lclone/memory.py` 四处**

1. `bootstrap` 签名：`global_limit: int = 20` → `int = 100`（`project_limit` 保持 20）。
2. `evolutions_for_insight` 去重：
```python
    out = []
    seen: set = set()
    for name in evo_refs(row["content"]):
        if name in seen:
            continue
        seen.add(name)
        c = read_evolution_file(name, conn)
        if c is not None:
            out.append({"name": name, ...})
    return out
```
3. `recall` 的进化边扩展：在 append 前用 `seen_evo = set()` 去重：
```python
    if base:
        seen_evo: set = set()
        base_snapshot = list(base)
        for x in base_snapshot:
            for evo in evolutions_for_insight(conn, x["id"]):
                if evo["name"] in seen_evo:
                    continue
                seen_evo.add(evo["name"])
                base.append({... 原样 ...})
```
（`evo_by_insight` 预取可保留，也可合并进同一循环；行为必须等价。）
4. `link_insight_to_evolution` 改为**就地追加**（不再新起一行）：
```python
    ref = f"[[evo:{evolution_id}]]"
    if ref in content:
        return
    lines = content.rstrip().splitlines()
    idx = next((i for i, ln in enumerate(lines) if ln.strip().startswith("影响")), None)
    if idx is None:
        idx = len(lines) - 1 if lines else 0
    if lines:
        lines[idx] = lines[idx].rstrip() + f"（关联资产：{ref}）"
        new_content = "\n".join(lines)
    else:
        new_content = ref
```
（函数 docstring 同步为「把引用就地追加到『影响/以后注意』段末尾」）

- [ ] **Step 5: 改 `lclone/frontend/index.html` 的芯片去重**

`openMem` 里解析 `[[evo:…]]` 的那段改为按名字去重（保持既有 `<button class="m-evo" data-evo>` + 事件委托与 `esc()`）：
```js
  const evoSeen = new Set();
  (m.content.match(/\[\[evo:([^\]\n]+)\]\]/g) || []).forEach(tag => {
    const name = tag.slice(6, -2);
    if (evoSeen.has(name)) return;      // 同一张卡重复提及同一资产只出一个芯片
    evoSeen.add(name);
    build.push(`<span>→ <button class="m-evo" data-evo="${esc(name)}">${esc(name)}</button>（进化资产）</span>`);
  });
```

- [ ] **Step 6: 改既有断言（行为变更的连带）**

`tests/test_offline.py` 里以四段/归属为前提的用例需按新契约改写：
- `323 归属为空 → 结构性拒绝` —— 该行为已删，改为**正向断言**（缺归属仍成卡）；
- `313`/`321`/`322` 等断言里带 `归属：无` 的样例可保留（三段卡兼容多出的段），但断言文案若写「四段」需改成「三段」；
- `2466`/`2496`/`2502`/`2512`/`2527`/`2529`/`2580`/`2602`/`2606` 等样例中的 `\n归属：无` 可保留（不报错），但**不要**因为样例保留就让新断言依赖它。
改完逐个确认：**每条断言都必须仍能失败**，不得改成恒真。

- [ ] **Step 7: 跑全量测试**

Run: `cd /Users/didi/github/L-clone && PYTHONIOENCODING=utf-8 .venv/bin/python tests/test_offline.py 2>&1 | tail -4`
Expected: 末行 `ALL OFFLINE TESTS PASSED`，303 PASS，`FRONTEND OK`，345–351 全 PASS。

- [ ] **Step 8: 提交**

```bash
git add lclone/llm.py lclone/memory.py lclone/frontend/index.html tests/test_offline.py
git commit -m "feat(memory): 洞察卡三段化(去归属)+引用就地+三处引用去重+全局层上限 100"
```

---

### Task 2（控制器自做，不派 subagent）: 文档、进化资产与线上数据

- 进化资产 `洞察格式模型.md` 发 v4：三段骨架 + 「引用就地写，不单独起引用行」；`记忆准入标准.md` 更新「结构规则」段（删除「归属非空」硬规则，保留自包含性）。
- 仓库 `lclone/data/starter/evolutions/` 两个文件与 `lclone/data/starter/insights.md` 同步（种子源必须与服务器一致）。
- 线上数据：`#796`/`#797` 去掉末尾重复引用行；`#655` 改写为三段表述。
- spec delta：`memory-capture` 的「记忆分类与确认」（MODIFIED，携带全部原场景）与「分工边界」（MODIFIED）改写，并 ADDED「引用去重」。

## Self-Review

- **Spec coverage**：三段卡 ← Task 1 Step 3/6；引用就地 ← Step 3/4；去重 ← Step 4/5；上限 100 ← Step 4；数据与资产 ← Task 2；delta ← Task 2。
- **Placeholder scan**：无 TBD；每个代码步骤都给了可直接落地的片段。
- **Type consistency**：`CARD_SECTIONS` 在三处（常量、提示词骨架、测试 345）表述一致；`global_limit=100`/`project_limit=20` 在签名与测试 351 一致；去重键统一用**资产名**（不是 hash/版本）。
