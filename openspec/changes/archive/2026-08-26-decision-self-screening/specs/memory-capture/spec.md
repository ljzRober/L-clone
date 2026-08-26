## MODIFIED Requirements

### Requirement: 记忆分类与确认

lclone 的自动捕获 SHALL 把内容分类为记录(note)与决策(decision)：note 免确认直接 active，decision 进 pending 待人工确认。LLM 提炼前 SHALL 自筛（只提高价值内容），落库前 SHALL 过代码准入条件 `_filter_item`（排除「做了什么」、给决策降级、丢弃琐碎 note）。

#### Scenario: 捕获记录

WHEN 分类器提炼出过程性事实/观察
THEN 写入 note 且 status=active，无需确认

#### Scenario: 捕获决策

WHEN 分类器提炼出选型/约定/边界
THEN 写入 decision 且 status=pending，待用户确认

#### Scenario: 自筛低价值

WHEN LLM 判断内容无长期价值（过程性琐碎/一次性/显而易见/临时性）
THEN 不提炼，不打扰用户

#### Scenario: 排除做了什么

WHEN 内容命中「做了什么」标记（修复/重构/commit/fix/bug/迁移/回滚 等）
THEN 不记忆，归 git 或 spec

#### Scenario: 决策信号降级

WHEN 内容被判为 decision 但不含决策信号（决定/采用/方案/边界/规则/约定 等）
THEN 降级为 note，不进待确认

#### Scenario: 琐碎丢弃

WHEN note 内容过短（< 4 字）
THEN 不记忆
