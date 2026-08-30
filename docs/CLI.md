# CLI 参考

> 回到 [README](../README.md)

## 命令总览

```
lclone init                           初始化数据库
lclone proj add <name> [仓库路径] [--charter "大方向"]
lclone proj list / sync <id|name> / rm / restore / show
lclone log "一句话摘要" [--title 标题] [--project id]        # L0 流水
lclone remember "内容" [--level decision|note] [--project id] [--module 名] [--reason 缘由] [--confirmed]
lclone capture "本次工作内容" [--project id] [--title 标题] [--module 名] [--session-key id] [--global-fallback]
lclone review [--id N --action keep|edit|delete --edit-new "…"] [--all keep|delete]
lclone recall "查询" [--project id] [--k 5] [--no-follow]
lclone bootstrap ["话题"] [--project id] [--k 5]   # 会话启动引导: charter+全局记忆+召回+待确认决策
lclone promote <id>                            # 记忆上升: 项目 -> 全局层
lclone demote <id> --project <id|name>         # 记忆下降: 挂到指定项目(含项目间横搬)
lclone suggest [--dup-threshold 0.92] [--stale-days 7] [--unused-days 30]  # 删除提示
lclone organize                                # 整理: LLM 语义合并相近记忆(不跨项目/等级/模块)
lclone memories [--project id] [--level decision|note] [--status active|pending|archived] [--limit 20]
lclone pending                                 # 打印待确认决策 JSON [{id, content}] (供插件探测)
lclone supervise "新提议" --project id          # 规范环
lclone ask "问题" [--project id] [--thread id] [--k 5] [--no-specs] [-v]
lclone web [--host 0.0.0.0] [--port 8000]
lclone serve start|stop|status|restart                                       # 管理 web 后台服务
lclone setup [--provider deepseek] [--api-key xx] [--yes]                                # 部署后端: 空项目起步, 不注册项目
lclone integrate [--target skill|dsh|claude|codex|commit|all]                            # 接入 AI 工具(交互式选 target)
lclone install [--provider deepseek] [--api-key xx] [--target all] [--yes]               # = setup + integrate
lclone doctor [--check-llm] [--backend] [--integration]                                  # 自检(默认前后端分段展示)
lclone backup [--dest backups]                                              # SQLite 在线快照备份
```

所有子命令可用 `--db <路径>` 指定数据库、`--cwd <目录>` 指定工作目录(git 归属判定用),前后均可。

## 接入的两条命令(务必分清)

部署后台服务与接入 AI 工具前端是两件事, 拆成两条命令互不干扰:

| 命令 | 做什么 | 不做什么 |
|---|---|---|
| `lclone setup` | 选 provider + 填 key → 生成 `.env` → init DB(空库) → 后端自检 | 不注册项目、不装 skill、不配 hooks/插件 |
| `lclone integrate` | 装 skill(`~/.agents/skills`) + 按所选 target 配 Claude Code / Codex / DSH / commit 钩子 → 集成自检 | 不碰 `.env`、数据库、项目、模型配置 |

- 只想跑一个后台 Web 服务 → `lclone setup` 就够了(空项目起步, 之后用 `lclone proj add` 加项目)。
- `setup` 的 provider 是**方向键单选菜单**(↑/↓ 选择 + 回车确认, 不支持的终端回退输序号);已有 `.env` 时直接沿用现有配置, 不再重复问。
- 想让 Claude Code / Codex / DSH 自动读写大脑 → 再单独跑 `lclone integrate`(交互式选 target)或 `lclone integrate --target <工具>`。
- `lclone integrate --target skill` 只装通用 skill, 不配任何特定工具。
- `lclone install` = 两者都做(新用户一键全流程)。
- `lclone doctor` 默认**前后端都查、分段展示**; `--backend` 只查后端, `--integration` 只查前端。

## 记忆写入语义(重要)

- **决策(decision)一律需要你盖章才生效**,无论来自自动捕获还是主动记忆:
  - `capture` 提炼出的决策 → `pending` 草稿,`lclone review` 确认后生效;
  - `remember` 默认也是 `pending`,加 **`--confirmed`** 表示当场已确认、直接生效;
  - `--level note`(记录)恒直接生效,免确认。
- **记录(note)** 是过程性事实/观察/TODO,低风险,直接进库;自动捕获时同一 `session_key`
  只建一条 note,每轮**追加原文**,超长时自动**滚动压缩**为摘要。
- **准入过滤(代码强制)**:描述"做了什么"(修复/重构/改接口/修 bug)的内容不进记忆,归 git 与 spec;
  标注为 decision 但不含决策信号的内容自动降级为 note;过短的琐碎记录丢弃。

## 生命周期与记忆整理

- **三级命名空间**:全局层(个人区)→ 项目 → 模块。全局层记忆永远加载;项目记忆在项目"活着"时加载;模块是项目内可选的次级竖向划分,**仅决策挂模块,记录无模块**。
- **上升/下降**: 记忆的"生命周期"是读取时决定的, 不落状态字段。
  - `promote <id>`: 项目记忆升到**全局层** (个人区) —— 当你发现多个项目要共读它时。
  - `demote <id> --project X`: 挂到指定项目 —— 当它不需要全局保持时; 也用于项目 A → B 横搬。
