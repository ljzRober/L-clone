# memory-capture Specification

## MODIFIED Requirements

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

## ADDED Requirements

### Requirement: 删除项目与模块

lclone SHALL 支持删除项目与模块：删除项目为墓碑式（登记 project_removals，不删行/记忆，可撤销，记忆读取时跳过）；删除模块连带删除该模块下所有决策记忆（note 无模块不受影响）。

#### Scenario: 删除项目

WHEN 用户删除项目
THEN 项目登记到 project_removals（墓碑式），从列表消失、记忆停止加载，数据保留可撤销

#### Scenario: 删除模块连带记忆

WHEN 用户删除项目下的模块
THEN 模块行删除，且该模块下的所有决策(decision)记忆一并删除（不可恢复）

#### Scenario: 删除模块不影响 note

WHEN 删除模块
THEN 项目层的记录(note) 不受影响（note 无模块，不参与删除）
