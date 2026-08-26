## MODIFIED Requirements

### Requirement: 模块归属

capture SHALL 由 LLM 把每条记忆分类到项目已有模块或粗粒度新关注点；代码 SHALL 强制词表（归一化、复用已有名、防泛名）；泛名模块 SHALL 挂项目层不建模块。

#### Scenario: 自动派生模块

WHEN capture 提炼出记忆
THEN LLM 给每条记忆一个模块名（优先复用项目已有模块），代码归一化后补录 modules 表

#### Scenario: 不硬编码模块

WHEN 项目模块发生变化
THEN 模块由 LLM 分类动态派生并复用已有名，不预先硬编码空模块

#### Scenario: 一次性命名

WHEN 项目出现新的关注点
THEN LLM 给出一个粗粒度新模块名，代码归一化后入表，此后相同关注点复用该名

#### Scenario: 泛名挂项目层

WHEN 模块名命中泛名（core/misc/general/other/todo 等）
THEN 不建模块，记忆挂项目层