- **项目墓碑**: `proj rm` 不删行不加状态, 只登记移除事件。移除后项目从列表消失、
  其记忆**停止加载**, 但数据保留, `proj restore <id|name>` 可复活。
- **模块管理**:模块名由 LLM 分类、代码维护词表(归一化/复用/防泛名);`proj` 与 Web 面板支持
  添加/删除模块(删除模块会连带删除该模块下的决策记忆)。
- **记忆链接**: 内容里写 `[[m:12]]` 即链接到记忆 #12 (跨项目/跨层级均可)。
  召回命中时自动把被链接记忆一起带出 (一层、限量), `recall --no-follow` 可关闭。
- **整理合并**: `organize` 让 LLM 把"语义相近、说的是同一件事"的记忆合并成一条综合描述;
  硬约束为**同项目 + 同等级 + 同模块**才能合并, 跨区域由代码校验拒绝。
- **删除提示**: `suggest` 用算法扫描候选 (疑似重复/长期未确认草稿/长期未召回/
  已移除项目记忆), 每条给出删除命令; **删除始终由你手动执行**。

## 模型 API 配置参考

`BRAIN_BASE_URL` 可切任意 OpenAI 兼容服务;推荐直接 `lclone setup` 按 provider 预设生成 `.env`:

| 服务 | BASE_URL | chat 模型示例 | embed 模型示例 |
|---|---|---|---|
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` | `text-embedding-3-small` |
| Claude (Anthropic) | `https://api.anthropic.com/v1` | `claude-3-5-haiku-latest` | (无 embed, 走本地哈希) |
| Gemini (Google) | `https://generativelanguage.googleapis.com/v1beta/openai` | `gemini-2.0-flash` | `text-embedding-004` |
| Copilot (GitHub Models) | `https://models.inference.ai.azure.com` | `gpt-4o-mini` | (无 embed, 走本地哈希) |
| Kimi (Moonshot) | `https://api.moonshot.cn/v1` | `moonshot-v1-8k` | (无 embed, 走本地哈希) |
| MiniMax | `https://api.minimaxi.com/v1` | `MiniMax-Text-01` | (无 embed, 走本地哈希) |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-v4-flash` | (无 embed 接口, 自动走本地哈希向量) |
| 硅基流动 | `https://api.siliconflow.cn/v1` | `Qwen/Qwen2.5-7B-Instruct` | `BAAI/bge-m3` |
| 智谱 | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-flash` | `embedding-3` |

> Key 说明: Copilot 用 GitHub Personal Access Token、Claude 用 Anthropic key、Gemini 用 Google AI Studio key、Kimi 用 Moonshot key、MiniMax 用 MiniMax key。
> 模型名按各服务商最新列表自行调整(改 `.env` 里的 `BRAIN_CHAT_MODEL` 即可)。

> 若 embed 模型不可用, 可把 `BRAIN_EMBED_BACKEND=local`(本地确定性哈希向量, 零依赖),
> 或把 `BRAIN_EMBED_MODEL` 指到任一兼容服务;
> 注意: 问答时检索到的记忆片段会随请求发给模型厂商(隐私边界)。

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `BRAIN_DB_PATH` | `lclone.db` | 数据库文件路径 |
| `BRAIN_LLM` | `api` | `api`(真实模型) / `dummy`(离线自测) |
| `OPENAI_API_KEY` | — | API Key |
| `BRAIN_BASE_URL` | `https://api.openai.com/v1` | OpenAI 兼容接口地址 |
| `BRAIN_CHAT_MODEL` | `gpt-4o-mini` | 对话/提炼/监督模型 |
| `BRAIN_EMBED_MODEL` | `text-embedding-3-small` | 向量化模型 |
| `BRAIN_EMBED_BACKEND` | `api` | `api`(真实 embed 接口) / `local`(本地哈希向量, 用于 DeepSeek 等无 embed 接口的服务商) |
| `BRAIN_TEMPERATURE` | `0.3` | 采样温度 |
| `BRAIN_HOST` / `BRAIN_PORT` | `0.0.0.0` / `8000` | Web 面板监听 |
| `LCLONE_API_KEY` | — | Web 服务鉴权(设了后 `/api/*` 与 `/mcp` 需带 `Authorization: Bearer <key>` 或 `X-API-Key: <key>`;留空=本地免鉴权) |
| `LCLONE_HOME` | `~` | `doctor`/`install` 查找 skill 与触发配置的家目录 |
| `LCLONE_CMD` | `lclone` | DSH 插件调用的 lclone 命令(可指到 `.venv/bin/python -m lclone`) |
| `DSH_SESSION_ID` | — | 外部会话 id, `capture` 用它做 note 逐轮聚合(DSH 插件自动注入) |
