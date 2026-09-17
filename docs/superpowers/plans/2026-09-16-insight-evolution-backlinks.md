# 洞察↔进化资产 双向引用 + 跨层去重 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让「洞察 ↔ 进化资产」的引用在看板两侧都可见、可点击互跳，并给记忆写入补上跨层（全局层↔项目层）去重，使库里不再长出新的一对重复卡。

**Architecture:** 后端只做两件小事——给既有去重函数加一个「是否跨层扫描」开关（默认关，现有同域语义与阈值一字不改），并把 `insights_for_evolution` 修正为只取 active、带项目名；`/api/evolution/index` 追加 `ref_count`/`refs` 两个纯追加字段，`/api/evolutions` 形状不动。前端复用既有面板：进化面板渲染反向引用条，记忆弹窗把 `[[evo:...]]` 渲染成芯片并允许弹窗浮在面板之上。

**Tech Stack:** Python 3 / SQLite / FastAPI（`lclone/`）、原生 JS 单文件看板（`lclone/frontend/index.html`）、零依赖离线测试脚本（`tests/test_offline.py`，`BRAIN_LLM=dummy`）。

**Spec:** `openspec/changes/insight-evolution-backlinks/proposal.md`（delta 写在 `openspec/changes/insight-evolution-backlinks/specs/`）

## Global Constraints

- 闸门判定标准 SHALL 仍单一来源在 `lclone/gate.py`；本计划**不得**改 `gate.py` 任何常量、词表、阈值、分档。
- 向量去重阈值 = `0.92`；归一化文本去重键 = 去空白标点后前 80 字。两者**不变**，本计划只加「扫描范围」。
- `organize` 的硬约束「只能合并 同项目 + 同等级(insight)」**不得放宽**（跨项目/跨等级由代码强制拒绝）。
- `GET /api/evolutions` 响应形状（`items[{name,ext,size,mtime,is_dir,children,content}]`）**不得改变**，只允许追加字段；新字段加在 `GET /api/evolution/index`。
- 进化资产权威**唯一**在服务器版本化内容寻址库；本地 `~/.lclone/evolution/` 只是可复现缓存——本计划**不得**写本地缓存目录。
- 前端所有动态内容 SHALL 经既有 `esc()` 转义；可点击元素 SHALL 键盘可达；本计划不引入新动画。
- 数据清理（删重复卡）走 `review`，**经用户确认后**才执行；代码任务不得调用任何删除类接口。

---

### Task 1: 后端 —— 跨层去重 + 反向引用

**Files:**
- Modify: `lclone/memory.py`（`_is_duplicate` / `_is_text_duplicate` / `capture` 调用处 / `insights_for_evolution`）
- Modify: `lclone/seed.py`（`apply` 里落库判重）
- Modify: `lclone/web.py`（`/api/evolution/index` 追加字段）
- Test: `tests/test_offline.py`（在末尾汇总块之前新增一节）

**Interfaces:**
- Produces: `_is_duplicate(conn, emb, project_id=None, threshold=0.92, limit=300, *, cross_layer=False) -> bool`；`_is_text_duplicate(conn, content, project_id=None, *, cross_layer=False, limit=300) -> bool`。`cross_layer` 语义：`project_id` 非空 → 扫「该项目 + 全局层」；`project_id is None` → 扫「全部层级（全局 + 所有项目）」；`cross_layer=False` → 完全保持现有行为。
- Produces: `insights_for_evolution(conn, evolution_id) -> List[dict]`，每项含 `{id, project_id, content, reason, project_name}`，只含 `status='active'` 的 insight。
- Produces: `GET /api/evolution/index` 的每一项追加 `ref_count: int` 与 `refs: [{id, project_id, project_name}]`（Task 2 消费）。

- [ ] **Step 1: 写失败测试**

> 判重是**捕获/种子路径**的能力；`remember()` 是「用户显式记录」通道，**刻意不做去重**（恒插入并返回新 id）。所以测试直接打判重助手本身，不改 `remember` 的既有语义。

