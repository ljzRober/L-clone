# memory-capture Specification

## Purpose
TBD - created by archiving change memory-capture-model. Update Purpose after archive.
## Requirements
### Requirement: 记忆分类与确认

lclone 的自动捕获 SHALL 把内容分类为记录(note)与决策(decision)：note 免确认直接 active，decision 进 pending 待人工确认。

#### Scenario: 捕获记录

WHEN 分类器提炼出过程性事实/观察
THEN 写入 note 且 status=active，无需确认

#### Scenario: 捕获决策

WHEN 分类器提炼出选型/约定/边界
THEN 写入 decision 且 status=pending，待用户确认

### Requirement: 决策强确认

每轮会话开始 bootstrap SHALL 带出【待确认决策】；存在待确认决策时，SHALL 主动用弹窗请用户逐条保留/删除，而非静默跳过。

#### Scenario: bootstrap 带出待确认

WHEN 存在 pending 决策
THEN bootstrap 输出包含【待确认决策】段

#### Scenario: 弹窗确认

WHEN 存在待确认决策
THEN 用工具弹窗（ask_user_question 等）请用户保留/删除，不用纯文本列表

### Requirement: 分工边界

代码改动/接口变化/新增端点/重构/修 bug SHALL 归 git；需求/场景/⚠️边界变化 SHALL 归 sp-spec（openspec）；lclone 记忆 SHALL 只留决策（选型/约定）与记录（过程事实）。

#### Scenario: 分类器排除代码改动

WHEN 分类器遇到"做了什么改动"
THEN 不提炼成 decision 或 note

#### Scenario: 只留选择与约定

WHEN 分类器遇到"选了什么方案/定了什么规则"
THEN 提炼为 decision

### Requirement: 记录按会话聚合

同一外部会话（session_key 相同）SHALL 只建一条 note，逐轮往这条 note 追加内容；新会话（新 session_key）SHALL 新建一条 note。

#### Scenario: 同会话追加

WHEN 相同 session_key 连续捕获 note
THEN 追加到同一条 note，不新建

#### Scenario: 新会话新 note

WHEN 新 session_key 捕获 note
THEN 新建一条 note

### Requirement: note 滚动压缩

note 追加后长度超过阈值（3000 字）时，SHALL 把整条 note 摘要压缩一次，保持有界。

#### Scenario: 超长触发压缩

WHEN note 长度超过阈值
THEN 整条 note 被摘要成有界摘要

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

