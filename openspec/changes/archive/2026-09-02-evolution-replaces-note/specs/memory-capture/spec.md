## MODIFIED Requirements

### Requirement: 记忆分类与确认

lclone 的自动捕获 SHALL 把内容提炼为**洞察(insight)**，不再分级为记录(note)。**insight SHALL 是原子化、自包含、内容丰富的知识/见解/教训**——每条是一件事（一个决定 / 一条经验 / 一个观察 / 一条复盘），自带精简背景/推理/后果（约 2-4 句），不是逐字记录（那是 git / spec），也不是一行干巴巴结论。LLM 提炼前 SHALL 自筛，落库前 SHALL 过 `_filter_item`（排除「做了什么」、过短琐碎丢弃）。insight 进 pending 待人工确认。

#### Scenario: 捕获记录

WHEN 分类器提炼出原子化的知识/见解/教训（决定/经验/观察/复盘）
THEN 写入 insight 且 status=pending，待用户确认

#### Scenario: 捕获决策

WHEN 分类器提炼出可跨会话复用的决策/规则/经验
THEN 写入 insight 且 status=pending，待用户确认

#### Scenario: 自筛低价值

WHEN LLM 判断内容无长期价值（过程性琐碎/一次性/显而易见/临时性）
THEN 不提炼，不打扰用户

#### Scenario: 排除做了什么

WHEN 内容命中「做了什么」标记（修复/重构/commit/fix/bug/迁移/回滚 等）
THEN 不记忆，归 git 或 spec

#### Scenario: 决策信号降级

WHEN 内容被判为 insight 但过短/空壳（< 4 字）
THEN 丢弃，不进待确认（note 降级通道已废弃）

#### Scenario: 琐碎丢弃

WHEN 内容过短（< 4 字）或空壳
THEN 不记忆

#### Scenario: 原子且丰富

WHEN 内容提炼为 insight
THEN 每条是一件事、自带背景与后果（约 2-4 句），不逐字转录对话/代码，也不压成一行

### Requirement: 记忆整理合并

lclone SHALL 提供整理(organize)能力：LLM 把「语义相近、说的是同一件事」的洞察合并成一条综合描述。合并 SHALL 不能跨区域——只能合并 同项目 + 同等级(insight) 的洞察；跨项目/跨等级的合并由代码强制校验拒绝。

#### Scenario: 语义合并

WHEN 用户触发整理
THEN LLM 找出语义相近的洞察并合成一条综合描述，覆盖各条要点不遗漏

#### Scenario: 不跨区域

WHEN LLM 返回的合并组跨项目或跨等级
THEN 代码校验拒绝该组合并，不执行

## ADDED Requirements

### Requirement: 进化资产与链接

lclone SHALL 提供进化资产(evolution)——可复用脚本/工具，实践某个具体事物时沉淀、会话中反复修改、不再修改即稳定。存储 SHALL 分两种：项目无关的通用脚本/工具内容存记忆库本体(`content`)；项目内脚本只存路径引用(`ref`，内容留仓库、git 版本化)。每个 evolution SHALL 可被 1..N 个 insight 支撑（`insight→evolution` 链接）；脚本被改时 SHALL 用 `update_evolution` 同步最新版本。检索命中 insight 时 SHALL 顺 `insight→evolution` 边带出该资产。

#### Scenario: 沉淀 evolution

WHEN 实践中生成一个可复用脚本/工具（项目无关 或 项目内）
THEN 写入 evolutions（项目无关存 content；项目内存 ref），status=active

#### Scenario: insight 支撑 evolution

WHEN 一个 evolution 有 1..N 个 insight 阐明"为什么/教训"
THEN 建立 insight→evolution 链接，可被检索顺边带出

#### Scenario: 同步最新版本

WHEN 脚本后续被改（继续使用/迭代）
THEN update_evolution 同步 content/ref 到最新版本，status 可置 stable

## REMOVED Requirements

### Requirement: 记录按会话聚合
**Reason**: note 通道已废弃，交由 evolution 承接；不再按会话逐轮追加原始文本。
**Migration**: 既有 note 旧数据保留（不再新建/呈现），后续可迁移为 insight 或 evolution。

### Requirement: note 滚动压缩
**Reason**: note 通道已废弃，滚动压缩随之移除。
**Migration**: 既有 note 内容保留原样；不再触发压缩。