在 `tests/test_offline.py` 的 `print()` 汇总块（`print()` + `if fails:` 之前）插入本节：

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python tests/test_offline.py 2>&1 | grep -E "^(PASS|FAIL) 33"`
Expected: `FAIL 329`/`FAIL 332`（`cross_layer` 形参还不存在 → `TypeError`，脚本会中断；此时能确认测试确实在跑新代码路径）。若因 `TypeError` 整体中断，属预期，进入 Step 3。

- [ ] **Step 3: 实现 `_is_duplicate` / `_is_text_duplicate` 的 `cross_layer`**

`lclone/memory.py`，把两个函数的签名与查询条件改为：

```python
def _is_duplicate(conn: sqlite3.Connection, emb: List[float],
                  project_id: Optional[int] = None,
                  threshold: float = 0.92, limit: int = 300,
                  cross_layer: bool = False) -> bool:
    """写入去重: 与同一归属内已有的记忆向量相似度 >= threshold 视为重复。

    cross_layer=True 时扩大**扫描范围**（阈值与规则不变）:
      - project_id 非空 → 该项目 + 全局层 (全局层在任何会话都加载, 已覆盖即重复);
      - project_id 为 None → 全部层级 (种子等通用内容不该与任何层的既有卡重复)。
    """
    q = ("SELECT embedding FROM memories"
         " WHERE status IN ('active','pending') AND embedding IS NOT NULL")
    params: list = []
    if project_id is None:
        if not cross_layer:
            q += " AND project_id IS NULL"
    elif cross_layer:
        q += " AND (project_id=? OR project_id IS NULL)"
        params.append(project_id)
    else:
        q += " AND project_id=?"
        params.append(project_id)
    q += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    for r in conn.execute(q, params).fetchall():
        if r["embedding"] and _cosine(emb, unpack_vec(r["embedding"])) >= threshold:
            return True
    return False
```

`_is_text_duplicate` 用同一套分支：

```python
def _is_text_duplicate(conn: sqlite3.Connection, content: str,
                       project_id: Optional[int] = None,
                       cross_layer: bool = False,
                       limit: int = 300) -> bool:
    """同一归属内, 归一化文本相同的记忆视为重复 (active + pending 都查)。

    cross_layer 语义与 `_is_duplicate` 完全一致 (只扩扫描范围, 不改判重规则)。
    """
    key = _norm_for_dup(content)
    if not key:
        return False
    q = ("SELECT content FROM memories WHERE status IN ('active','pending')")
    params: list = []
    if project_id is None:
        if not cross_layer:
            q += " AND project_id IS NULL"
    elif cross_layer:
        q += " AND (project_id=? OR project_id IS NULL)"
        params.append(project_id)
    else:
        q += " AND project_id=?"
        params.append(project_id)
    q += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    for r in conn.execute(q, params).fetchall():
        if _norm_for_dup(r["content"]) == key:
            return True
    return False
```

- [ ] **Step 4: capture 调用处启用跨层（项目卡）**

`lclone/memory.py` 的 `_capture_impl` 里两处调用改为（全局卡 `project_id is None` → `cross_layer=False`，行为不变）：

```python
        if _is_text_duplicate(conn, content, project_id, cross_layer=project_id is not None):
            continue
        emb = llm.embed_one(content)
        # 洞察进草稿待确认 (B 类); 写入前去重
        if _is_duplicate(conn, emb, project_id=project_id, cross_layer=project_id is not None):
            continue
```

- [ ] **Step 5: seed 落库前补跨层向量去重**

`lclone/seed.py` 的 `apply`，把 embedding 计算提前到判重之前，并在文本判重后补向量判重：

```python
        emb = llm.embed_one(content)
        # 库里已有语义/文本近乎相同的记忆 → 不种, 免得制造重复 (跨层: 任意项目里已有等价卡也算)
        if mem_mod._is_text_duplicate(conn, content, None, cross_layer=True) \
                or mem_mod._is_duplicate(conn, emb, None, cross_layer=True):
            report["insights_skipped"].append(key)
            if not dry_run:
                _mark(conn, state_key)
            continue
        report["insights_added"].append(key)
        if dry_run:
            continue
        conn.execute(
            "INSERT INTO memories(project_id, level, content, reason, status,"
            " source_type, source_ref, embedding, confirmed_at)"
            " VALUES (NULL, 'insight', ?, ?, 'active', 'seed', ?, ?, datetime('now'))",
            (content, "首次安装预置的通用洞察", ref, pack_vec(emb)),
        )
        _mark(conn, state_key)
