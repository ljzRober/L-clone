# cli-onboarding Specification

## Purpose
TBD - created by archiving change install-doctor-onboarding. Update Purpose after archive.
## Requirements
### Requirement: 一键接入

lclone SHALL 提供 `install` 命令，一条命令完成 provider 配置、`.env` 写入、数据库初始化、项目注册、skill 安装与触发配置。

#### Scenario: 非交互安装

WHEN 运行 `lclone install --provider dummy --yes`
THEN 生成 `.env`、初始化数据库、注册当前 git 项目、安装 skill 到 `LCLONE_HOME`，并输出自检结果

#### Scenario: 未知 provider

WHEN 传入未知的 `--provider`
THEN 报错并列出可选 provider

#### Scenario: 项目注册默认值

WHEN 未显式传 `--project` / `--charter`
THEN 项目名取 git 仓库名、charter 从 README 首段猜测

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

