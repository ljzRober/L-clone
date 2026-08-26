## MODIFIED Requirements

### Requirement: 记忆分类与确认

lclone 的自动捕获 SHALL 把内容分类为记录(note)与决策(decision)：note 免确认直接 active，decision 进 pending 待人工确认。落库前 SHALL 过代码准入条件 `_filter_item`，排除「做了什么」、给决策降级、丢弃琐碎 note。

#### Scenario: 捕获记录

WHEN 分类器提炼出过程性事实/观察
THEN 写入 note 且 status=active，无需确认

#### Scenario: 捕获决策

WHEN 分类器提炼出选型/约定/边界
THEN 写入 decision 且 status=pending，待用户确认

#### Scenario: 排除做了什么

WHEN 内容命中「做了什么」标记（修复/重构/commit/fix/bug/迁移/回滚 等）
THEN 不记忆，归 git 或 spec

#### Scenario: 决策信号降级

WHEN 内容被判为 decision 但不含决策信号（决定/采用/方案/边界/规则/约定 等）
THEN 降级为 note，不进待确认

#### Scenario: 琐碎丢弃

WHEN note 内容过短（< 4 字）
THEN 不记忆

### Requirement: 模块归属

capture SHALL 由 LLM 把每条**决策(decision)**分类到项目已有模块或粗粒度新关注点；代码 SHALL 强制词表（归一化、复用已有名、防泛名）；泛名模块 SHALL 挂项目层不建模块。**记录(note) SHALL 不挂模块**，落在项目层（偶尔全局层）。

#### Scenario: 自动派生模块

WHEN capture 提炼出决策
THEN LLM 给每条决策一个模块名（优先复用项目已有模块），代码归一化后补录 modules 表

#### Scenario: 不硬编码模块

WHEN 项目模块发生变化
THEN 模块由 LLM 分类动态派生并复用已有名，不预先硬编码空模块

#### Scenario: 一次性命名

WHEN 项目出现新的关注点
THEN LLM 给出一个粗粒度新模块名，代码归一化后入表，此后相同关注点复用该名

#### Scenario: 泛名挂项目层

WHEN 模块名命中泛名（core/misc/general/other/todo 等）
THEN 不建模块，决策挂项目层

#### Scenario: 记录无模块

WHEN capture 提炼出记录(note)
THEN note 不挂模块（module 为空），落在项目层（偶尔全局层）
