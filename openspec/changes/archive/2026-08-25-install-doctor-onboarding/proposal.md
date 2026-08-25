## Why

一个新接触 lclone 的人要接入，得走 9 步（clone/venv、写 8 个 env 变量、init、proj add、配 mcporter、手动复制 skill、按环境配四套触发、无自检），其中多个步骤是隐藏的或易踩坑：DeepSeek 无 embedding 接口必须设 `BRAIN_EMBED_BACKEND=local`；skill 要手动复制到 `~/.agents/skills/`；四套触发配置格式不统一；装完没有自检命令。

需要把接入收敛成「装包 → `lclone install` → 填 provider+key → `lclone doctor` 看全绿」。

## What Changes

- **provider 预设**：新增 `lclone/presets.py`，把 8 个 env 变量收敛成「选一个 provider + 一个 key」（deepseek/openai/siliconflow/zhipu/dummy），DeepSeek 的 embedding 坑自动处理。
- **`lclone install` 向导**：新增 `lclone/install.py`，一条命令走完 env 写入 + init DB + 注册项目（git 检测 + charter 自动猜）+ 装 skill + 按环境配触发 + 末尾自检。
- **`lclone doctor` 自检**：新增 `lclone/doctor.py`，输出 ✅/❌/⚠️ 清单（.env/provider/DB/项目/skill/四套触发/LLM 连通），附修复建议。
- **CLI 接入**：`cli.py` 加 `install`、`doctor` 子命令；`docs/CLI.md` 补文档；`tests` 补冒烟。

## Capabilities

- **New Capabilities**:
  - `cli-onboarding`：新增「一键接入」「接入自检」「provider 预设」需求
- **Modified Capabilities**: 无

## 方案

### 文件变更

- 新增 `lclone/presets.py`：`PROVIDERS` 表 + `env_for(provider, key, db_path)` + `render_env()`
- 新增 `lclone/install.py`：`home_dir()`（读 `LCLONE_HOME` 或 `~`）、`detect_git_repo()`、`guess_charter()`、`write_env()`、`install_skill()`、`configure_triggers()`、`run()`
- 新增 `lclone/doctor.py`：`check_all()` 返回 `[{name, ok, detail, hint}]`
- 改 `lclone/cli.py`：`install`（`--provider/--api-key/--project/--charter/--target/--yes`）、`doctor`（`--check-llm`）
- 改 `docs/CLI.md`、`tests/test_offline.py`

### 关键设计

- **家目录可测**：skill/配置路径走 `LCLONE_HOME`，默认 `Path.home()`；测试用临时目录，不污染真实 `~/.agents`、`~/.claude`、`~/.codex`。
- **不自动动 DSH 运行时**：DSH 触发只打印 `dsh plugin add` 命令，让用户手动执行（避免改动当前会话运行时）。
- **claude/codex 配置合并只追加 + 备份**：绝不覆盖已有 hooks。
- **幂等**：skill 已存在则跳过；`--yes` 非交互。

## Spec Constraints

- 无 spec 变更：本次只新增 CLI 命令面，不改 `web-hierarchy` 的 Web 行为，等价确认。

## Impact

- 文件：新增 `presets.py`/`install.py`/`doctor.py`，改 `cli.py`/`CLI.md`/`test_offline.py`
- 依赖：无新增
- 测试：`tests/test_offline.py` 全绿 + 补 presets/doctor 冒烟
