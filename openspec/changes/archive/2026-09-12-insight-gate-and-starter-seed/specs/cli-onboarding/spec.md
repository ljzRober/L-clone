## MODIFIED Requirements

### Requirement: 一键接入

lclone SHALL 提供 `install` 命令，一条命令完成 provider 配置、`.env` 写入、数据库初始化、**首次种子内容种入**、项目注册、skill 安装与触发配置。`setup`（部署后端）SHALL 在初始化数据库后种入种子内容，并 SHALL 支持 `--no-seed` 跳过；新增开关 SHALL NOT 破坏非交互（`--yes`）场景。`integrate`（接入工具前端）SHALL NOT 涉及种子内容。

#### Scenario: 非交互安装

WHEN 运行 `lclone install --provider dummy --yes`
THEN 生成 `.env`、初始化数据库、注册当前 git 项目、安装 skill 到 `LCLONE_HOME`，并输出自检结果

#### Scenario: 未知 provider

WHEN 传入未知的 `--provider`
THEN 报错并列出可选 provider

#### Scenario: 项目注册默认值

WHEN 未显式传 `--project` / `--charter`
THEN 项目名取 git 仓库名、charter 从 README 首段猜测

#### Scenario: 默认种入种子内容

WHEN 运行 `lclone setup`（未带 `--no-seed`）
THEN 初始化数据库后种入通用洞察与通用进化文件，并在输出中报告种入条数

#### Scenario: 跳过种子内容

WHEN 运行 `lclone setup --provider dummy --yes --no-seed`
THEN 照常写出 `.env`、初始化数据库并输出自检结果，但不写入任何种子洞察或进化文件

## ADDED Requirements

### Requirement: 首次种子内容

lclone SHALL 在首次部署后端时种入一份**通用**种子内容，让空库用户立刻看到「一条洞察长什么样、进化资产怎么用」：

- **通用洞察** 4 条，SHALL 落全局层（`project_id IS NULL`）、`status='active'`、`source_type='seed'`，且 **SHALL NOT 进 pending 待确认**（它是预置内容，不是捕获来的草稿）；
- **通用进化文件**（洞察格式模型 / 记忆准入标准 / 会话归属与落库约定 + 示例脚本），SHALL 写入记忆区进化目录（`~/.lclone/evolutions/`）。

种子内容 SHALL NOT 绑定具体项目，SHALL NOT 依赖具体 provider；`BRAIN_LLM=dummy` 下 SHALL 仍可种入。种子 SHALL NOT 覆盖记忆中已存在的等价内容，也 SHALL NOT 覆盖已存在的进化文件。种子内容 SHALL 与代码分离存放（`lclone/data/starter/`），以便非开发者增删条目。

#### Scenario: 首次种入

WHEN 在一个空库上运行 `lclone setup`
THEN 写入 4 条全局通用洞察与通用进化文件，并报告种入条数

#### Scenario: 全局层且直接生效

WHEN 种子洞察写入
THEN `project_id IS NULL`、`status='active'`、`source_type='seed'`，不出现在待确认列表、不弹确认框

#### Scenario: 不覆盖既有内容

WHEN 进化目录下已存在同名文件（用户改过）
THEN 种子不覆盖它，只在报告中计入跳过

#### Scenario: 离线可种

WHEN `BRAIN_LLM=dummy` 且无 API key
THEN 种子洞察仍可写入（embedding 走本地确定性哈希向量）

### Requirement: 种子重放

`lclone seed` SHALL 支持幂等重放种子内容。已种过的条目 SHALL 记入 `seed_state` 表；**用户删除后的种子条目 SHALL NOT 自动回灌**（尊重用户删除）。`--force` SHALL 覆盖已存在的进化文件并补回缺失的种子洞察；`--dry-run` SHALL 只报告将要做什么，SHALL NOT 写入任何内容。

#### Scenario: 幂等重放

WHEN 连续运行两次 `lclone seed`
THEN 第二次不新增任何洞察或进化文件，报告全部为跳过

#### Scenario: 删除后不回灌

WHEN 用户删掉某条种子洞察后再运行 `lclone seed`
THEN 该条不被重新写入

#### Scenario: force 覆盖

WHEN 运行 `lclone seed --force` 且进化文件已被用户修改
THEN 该文件被种子版本覆盖

#### Scenario: dry-run 不写入

WHEN 运行 `lclone seed --dry-run`
THEN 只打印将要种入/跳过的清单，数据库与进化目录均不变化
