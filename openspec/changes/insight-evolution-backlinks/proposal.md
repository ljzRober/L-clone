## Why

看板里「洞察 ↔ 进化资产」的引用目前是**单向且不可见**的：`[[evo:文件名]]` 写在洞察正文里，只有洞察侧知道它指向谁；进化面板看一个资产时完全看不出"这条规则是被谁支撑的"。结果是引用关系只能靠人肉 grep——本次核查就发现 `记忆准入标准.md`、`会话归属与落库约定.md`、两个示例脚本以及 `keys.txt` 在库内**零引用**，而这一点平时根本看不出来。用户改一处（改资产正文 / 改洞察里的引用行）时无法看到另一侧，引用自然漂移。

同时本次核查发现**跨层重复**是结构性的：写入去重（`_is_duplicate` / `_is_text_duplicate`）按 `project_id` 分域比较，种子落库（`seed.apply`）只做归一化文本去重、不做向量去重，`organize` 又硬性拒绝跨项目/跨层合并。于是"全局层种子卡"与"项目层旧卡"说同一件事却互不可见——库里已经存在 `#656`(全局 seed) ↔ `#297`(项目 lclone)、`#655`(全局 seed) ↔ `#324`(项目 lclone) 这样的实例。

## What Changes

- **跨层写入去重（不改现有判定行为）**：`_is_duplicate` / `_is_text_duplicate` 增加 `cross_layer` 开关，默认 `False`（现有同域语义、阈值 0.92、80 字归一化规则一字不改）。规则按**覆盖面**判定，避免误杀：
  - 写**项目卡**时同时比对全局层——全局层在任何会话都加载，已覆盖则跳过（`cross_layer=True`）；
  - 写**全局卡**时**仍只比全局层**——全局卡不该被某个项目里的卡阻断（保持现有行为）；
  - 种子落库（`seed.apply`）**双向比对**：种子是首次安装的通用内容，库里已有等价记忆就不种（其代码注释本就写着"免得制造重复"），保留现有文本去重并补上向量跨层去重。
  - `organize` 的「只能合并 同项目 + 同等级」**保持不变**（现有 spec 场景不动）。
- **双向引用可见**：`GET /api/evolution/index` 追加 `ref_count` 与 `refs[{id, project_id, project_name}]`（纯追加字段，`GET /api/evolutions` 响应形状不变）；
  - 进化面板：每个资产显示被引用数，详情区列出引用它的洞察，点洞察 → 打开记忆弹窗（记忆弹窗浮在面板之上，关闭后回到面板）；
  - 记忆弹窗：`[[evo:name.ext]]` 渲染为可点击芯片，点芯片 → 打开进化面板并选中该资产。
  - 两端都只是**显示 + 跳转**，不做内容自动回写——改哪边仍由人决定，但改之前能看见对面是谁。
- **数据清理**：按"保留哪张 / 删哪张"清单处理本次核查出的重复卡（走 `review` 的 edit + delete，逐条过确认闸门后执行）。

## Capabilities

### New Capabilities

（无。修的是既有引用关系与准入去重的完整性，不引入新 capability 路径。）

### Modified Capabilities

- `memory-capture`：新增「跨层去重」需求（写项目卡时全局层参与比对；全局卡与种子落库的既有语义不变）；新增「进化资产反向引用可查」需求（一个资产 SHALL 能查出引用它的洞察，供看板与工具消费）。
- `evolution-store`：新增「清单携带引用计数」需求（`/api/evolution/index` 追加 `ref_count` / `refs`，`/api/evolutions` 形状不变）。
- `web-hierarchy`：新增「洞察与进化资产双向引用可见」需求（两侧显示 + 点击互跳，记忆弹窗可从进化面板之上打开）。

## 方案

### 后端（`lclone/memory.py` + `lclone/web.py`）

1. `_is_duplicate(conn, emb, project_id=None, *, cross_layer=False, ...)`：`cross_layer=True` 且 `project_id` 非空时，扫描范围从"该项目"扩为"该项目 + 全局层"；`project_id IS NULL` 时行为不变。`_is_text_duplicate` 同形参、同语义。
2. `capture` 路径：项目卡调用处传 `cross_layer=True`；全局卡保持 `cross_layer=False`（覆盖面规则）。
3. `seed.apply`：现有 `_is_text_duplicate(conn, content, None)` 之后补一次 `_is_duplicate(conn, emb, None, cross_layer=True)`；注意**先算 embedding 再判重**，避免判完才发现要发布。
4. `insights_for_evolution(conn, name)` 修正为：只取 `status='active'`、带 `project_name`（LEFT JOIN projects），并保持"精确匹配 `[[evo:name]]`"语义（不做模糊/大小写放宽）。
5. `web.py` `/api/evolution/index`：对每个条目追加 `ref_count` 与 `refs`（字段缺失时给 `0` / `[]`，前端无需判空分支）；`/api/evolutions` 一行不动。