```

（删掉原来在 `report["insights_added"].append(key)` 之后的那次 `emb = llm.embed_one(content)`，不要重复计算。）

- [ ] **Step 6: 修正 `insights_for_evolution`**

`lclone/memory.py`：

```python
def insights_for_evolution(conn: sqlite3.Connection, evolution_id: str) -> List[dict]:
    """找指向某进化文件的 insight (只含 active; 带项目名, 供看板与工具直接展示)。"""
    rows = conn.execute(
        "SELECT m.id, m.project_id, m.content, m.reason, p.name AS project_name"
        " FROM memories m LEFT JOIN projects p ON p.id = m.project_id"
        " WHERE m.level='insight' AND m.status='active'"
    ).fetchall()
    return [{"id": r["id"], "project_id": r["project_id"], "content": r["content"],
             "reason": r["reason"], "project_name": r["project_name"]}
            for r in rows if evolution_id in evo_refs(r["content"])]
```

- [ ] **Step 7: `/api/evolution/index` 追加引用字段**

`lclone/web.py` 的 `evo_index`，在 `row["base_version"] = row.get("version")` 之后、`items.append(row)` 之前插入：

```python
            # 反向引用: 谁在用这个资产 (纯追加字段, /api/evolutions 形状不受影响)
            _refs = mem_mod.insights_for_evolution(conn, row["name"])
            row["ref_count"] = len(_refs)
            row["refs"] = [{"id": r["id"], "project_id": r["project_id"],
                            "project_name": r["project_name"]} for r in _refs]
```

（`web.py` 已 `from . import memory as mem_mod`；若 import 名不同，按文件现有别名改。）

- [ ] **Step 8: 跑测试确认通过**

Run: `python tests/test_offline.py 2>&1 | tail -5`
Expected: `ALL OFFLINE TESTS PASSED`，且新用例 `PASS 330`。

- [ ] **Step 9: 提交**

```bash
git add lclone/memory.py lclone/seed.py lclone/web.py tests/test_offline.py
git commit -m "feat(memory): 跨层写入去重 + 进化资产反向引用 (index 追加 ref_count/refs)"
```

---

### Task 2: 前端 —— 双向引用条 + 弹窗层级

**Files:**
- Modify: `lclone/frontend/index.html`（CSS 一行、面板加一个容器、`evoRender`/`showEvo`/`evoReset`/`openMem` 与 `evoRefreshList` 的行渲染）

**Interfaces:**
- Consumes: `GET /api/evolution/index` 的 `ref_count` / `refs`（Task 1 Step 7）；`openMem(id)`、`openEvo(name)`、`EVO_META`、`MEMS`（均为本文件既有符号）。
- Produces: `evoRenderRefs(name)`、`openMem(mid, above)`（第二参数为真时记忆弹窗浮在进化面板之上）。

- [ ] **Step 1: 加 CSS（弹窗置顶层级）**

`lclone/frontend/index.html` 的 `.modal-bg.on { display:flex; }` 之后加一行：

```css
.modal-bg.on-top { z-index:60; }   /* 从引用条点进的记忆弹窗: 浮在进化面板之上 */
```

- [ ] **Step 2: 面板加反向引用容器**

在 `<div class="evo-note" id="evo-note"></div>` 之前插入：

```html
        <div class="evo-refs" id="evo-refs"></div>
