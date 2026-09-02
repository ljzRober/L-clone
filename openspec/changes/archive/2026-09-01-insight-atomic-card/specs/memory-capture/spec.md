## MODIFIED Requirements

### Requirement: 记忆分类与确认

lclone 的自动捕获 SHALL 把内容分类为记录(note)与洞察(insight)：note 免确认直接 active；insight 进 pending 待人工确认。**insight SHALL 是原子化、自包含、内容丰富的知识/见解/教训**——每条是一件事（一个决定 / 一条经验 / 一个观察 / 一条复盘），自带精简背景/推理/后果（约 2-4 句），不是逐字记录（那是 note / git / spec），也不是一行干巴巴结论。LLM 提炼前 SHALL 自筛，落库前 SHALL 过 `_filter_item`（排除「做了什么」、给缺乏洞察信号的 insight 降级为 note、丢弃琐碎 note）。

#### Scenario: 捕获记录

WHEN 分类器提炼出过程性事实/观察
THEN 写入 note 且 status=active，无需确认

#### Scenario: 捕获决策

WHEN 分类器提炼出原子化的知识/见解/教训（决定/经验/观察/复盘）
THEN 写入 insight 且 status=pending，待用户确认

#### Scenario: 自筛低价值

WHEN LLM 判断内容无长期价值（过程性琐碎/一次性/显而易见/临时性）
THEN 不提炼，不打扰用户

#### Scenario: 排除做了什么

WHEN 内容命中「做了什么」标记（修复/重构/commit/fix/bug/迁移/回滚 等）
THEN 不记忆，归 git 或 spec

#### Scenario: 决策信号降级

WHEN 内容被判为 insight 但不含洞察信号（决定/采用/方案/边界/规则/约定/经验/教训/因为/所以 等）
THEN 降级为 note，不进待确认

#### Scenario: 琐碎丢弃

WHEN note 内容过短（< 4 字）
THEN 不记忆

#### Scenario: 原子且丰富

WHEN 内容提炼为 insight
THEN 每条是一件事、自带背景与后果（约 2-4 句），不逐字转录对话/代码，也不压成一行

### Requirement: 分工边界

代码改动/接口变化/新增端点/重构/修 bug SHALL 归 git；需求/场景/⚠️边界变化 SHALL 归 sp-spec（openspec）；lclone 记忆 SHALL 只留**洞察(insight)**（原子化的知识/见解/教训）与**记录(note)**（过程事实）。边界判定遵循试金石：**内容能否改写成一条带 WHEN/THEN 的 requirement**。能 → 归 spec；不能（是理由/权衡/过程事实/偏好/经验教训）→ 归记忆。**归属纪律**：若 insight 明确对应仓库内某具体 spec/文件，项目级记忆可标 `[[spec:id]]`/`[[src:path]]`（link, not copy，权威内容留在仓库）；全局级记忆无仓库上下文，不标此类链接（只有 `[[m:N]]`）。

#### Scenario: 分类器排除代码改动

WHEN 分类器遇到"做了什么改动"
THEN 不提炼成 insight 或 note

#### Scenario: 只留选择与约定

WHEN 分类器遇到"选了什么方案/定了什么规则/学到的经验教训"
THEN 提炼为 insight

#### Scenario: 契约归 spec

WHEN 内容是"系统必须满足的契约"（可改写为带 WHEN/THEN 的 requirement）
THEN 不进 lclone 记忆，归 sp-spec（openspec）

#### Scenario: 理由归记忆

WHEN 内容是"为什么这么选/观察到什么"（无法写成 WHEN/THEN requirement）
THEN 写入项目记忆

#### Scenario: 半契约半理由拆分

WHEN 一条内容既含理由又含契约
THEN 理由归记忆、契约归 spec，不整体塞进单一桶

#### Scenario: 记忆升格为 spec

WHEN 一条记忆进一步被锁定为"系统必须满足 X"且能写成 WHEN/THEN requirement
THEN 在 spec 建/改该 requirement；原记忆写入 `[[spec:id]]` 引用或删除，避免与 spec 双份漂移

### Requirement: 记忆整理合并

lclone SHALL 提供整理(organize)能力：LLM 把「语义相近、说的是同一件事」的记忆合并成一条综合描述。合并 SHALL 不能跨区域——只能合并 同项目 + 同等级(insight/note) 的记忆；跨项目/跨等级的合并由代码强制校验拒绝。

#### Scenario: 语义合并

WHEN 用户触发整理
THEN LLM 找出语义相近的记忆并合成一条综合描述，覆盖各条要点不遗漏

#### Scenario: 不跨区域

WHEN LLM 返回的合并组跨项目或跨等级
THEN 代码校验拒绝该组合并，不执行

## ADDED Requirements

### Requirement: 洞察强确认

后台捕获产生 pending 洞察后，**呈现由宿主按端分派**：capture 输入 SHALL 含用户与助手文本（判断纳入「助手是否确认/落地」），分类器 SHALL 仅把被助手确认、落地或持续推进的用户选择/规则/经验提炼为 insight；DSH 宿主 SHALL 不用 agent.steer 劫持主 agent，改由客户端轮询宿主 `/api/lclone-decisions` 以 UI 弹窗/角标提示，用户经 `/api/lclone-review` 保留/删除（主 agent 全程不参与确认）；非 web 端 SHALL 由 bootstrap 每轮带出【待确认洞察】。

#### Scenario: bootstrap 带出待确认

WHEN 存在 pending 洞察
THEN bootstrap 输出包含【待确认洞察】段

#### Scenario: 会话中逐轮检查

WHEN turn/end 时探测到本轮产生了待确认洞察
THEN 判断基于该轮「用户 + 助手」交换；DSH 由客户端轮询呈现，非 web 端由 bootstrap 带出，均不再用 agent.steer 劫持主 agent

#### Scenario: 弹窗确认

WHEN DSH 客户端轮询到新增 pending 洞察
THEN 以 UI 弹窗（洞察内容 + 保留/删除/稍后按钮）+ 侧边栏角标提示用户，用户点击保留/删除经 `/api/lclone-review` 落地；主 agent 不参与确认

#### Scenario: 去重防循环

WHEN 客户端已提醒过某批 pending 洞察（其 id 已入 seen 集合）
THEN 该批不再重复弹窗；仅未见过的新 id 触发渲染，避免刷屏

#### Scenario: 判断纳入助手实现

WHEN turn/end 提交「用户 + 助手」整段交换
THEN 分类器判断用户提出的选择/规则是否被助手确认、落地或持续推进，仅提炼为 insight；未获回应/未落地的一律不提炼

## REMOVED Requirements

### Requirement: 决策强确认
**Reason**: 类型由"决策(decision)"更名为"洞察(insight)"，确认收口为"洞察强确认"。
**Migration**: 既有 `decision` 记忆在数据库迁移中改写为 `insight`；确认流程语义不变。