### 前端（`lclone/frontend/index.html`）

- **Frontend Design**：沿用看板既有暗色 token 与 `.tag`/`chip` 语汇，不引入新配色与新字体——这里要的是"在既有信息密度里多一条可信的边"，不是重做视觉。签名元素 = **双向引用条**：一条水平条目，左端是资产名、右端是引用它的洞察数，方向用 `→`（洞察指向资产）与 `←`（资产被哪些洞察指向）区分，计数为 0 时显示为静默态（灰、无链接）而不是隐藏——**孤儿资产必须看得见**，否则本次核查发现的零引用问题下次还是发现不了。
- 引用芯片全部走既有 `esc()` 转义；可点击元素用 `<button>`/带 `role` 的 `<a>`，保留键盘可达与 `:focus-visible` 焦点环；无新增动画，因此无新增 `prefers-reduced-motion` 分支。
- 记忆弹窗需要能从进化面板之上打开：现有 `.modal-bg` 同为 `z-index:40`、`#evo-exp` 在 DOM 里靠后，直接开 `#modal` 会被压在下面。给 `#modal` 加一个 `on-top` 类（`z-index:60`）由"从引用进入"的路径设置，关闭时移除，避免影响正常入口的层级。

### 数据清理（不走代码）

按确认闸门的清单执行：`review` 的 `edit`（把保留卡补成两卡要点）与 `delete`（删除被吸收卡）。跨层重复对（`#656`/`#297`、`#655`/`#324`）优先"保项目卡、删全局 seed 重复项"，因为项目卡的上下文更具体、且全局层可由项目卡升格补回。

## Spec Constraints

- `memory-capture` > 记忆分类与确认：闸门 SSOT 仍在 `gate.py`，本次**不改任何词表/阈值/判定分档**；向量去重阈值 0.92 与"归一化文本前 80 字"规则不变（新场景只加跨层扫描范围）。
- `memory-capture` > 记忆整理合并：⚠️「只能合并 同项目 + 同等级，跨项目/跨等级由代码强制拒绝」——本次**不得**放宽，跨层重复靠写入闸门拦，不靠事后 organize。
- `memory-capture` > 进化资产与链接：⚠️「权威 SHALL 唯一：服务器版本化内容寻址库」与「项目内脚本只记 ref、不入内容库」——引用展示只读，SHALL NOT 触发任何发布/写入。
- `memory-capture` > 闸门标准单一来源：⚠️ 判定标准集中在 `gate.py`；本次新增的是**去重扫描范围**，不是准入标准，SHALL NOT 往 `gate.py` 里加词表。
- `evolution-store` > 看板兼容：⚠️ `GET /api/evolutions` 响应形状不变（只允许附加字段）；本次新字段加在 `/api/evolution/index`。
- `evolution-store` > 本地只读缓存与同步：⚠️ 本地永远不是权威；引用信息只从服务器读，SHALL NOT 写入本地缓存目录。
- `web-hierarchy` > 记忆工作台：工具栏「刷新」SHALL 一并刷新引用计数（复用现有 `loadAll()` 路径，不新增独立刷新入口）。

## Impact

- **后端**：`lclone/memory.py`（去重函数形参 + `insights_for_evolution` 修正）、`lclone/web.py`（index 追加两字段）、`lclone/seed.py`（补向量跨层去重）。
- **前端**：`lclone/frontend/index.html`（引用条 + 弹窗层级），无新依赖。
- **测试**：`tests/test_offline.py` 补跨层去重与反向引用两个离线用例（dummy 后端可跑）。
- **数据**：本次清理重复卡会真删 `memories` 行（`review_log` 留痕，符合既有删除纪律：只删经确认的）。
- **不影响**：`gate.py` 任何常量、`/api/evolutions` 形状、`organize` 的跨区域硬约束、CLI 参数面。
