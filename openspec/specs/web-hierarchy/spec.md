# web-hierarchy Specification

## Purpose
TBD - created by archiving change ui-hierarchy. Update Purpose after archive.
## Requirements
### Requirement: 记忆工作台

Web 面板主页面 SHALL 是记忆工作台：左侧层级树 + 右侧卡片流，用户通过 UI 查看、移动、添加记忆。

#### Scenario: 默认展示全局层卡片

WHEN 打开主页
THEN 左侧出现层级树（全局层带 ∞ 徽章、各项目含记忆数），右侧卡片流默认显示全局层记忆

#### Scenario: 点击层级筛选

WHEN 点击层级树的全局层或某项目
THEN 卡片流只显示该层级的记忆，标题与生命周期提示随之更新

#### Scenario: 拖拽卡片移动记忆

WHEN 把记忆卡片拖到层级树的目标节点
THEN 记忆移动到该层级（拖到全局层 = 上升，拖到项目 = 下降），卡片流与层级计数刷新

#### Scenario: 卡片上升按钮

WHEN 项目记忆卡片点击「↑ 到全局」
THEN 记忆上升为全局层并刷新

#### Scenario: 添加记忆

WHEN 点击「＋ 添加记忆」并在弹窗填写内容、选择等级与归属层级后确认
THEN 记忆写入并刷新卡片流与层级计数

#### Scenario: 无 spec 区分

WHEN 浏览任意页面
THEN 界面不出现「记忆/spec」区分或 spec 计数；所有记忆即 spec

### Requirement: 问答独立页面

问答 SHALL 位于独立页面 /ask，与记忆工作台完全分开。

#### Scenario: 独立访问

WHEN 在工作台点击「问答 →」或在浏览器访问 /ask
THEN 打开独立的问答页（带记忆聊天 + 边界监督），与记忆管理界面互不混合

#### Scenario: 页面互链

WHEN 在问答页点击「← 记忆工作台」
THEN 返回记忆工作台主页