```

- [ ] **Step 3: 渲染反向引用条**

在 `evoReasonText` 之后新增（沿用既有语汇，不引入新配色；计数为 0 时是**静默态而非隐藏**——孤儿资产必须看得见）：

```js
// 反向引用条: 哪个洞察在支撑当前资产 (方向 ← 表示"被谁指向")。
// 计数为 0 不隐藏而是显式说明"无人引用"——零引用是本次核查暴露过的问题, 不能靠隐身掩盖。
function evoRenderRefs(name) {
  const box = $('evo-refs');
  if (!box) return;
  const m = (EVO_META && EVO_META[name]) || null;
  const refs = (m && Array.isArray(m.refs)) ? m.refs : null;
  if (!refs) { box.innerHTML = ''; return; }
  if (!refs.length) {
    box.innerHTML = '<span class="evo-refs-empty">← 暂无洞察引用该资产（孤儿资产）</span>';
    return;
  }
  const chips = refs.map(r => {
    const who = r.project_name ? '项目「' + esc(r.project_name) + '」' : '全局层';
    return `<button class="evo-ref" data-ref="${r.id}">← #${r.id} · ${esc(who)}</button>`;
  }).join('');
  box.innerHTML = `<span class="evo-refs-sum">← ${refs.length} 条洞察引用它：</span>${chips}`;
}
```

- [ ] **Step 4: 接上渲染与点击**

在 `showEvo(name)` 的 `await evoHistLoad(name);` 之后加一行：

```js
    evoRenderRefs(name);               // 反向引用随资产一起渲染 (历史预览不改它: 引用属于资产而非版本)
```

在 `evoReset()` 里 `$('evo-hist-list').innerHTML = '';` 之后加：

```js
  $('evo-refs').innerHTML = '';
```

在面板事件委托处（文件里已有 `#evo-list .evo-row` 的点击委托，找到同一段）补一条 `#evo-refs .evo-ref` 的委托：

```js
document.addEventListener('click', e => {
  const chip = e.target.closest && e.target.closest('#evo-refs .evo-ref');
  if (!chip) return;
  const id = Number(chip.dataset.ref);
  if (id) openMem(id, true);         // above=true: 弹窗浮在进化面板之上, 关闭后回到面板
});
```

- [ ] **Step 5: `openMem` 支持置顶与 `[[evo:...]]` 芯片**

把 `openMem(mid)` 的签名与 `#m-links` 赋值段改为：

```js
function openMem(mid, above) {
  const m = MEMS.find(x => x.id === mid); if (!m) return;
  CUR_MID = mid;
  $('m-title').textContent = '记忆详情';
  $('m-content').value = m.content;
  $('m-level').value = m.level || 'insight';
  $('m-owner').value = m.project_id || '';
  $('m-meta').textContent = `#${m.id} · ${m.project_id ? '项目「' + (m.project_name || '') + '」' : '全局层'} · ${m.created_at} · ${m.source_type === 'auto' ? '自动捕获' : '主动记忆'}`;
  $('m-owner-hint').textContent = m.project_id ? '（改为全局层 = 上升）' : '（选择项目 = 下降）';
  const outs = LINKS.filter(l => l.source_id === mid).map(l => l.target_id);
  const ins = LINKS.filter(l => l.target_id === mid).map(l => l.source_id);
  const build = [];
  outs.forEach(t => { const tm = MEMS.find(x => x.id === t); build.push(`<span>→ <a onclick="openMem(${t})">#${t}${tm ? ' · ' + esc(tm.content.slice(0, 14)) : ''}</a></span>`); });
  ins.forEach(s => { const sm = MEMS.find(x => x.id === s); build.push(`<span>← <a onclick="openMem(${s})">#${s}${sm ? ' · ' + esc(sm.content.slice(0, 14)) : ''}</a></span>`); });
  // 进化资产引用: 洞察正文里的 [[evo:名字]] → 芯片, 点击跳到进化面板并选中该资产
  (m.content.match(/\[\[evo:([^\]\n]+)\]\]/g) || []).forEach(tag => {
    const name = tag.slice(6, -2);
    build.push(`<span>→ <a onclick="openEvo('${esc(name)}')">${esc(name)}</a>（进化资产）</span>`);
  });
  $('m-links').innerHTML = build.length ? '链接：' + build.join('') : '链接：无';
  $('btn-del').style.display = ''; $('btn-move').style.display = ''; $('btn-save').style.display = ''; $('btn-save').textContent = '保存修改';
  $('modal').classList.toggle('on-top', !!above);   // 从引用条进入才置顶
  $('modal').classList.add('on');
}
```

> `openEvo(name)` 会先 `closeModal()`（同时清掉 CUR_MID）再开进化面板，方向正确；`openEvo` 里补一句 `$('modal').classList.remove('on-top');` 免得置顶态残留到下一次普通入口。

- [ ] **Step 6: 清单位置显示引用数**

在 `evoRefreshList()` 的行模板里，把 `const tag = ...` 那行之后补一行并在 `s +=` 中带上计数：

```js
          const rc = (m.ref_count != null) ? m.ref_count : 0;
          const refTag = tomb ? '' : ` · ${rc} 引用`;
