## MODIFIED Requirements

### Requirement: 归属判定

自动捕获的项目归属 SHALL 优先按 **git remote** 检测：客户端取仓库 `origin` 的远端地址并归一化为 `host/group/repo`（去协议与凭据、去尾 `.git`、去尾 `/`、host 小写、path 保留大小写），服务端 SHALL 按归一化 remote **精确匹配**已注册项目；无 remote（含 `remote` 列为空的历史项目）时 SHALL 回落按仓库根路径匹配（resolved 相等，或客户端上报路径的最长前缀）。git 检测到仓库但未注册时 SHALL 自动注册项目（`name`=仓库 basename、`path`=本次看到的仓库根、`remote`=归一化值，撞名沿用后缀去重）；无 git 时 SHALL 问用户新建 project 或升到全局层，而非静默默认全局。**当后端部署在与会话不同的机器上（记忆在服务器）时，git 检测 SHALL 由客户端（会话所在机器）执行并把解析出的 `remote` 与 `project_id` 随请求一并上报**——服务端看不到客户端路径，不得据此静默降级为全局层。客户端上报 `(remote, path)` 命中一个 `remote` 为空的既有项目时，SHALL 惰性回填该项目的 `remote`，SHALL NOT 因此新建项目。

#### Scenario: git 优先

WHEN 会话所在 git 仓库匹配到已注册项目
THEN 记忆归该项目

#### Scenario: git 自动注册

WHEN git 检测到仓库但未匹配到已注册项目
THEN 自动注册项目（name=仓库 basename、path=仓库根、remote=归一化远端地址、charter 留空）并把记忆归该项目

#### Scenario: 无 git 问用户

WHEN git 检测不到仓库
THEN 主动问用户新建 project（取名）还是升到全局层，不静默落全局

#### Scenario: 客户端解析归属（远程后端）

WHEN 后端部署在与会话不同的机器上（服务端看不到会话 cwd）
THEN 客户端按本地 git 仓库解析归属并把 `remote` 与 `project_id` 随 capture 上报：命中已注册项目则归该项目，未注册则先自动注册再归该项目；不得因服务端 no_git 而把记忆静默落进全局层

#### Scenario: MCP 显式归属（远程后端）

WHEN agent 经 MCP（HTTP）调用 capture/remember 且后端为远程
THEN 显式传 `project`，或传 `repo_remote` 使服务端按 remote 匹配；使归属不依赖服务端的 cwd 判定

#### Scenario: remote 优先于 path

WHEN 客户端上报的归一化 remote 与某已注册项目一致，而该项目的 path 与本次仓库根不同（换机器 / 换 clone 目录）
THEN 记忆归该既有项目，且不新建项目

#### Scenario: 无 remote 回落 path

WHEN 仓库没有任何 remote，而其仓库根匹配到已注册项目的 path
THEN 记忆归该项目

#### Scenario: remote 惰性回填

WHEN 客户端上报 `(remote, path)` 命中一个 `remote` 为空的既有项目
THEN 就地写入该 remote，项目 id 与既有记忆归属不变

#### Scenario: 同一 remote 跨机器收敛

WHEN 同一 remote 的仓库在两台机器上以不同本地路径被检测
THEN 两次都解析到同一个项目，不产生第二个项目

### Requirement: 按环境加载记忆

bootstrap SHALL 根据会话环境决定加载范围，且**每会话只注入一次**：会话归属落进**已知项目** → 注入【项目方向】(charter) +【项目记忆】(该项目近 project_limit 条洞察) +【全局记忆】；否则（无归属 / 不在已知项目 / 全局会话）→ 只注入【全局记忆】。会话归属 SHALL 由会话所在机器解析后随请求上报（`project_id`，或可归一化的 `repo_remote`）；服务端 SHALL NOT 依赖在服务器上对客户端路径执行 git 检测来决定是否加载项目记忆。`cwd` 参数 SHALL 仅作为未提供 `project_id`/`repo_remote` 时的向后兼容回落。DSH 宿主由插件在会话首轮注入一次，不因后续轮次重复注入。

#### Scenario: 会话首轮注入一次

WHEN 会话首轮注入记忆
THEN DSH 插件运行 bootstrap 注入一次，同一会话不再重复注入

#### Scenario: 项目会话加载

WHEN 会话归属落进已知项目
THEN bootstrap 注入 项目方向 + 项目记忆 + 全局记忆

#### Scenario: 全局会话加载

WHEN 会话不在已知项目（或无归属）
THEN bootstrap 只注入全局记忆

#### Scenario: 客户端解析归属（远程后端）

WHEN 后端在服务器上且会话 cwd 在某个已注册项目的 git 仓库内
THEN 插件在客户端解析出 `project_id` 并随 bootstrap 上报，服务端据此注入 项目方向 + 项目记忆 + 全局记忆

#### Scenario: 服务端无 git 不降级

WHEN 服务端无法对客户端路径执行 git 检测
THEN 仍按上报的 `project_id` / `repo_remote` 加载项目记忆，不静默只注入全局层

## ADDED Requirements

### Requirement: 项目身份与重复探测

项目身份 SHALL 由归一化 git remote 表达；本地路径 SHALL 只作为「最近一次看到的位置」提示（单列，后写覆盖），SHALL NOT 作为身份键。系统 SHALL 提供**只读**的重复项目探测：按归一化 remote 分组，列出同一 remote 下的多个项目及其记忆数；探测 SHALL NOT 自动改动任何数据。合并 SHALL 由显式动作触发，且 SHALL 在一个事务内完成：把源项目的 `memories.project_id` 与 `specs_index.project_id` 改挂目标项目、给源项目登记墓碑（复用 `project_removals`，不物理删除），并在合并前产出可回滚备份；`specs_index` 的 `UNIQUE(project_id, rel_path)` 冲突 SHALL 保留目标项目既有行、丢弃源重复行并计入报告。

#### Scenario: 重复可探测

WHEN 库中存在归一化 remote 相同的两个项目
THEN 探测报告把它们列为一组（含各自 id/name/path/mem_count），且不修改任何数据

#### Scenario: 显式合并

WHEN 用户显式要求把源项目合并到目标项目
THEN 源项目的记忆与 spec 索引改挂目标项目、源项目登记墓碑，且合并前已产出可回滚备份

#### Scenario: path 不作身份

WHEN 同一 remote 的仓库在两个不同本地路径被检测
THEN 不产生第二个项目（path 只更新为最近一次看到的位置）

#### Scenario: 合并可回滚

WHEN 用户用合并产出的备份执行回滚
THEN 记忆与 spec 索引的 project_id 恢复为合并前的值，源项目墓碑被撤销
