## ADDED Requirements

### Requirement: 归属判定

自动捕获的项目归属 SHALL 优先按 git 检测；无 git 或匹配不到已注册项目时，SHALL 问用户新建 project 或升到全局层，而非静默默认全局。

#### Scenario: git 优先

WHEN 会话所在 git 仓库匹配到已注册项目
THEN 记忆归该项目

#### Scenario: 无 git 问用户

WHEN git 检测不到已注册项目
THEN 主动问用户新建 project（取名）还是升到全局层

### Requirement: 模块归属

分类器 SHALL 按工作主题自动派生 module（与 sp-spec 分 spec 同逻辑：按关注点拆），capture SHALL 自动补录项目 modules 表。

#### Scenario: 自动派生模块

WHEN 分类器提炼记忆
THEN 每条记忆带主题 module，capture 自动把新模块补进 modules 表

#### Scenario: 不硬编码模块

WHEN 项目模块发生变化
THEN 模块由分类器动态派生，不预先硬编码空模块