```

模板字符串里 `${esc(tag + v + sz)}` 改为 `${esc(tag + v + sz + refTag)}`（引用数与版本/大小同样是服务端下发的值，继续走 `esc`）。

- [ ] **Step 7: 跑离线测试并处理转义审计（必做，勿跳）**

Run: `cd /Users/didi/github/L-clone && PYTHONIOENCODING=utf-8 .venv/bin/python tests/test_offline.py 2>&1 | tail -5`

本步新增的 `#evo-refs` 渲染是一处**新的 innerHTML 动态 sink**，会被检查 303「前端 innerHTML 插值转义审计」拦。若 303 FAIL 且 `dyn_bad` 里出现 `#evo-refs`：

1. 从 FAIL 行里**逐字**取出它打印的 `(选择器, RHS 原文)`；
2. 在 `tests/test_offline.py` 的 `_DYN_SINKS` 里追加该条，值写清楚理由（例如：`#evo-refs 引用条 —— 动态量 refs 来自 /api/evolution/index，逐项经 esc() 包裹后 join，其余为静态字面量；本 change 新增，显式冻结为例外`）；
3. 重跑，直到末行 `ALL OFFLINE TESTS PASSED`（注意：`_DYN_SINKS` 是**双向等号**——RHS 原文一变就失配，取值必须与打印完全一致）。

同时确认：`#m-links` 的 RHS 仍是 `build.length ? '链接：' + build.join('') : '链接：无'`（本步只往 `build` 里 push 元素，不改该表达式），因此既有登记项不会失配。

- [ ] **Step 8: 静态验证（无浏览器时的确定性检查）**

Run:
```bash
grep -n "on-top\|evo-refs\|evoRenderRefs\|openMem(id, true)" lclone/frontend/index.html
node --check <(sed -n '/<script>/,/<\/script>/p' lclone/frontend/index.html | sed '1d;$d') 2>/dev/null || echo "无 node，跳过语法检查"
```
Expected: 五个符号各至少命中一次；无 `SyntaxError`。

- [ ] **Step 9: 三处转义与可达性自查**

Run: `grep -n "evo-ref\|esc(name)\|esc(who)" lclone/frontend/index.html`
Expected: 引用芯片的 `who`、资产名、以及模板里的动态段都经 `esc()`；芯片用 `<button>`（键盘可达）。

- [ ] **Step 10: 提交**

```bash
git add lclone/frontend/index.html tests/test_offline.py
git commit -m "feat(web): 洞察↔进化资产双向引用条 (可点击互跳, 记忆弹窗可浮于面板之上)"
```

---

## Self-Review

- **Spec coverage**：`memory-capture` 新增「跨层去重」← Task 1 Step 3/4/5；`memory-capture` 新增「进化资产反向引用可查」← Task 1 Step 6；`evolution-store` 新增「清单携带引用计数」← Task 1 Step 7；`web-hierarchy` 新增「双向引用可见」← Task 2 Step 3~6。数据清理不在代码任务内（走确认闸门后单独执行）。
- **Placeholder scan**：无 TBD/TODO；每个代码步骤都给了可落地的完整片段。
- **Type consistency**：`cross_layer` 在 `_is_duplicate` / `_is_text_duplicate` / capture / seed 四处同名同义；`refs` 的元素形状 `{id, project_id, project_name}` 在 Task 1 产出与 Task 2 消费一致；`openMem(mid, above)` 的 `above` 只在引用条路径传 `true`。
