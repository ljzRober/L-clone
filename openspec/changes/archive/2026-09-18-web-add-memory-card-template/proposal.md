## Why

洞察卡的形状契约（要点 / 背景·为什么 / 影响·以后注意）目前只在**自动捕获**通道被强制：`llm.extract_memories()` 做形状与自包含性校验，缺段的元报告/回声不成卡。而 Web「添加记忆」走的是另一条路——`POST /api/remember` → `memory.remember()`，该函数只归一化 `level`，无长度、无形状校验，且 Web 侧写死 `confirmed=True` 直接生效、跳过待确认。线上实测（active 66 条）：`manual` 26 条中 8 条完全没有三段标题，`auto` 40 条全部合规——缺口集中在手动通道。

本轮先只解决**入口默认值**这一半：新建记忆时给出三段骨架，让「格式正确的卡」成为默认路径；不做服务端校验、不改 `remember()` 语义。

## What Changes

- Web 新建记忆弹窗（工具栏「＋ 添加记忆」与列头 ＋ 两个入口）默认预填三段骨架，光标落在「要点」行末，用户只填内容。
- 保存前对未填段落做一次**软提示**（列出缺哪些段，可继续保存、取消则不写入）。
- 预填带来的回归面一并堵住：表单原样未填（三段标签俱在、正文一段没填）仍按「内容不能为空」拦下，不写入空骨架卡。
- 编辑既有记忆路径不受影响（不预填、不弹缺段提示），存量卡不被强行改形。
- **不改后端**：`/api/remember`、`memory.remember()`、MCP `remember`、CLI `remember` 一行不动。

## Capabilities

### New Capabilities

（无。）

### Modified Capabilities

- `web-hierarchy`：**修改**「记忆工作台」——新增场景「新建记忆默认三段骨架」（预填骨架 + 光标落点 + 缺段软提示 + 空骨架拦下），原有 13 个场景全部原样保留。

## Impact

- **前端**：`lclone/frontend/index.html`（`CARD_TEMPLATE`/`CARD_LABELS` 常量、`missingCardSections()`、`openAdd()`、`saveAdd()`）。
- **测试**：`tests/frontend_evo_test.js`（DOM 桩补 `setSelectionRange`；新增 346/346b/347/348/349/350/351）。
- **不影响**：后端与 API 形状、记忆准入闸门、提炼提示词、`remember()` 既有语义（含 `memory-capture` > 跨层去重那条「`remember()` SHALL NOT 改变既有语义」）、鉴权层。
- **部署**：`index.html` 是后端静态资源，上线需随容器重建（本轮不含部署动作）。

## 方案

新增两个常量与一个纯判定函数，改两个既有函数，均为前端内联脚本改动：

```js
const CARD_TEMPLATE = '要点：\n背景/为什么：\n影响/以后注意：';
const CARD_LABELS = ['要点', '背景', '影响'];

// 逐行扫描: 标签行开一个段, 段体 = 标签后残余 + 直到下一个标签之前的行;
// 段体去空白后为空即未填, 标签整段缺失也算未填
function missingCardSections(text) { … }
```

`openAdd()` → `c.value = CARD_TEMPLATE` + `c.setSelectionRange(3, 3)`；`saveAdd()` → 缺段 `confirm` 一次（取消即返回），模板原样未填则 `alert('内容不能为空：三段都还没填')`。

**标签文案是跨语言契约**：`要点`/`背景`/`影响` 同时是后端形状校验的匹配串（`lclone/llm.py` 的 `CARD_SECTIONS`/`CARD_REQUIRED`/`CARD_SUPPORTING`）与去重键的来源（`lclone/memory.py` 的 `_norm_for_dup` 取归一化前 80 字，即「要点」正文）。改前端模板即改契约，必须在注释里点明同步要求。

### 文件

- `lclone/frontend/index.html`：常量、`missingCardSections`、`openAdd`、`saveAdd`
- `tests/frontend_evo_test.js`：桩补 `setSelectionRange`；用例 346/346b/347/348/349/350/351

## Spec Constraints

- `web-hierarchy` > 记忆工作台 > 添加记忆（不变）：弹窗仍填写内容/等级/归属后确认，写入后刷新图形与计数；本轮只改默认值与保存前提示，不改变写入路径。
- `memory-capture` > 跨层去重（不变）：「`remember()`（用户显式记录通道）SHALL NOT 因此改变既有语义」——本轮后端零改动，该边界未被触碰。
- `memory-capture` > 自动捕获的卡片形状（不变）：形状/自包含性校验仍只作用于提炼通道；本轮不把手动通道纳入强校验（软提示不阻断）。
- `dsh-web-dashboard`（不变）：本次不涉及插件注入与看板端点。
