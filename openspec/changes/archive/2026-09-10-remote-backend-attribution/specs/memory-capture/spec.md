## MODIFIED Requirements

### Requirement: 归属判定

自动捕获的项目归属 SHALL 优先按 git 检测；git 检测到仓库但未注册时 SHALL 自动注册项目；无 git 时 SHALL 问用户新建 project 或升到全局层，而非静默默认全局。**当后端部署在与会话不同的机器上（记忆在服务器）时，git 检测 SHALL 由客户端（会话所在机器）执行并把解析出的项目归属随捕获请求一并上报**——服务端看不到客户端路径，不得据此静默降级为全局层。

#### Scenario: git 优先

WHEN 会话所在 git 仓库匹配到已注册项目
THEN 记忆归该项目

#### Scenario: git 自动注册

WHEN git 检测到仓库但未匹配到已注册项目
THEN 自动注册项目（name=仓库 basename、path=仓库根、charter 留空）并把记忆归该项目

#### Scenario: 无 git 问用户

WHEN git 检测不到仓库
THEN 主动问用户新建 project（取名）还是升到全局层，不静默落全局

#### Scenario: 客户端解析归属（远程后端）

WHEN 后端部署在与会话不同的机器上（服务端看不到会话 cwd）
THEN 客户端按本地 git 仓库解析归属并把 `project_id` 随 capture 上报：命中已注册项目则归该项目，未注册则先自动注册再归该项目；不得因服务端 no_git 而把记忆静默落进全局层

#### Scenario: MCP 显式归属（远程后端）

WHEN agent 经 MCP（HTTP）调用 capture/remember 且后端为远程
THEN 显式传 `project`（按 `projects` 的 path 匹配当前工作目录），使归属不依赖服务端的 cwd 判定
