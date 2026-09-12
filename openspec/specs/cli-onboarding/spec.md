# cli-onboarding Specification

## Purpose
TBD - created by archiving change install-doctor-onboarding. Update Purpose after archive.
## Requirements
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

### Requirement: 接入自检

lclone SHALL 提供 `doctor` 命令，输出 `.env` / provider / 数据库 / 项目 / skill / 触发 / LLM 的 ✅/❌ 清单。

#### Scenario: 自检输出

WHEN 运行 `lclone doctor`
THEN 逐项输出 ✅/❌ 与修复建议，并给出通过数汇总

#### Scenario: LLM 连通检查

WHEN 运行 `lclone doctor --check-llm`
THEN 额外真调 LLM 验证连通性

### Requirement: provider 预设

lclone SHALL 内置 provider 预设（deepseek/openai/siliconflow/zhipu/dummy），把多个 env 变量收敛为「选一个 provider + 一个 key」。

#### Scenario: DeepSeek embedding

WHEN 选择 deepseek 预设
THEN `BRAIN_EMBED_BACKEND=local`（DeepSeek 无 embedding 接口，用本地哈希向量）

#### Scenario: 预设反推

WHEN 根据现有 `BRAIN_BASE_URL` 与 `BRAIN_LLM` 反推 provider
THEN 匹配到对应预设名；匹配不到返回空

### Requirement: 首次种子内容

lclone SHALL 在首次部署后端时种入一份**通用**种子内容，让空库用户立刻看到「一条洞察长什么样、进化资产怎么用」：

- **通用洞察** 4 条，SHALL 落全局层（`project_id IS NULL`）、`status='active'`、`source_type='seed'`，且 **SHALL NOT 进 pending 待确认**（它是预置内容，不是捕获来的草稿）；
- **通用进化文件**（洞察格式模型 / 记忆准入标准 / 会话归属与落库约定 + 示例脚本），SHALL 走**版本化发布**写入进化资产库（详见 `evolution-store`），并物化到记忆区进化缓存目录（默认 `~/.lclone/evolution/`，可用 `LCLONE_EVO_DIR` 覆盖——该目录只是可复现缓存，容器化部署无需持久化）。种子 SHALL NOT 绕开版本库直接写文件。

种子内容 SHALL NOT 绑定具体项目，SHALL NOT 依赖具体 provider；`BRAIN_LLM=dummy` 下 SHALL 仍可种入。种子 SHALL NOT 覆盖记忆中已存在的等价内容，也 SHALL NOT 覆盖已存在的进化资产（含已在版本库中的名字、以及缓存目录里的同名文件）。种子内容 SHALL 与代码分离存放（`lclone/data/starter/`），以便非开发者增删条目。部署时若进化缓存目录已有存量文件，lclone SHALL 提供把它们摄入为 v1 的迁移能力（详见 `evolution-store`）。

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

#### Scenario: 种子进化文件进版本库

WHEN 种子种入通用进化文件
THEN 它们以 v1 进入进化资产库（可被 `history` 查到、可被客户端 `pull` 到），而不是只存在于某台机器的目录里

#### Scenario: 升级时摄入存量资产

WHEN 进化缓存目录里已有版本库中不存在的文件（旧版本升级上来的情况）
THEN 迁移能力把它们摄入为 v1（并按扩展名记好类型），且重复执行幂等

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

