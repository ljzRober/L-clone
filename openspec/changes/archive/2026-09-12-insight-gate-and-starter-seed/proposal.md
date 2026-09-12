## Why

DSH 插件每轮 `turn/end` 都把整段 user+assistant 原文 POST 到 `/api/capture`，`capture` 无条件调 LLM 提炼，落库前只有 `DID_MARKERS` 和 `len < 4` 两条确定性规则——「值不值得记」实际由模型自由裁量，导致待确认洞察过多、每轮弹窗、每轮一次 LLM 调用。同时新用户首次下载后记忆区为空，看不到「一条洞察长什么样、进化资产怎么用」，冷启动体验为零。

## What Changes

- 新增确定性准入闸门 `lclone/gate.py`（纯标准库、不依赖 LLM）：把一次 capture 的文本判为 `skip` / `candidate` / `uncertain`。
  - `skip` → 直接返回，**0 次 LLM 调用**（预期覆盖绝大多数轮次）
  - `candidate`（命中决策/约定/规则/教训强信号）→ 交 LLM 成卡，跳过判定
  - `uncertain`（无强信号但非噪声）→ 先一次极便宜的 yes/no 判定，yes 才成卡
  - 用户显式「记住/记一下/记下来」旁路为 `candidate`
  - 判定只在**用户轮**上做（按 `用户：`/`助手：` 切分），消掉助手输出这一最大噪声源
- 闸门标准以常量块集中在 `gate.py`（SSOT）；新增 `lclone gate "<文本>"` 可解释自测命令，打印 verdict / 命中规则
- capture 增加确定性护栏：单轮成卡上限 2 条；文本级近重复判重（去标点空白后前 80 字）
- 新增首次种子包 `lclone/seed.py` + `lclone/data/starter/`：通用洞察 4 条（全局层、`active`、**不弹窗**、`source_type='seed'`）+ 进化文件（洞察格式模型 / 记忆准入标准 / 会话归属与落库约定 + 2 个示例脚本）
- `db.py` 新增 `seed_state` 表实现幂等：种过即记，用户删掉后不回灌
- `lclone setup` 末尾自动种入（`--no-seed` 跳过）；新增 `lclone seed [--force] [--dry-run]`
- capture 返回值新增 gate 诊断字段（纯增量，MCP / web / 插件均不破坏）
- 不改动既有 pending / review / promote 语义（**非 BREAKING**）

## Capabilities

### New Capabilities

（无——种子与闸门分别归属既有的 onboarding 与 capture 能力，不新增 spec）

### Modified Capabilities

- `memory-capture`: 新增「确定性准入闸门」需求——判据从「LLM 自筛」改为「脚本分流 + LLM 兜底」，并明确单轮成卡上限与近重复判重
- `cli-onboarding`: 新增「首次种子内容」「种子重放」两条需求；「一键接入」增加 `--no-seed`

## Impact

- 代码：新增 `lclone/gate.py`、`lclone/seed.py`、`lclone/data/starter/**`；改 `lclone/memory.py`（capture）、`lclone/llm.py`（uncertain 判定 + 严格提示）、`lclone/db.py`（seed_state）、`lclone/install.py`、`lclone/cli.py`、`lclone/web.py`、`lclone/mcp_server.py`（返回值）、`integrations/dsh/dsh/index.js`（日志）
- 行为：多数轮次不再调 LLM；待确认量显著下降；新库首次 setup 后记忆区非空
- 兼容：capture 增字段为增量；已有 active/pending 数据不受影响；`BRAIN_LLM=dummy` 下闸门与种子仍可离线跑通
- 测试：`tests/test_offline.py` 增 gate / seed 幂等 / capture 分流用例
- 文档：`docs/CONCEPTS.md`、`integrations/dsh/README.md`

## 方案

- **闸门位置：服务端** `mem_mod.capture()`。DSH / Claude Code / Codex / MCP / post-commit 五条入口一次收窄；客户端只多打一行日志，避免各端判定标准漂移。
- **选型：纯函数 + 常量表**，`classify(text) -> Verdict{kind, score, hits, reason}`。可单测、可解释、可调参，无外部依赖。
- **分层解耦**：`gate.py` 只判定、不 import `llm`，便于离线（`BRAIN_LLM=dummy`）单测；成卡仍由 `llm.extract_memories` 负责。
- **保守档白名单**：只收「决策/约定/规则」与「教训/经验」两类强信号；地址/端口/版本这类一般事实不收（那是上一档）。否定作用域（`不|没|无需|不用|取消` 出现在信号词前 3 字内）不计命中。
- **种子内容与代码分离**：内容放 `data/starter/`（md/sh），`seed.py` 只负责幂等落库与「已存在则不覆盖」写入，便于非开发者增删条目。
- **现网联动（本次排查发现，属部署动作而非 spec 变更）**：线上插件 `@yueliudan/lclone-memory-dsh@0.2.1` 缺客户端归属解析（commit `9aacd09`），远端后端下 auto 捕获全部退化为全局层（表现为待确认条目没有「提升至全局」勾选框）。0.2.3 **从未发版**（registry 只有 0.2.0/0.2.1）；已把仓库源码以 `link:` 装进 web profile，需重启 DSH web 生效。

## Spec Constraints

来自已加载的 `memory-capture`（⚠️含边界）与 `cli-onboarding`：

- `memory-capture` > 记忆分类与确认：insight SHALL 仍是四段卡、原子化自包含；落库前 SHALL 过确定性准入；`_strip_ingest_noise` 剥噪 SHALL 保留
- `memory-capture` > 分工边界：闸门 SHALL NOT 把「能改写成 WHEN/THEN 的契约」放进来（归 sp-spec）
- `memory-capture` > 洞察强确认：insight SHALL 仍进 pending 待确认；种子洞察为例外（它是预置内容，不是捕获产物）
- `memory-capture` > 归属判定：闸门 SHALL NOT 改变归属逻辑——远程后端下归属仍由客户端解析并随 capture 上报 `project_id`
- `cli-onboarding` > 一键接入：`install` SHALL 仍一条命令完成；新增 `--no-seed` SHALL NOT 破坏非交互（`--yes`）场景
- `cli-onboarding` > provider 预设：种子 SHALL NOT 依赖具体 provider；`BRAIN_LLM=dummy` 下 SHALL 仍可跑通
