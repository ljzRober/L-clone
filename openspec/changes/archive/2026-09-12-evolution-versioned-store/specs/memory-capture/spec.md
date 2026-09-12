## MODIFIED Requirements

### Requirement: 进化资产与链接

lclone SHALL 提供进化资产(evolution)——可复用脚本/工具/模板，实践某个具体事物时沉淀、会话中反复修改、不再修改即稳定。**权威 SHALL 唯一：内容存储在服务器侧的版本化内容寻址库**（`evo_versions` 只追加 + `evo_current` 当前指针 + 以 `sha256` 命名的 blob），本地目录只是**可复现的缓存**；SHOULD NOT 出现"本机是唯一副本"的进化资产。存储 SHALL 分两种：项目无关的通用脚本/工具内容入内容库（`evo_versions.hash` 指向 blob）；项目内脚本只记路径引用（`ref`，内容留仓库、git 版本化，不入内容库）。每个 evolution SHALL 可被 1..N 个 insight 支撑（`insight→evolution` 链接）；脚本被改时 SHALL 用 `update_evolution` 发布**新版本**（append-only，旧版本保留可回滚），SHALL NOT 原地覆盖历史。检索命中 insight 时 SHALL 顺 `insight→evolution` 边带出该资产。

#### Scenario: 沉淀 evolution

WHEN 实践中生成一个可复用脚本/工具（项目无关 或 项目内）
THEN 发布一版：项目无关内容入内容寻址库并指向 blob；项目内只记 `ref` 引用

#### Scenario: insight 支撑 evolution

WHEN 一个 evolution 有 1..N 个 insight 阐明"为什么/教训"
THEN 建立 insight→evolution 链接，可被检索顺边带出

#### Scenario: 同步最新版本

WHEN 脚本后续被改（继续使用/迭代）
THEN update_evolution 发布新版本（版本号按历史最大版本递增，历史版本保留）

#### Scenario: 项目内脚本只存引用

WHEN evolution 以 `ref` 形式登记（内容在项目仓库）
THEN 索引只记引用，内容库不存 blob，本地同步清单不含该条目，读取时返回指向仓库路径的说明
