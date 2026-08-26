## MODIFIED Requirements

### Requirement: 归属判定

自动捕获的项目归属 SHALL 优先按 git 检测；git 检测到仓库但未注册时 SHALL 自动注册项目；无 git 时 SHALL 问用户新建 project 或升到全局层，而非静默默认全局。

#### Scenario: git 优先

WHEN 会话所在 git 仓库匹配到已注册项目
THEN 记忆归该项目

#### Scenario: git 自动注册

WHEN git 检测到仓库但未匹配到已注册项目
THEN 自动注册项目（name=仓库 basename、path=仓库根、charter 留空）并把记忆归该项目

#### Scenario: 无 git 问用户

WHEN git 检测不到仓库
THEN 主动问用户新建 project（取名）还是升到全局层，不静默落全局

### Requirement: 模块归属

capture SHALL 由代码按 embedding 相似度增量聚类把记忆归到模块，LLM 不自由起模块名；新模块名由一次性 LLM 标签生成并缓存；泛名模块 SHALL 挂项目层不建模块。

#### Scenario: 自动派生模块

WHEN capture 提炼出记忆
THEN 代码用 embedding 余弦相似度归到最近模块（≥0.8）或新建模块，capture 自动把新模块补进 modules 表

#### Scenario: 不硬编码模块

WHEN 项目模块发生变化
THEN 模块由代码增量聚类动态派生，不预先硬编码空模块

#### Scenario: 一次性命名

WHEN 代码新建模块
THEN 模块名由一次性 LLM 标签生成并缓存进 modules 表，此后相同关注点复用同一名

#### Scenario: 泛名挂项目层

WHEN 新建模块名命中泛名（core/misc/general/other/todo）
THEN 不建模块，记忆挂项目层
