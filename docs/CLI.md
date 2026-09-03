# CLI / 接口参考

> 回到 [README](../README.md)

本文是**与 lclone 交互的所有接口参考**:CLI 命令、Web 面板、REST API、MCP 工具,以及模型 API 配置与环境变量。

## 命令总览

```
lclone init                           初始化数据库
lclone proj add <name> [仓库路径] [--charter "大方向"] / list / sync / rm / restore / show
lclone log "一句话摘要" [--title 标题] [--project id]        # L0 流水
lclone remember "内容" [--level insight] [--project id] [--reason 缘由] [--confirmed]
lclone capture "本次内容" [--project id] [--title 标题] [--session-key id] [--global-fallback]
lclone evolution add <文件名> [--kind script|tool|command|model|other] [--content 内容] [--ref 路径] [--reason 缘由] [--project id]
lclone evolution list [--project id] [--status]
lclone review [--id N --action keep|edit|delete|promote --edit-new "…"] [--all keep|delete]
lclone recall "查询" [--project id] [--k 5] [--no-follow]
lclone bootstrap ["话题"] [--project id] [--k 5]   # 会话启动引导: charter+全局记忆+按话题召回+待确认洞察
lclone conflicts [--project id]                    # 矛盾检测: 找疑似互相矛盾的洞察对 (需真实 LLM)
lclone promote <id>                                # 洞察上升: 项目 -> 全局层 (生命周期无限)
lclone demote <id> --project <id|name>             # 洞察下降: 挂到指定项目(含项目间横搬)
lclone suggest [--dup-threshold 0.92] [--stale-days 7] [--unused-days 30]  # 删除提示
lclone organize                                    # 整理: LLM 语义合并相近洞察 (不跨项目/等级)
lclone memories [--project id] [--level insight] [--status active|pending] [--limit 20]
lclone pending                                     # 打印待确认洞察数 (非交互, 供插件探测)
lclone supervise "新提议" --project id              # 规范环
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

## 记忆模型: 只有洞察 (insight)

lclone 的记忆只有一种正式等级——**洞察 (insight)**(见 [CONCEPTS.md](CONCEPTS.md) 第 3 节):

- 每条洞察是原子化、自包含的富知识卡,按**四段卡**(要点 / 背景-为什么 / 影响-以后注意 / 归属)书写;
- **一律需要你盖章才生效**:无论来自自动捕获 (`capture`) 还是主动记忆 (`remember`),统一进 `pending` 草稿,`review` 确认后生效;
  - `remember` 加 **`--confirmed`** 表示当场已确认、直接生效;
  - 若忘加 `--confirmed`,后续 `review` 再确认同样生效。
- **no note 通道**:早期区分「决策(强确认)/记录(免确认)」两档,后统一为「洞察」一档;过程性事实并入进化资产 / git 侧。
- **准入过滤(代码强制)**:描述"做了什么"(修复/重构/改接口/修 bug)的内容不进记忆,归 git 与 spec;
  标注 insight 但无决策信号自动降级;过短(< 4 字)的琐碎记录丢弃。
- **ingest 剥噪**:`capture` 前剥离宿主注入的标签块(`<system-reminder>`/`<private>`/`<claude-mem-context>`/`<available_skills>`/`<injected>`/`<context>`)。

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

## 生命周期与记忆整理

- **两轴命名空间**:全局层(个人区)→ 项目。全局层洞察永远加载;项目洞察在项目"活着"时加载。
  (已去掉早期的 module 维度——模块词表管理成本高于收益。)
- **上升/下降**: 洞察的"生命周期"是读取时决定的, 不落状态字段。
  - `promote <id>`: 项目洞察升到**全局层** (个人区) —— 当你发现多个项目要共读它时。
  - `demote <id> --project X`: 挂到指定项目 —— 当它不需要全局保持时; 也用于项目 A → B 横搬。
- **项目墓碑**: `proj rm` 不删行不加状态, 只登记移除事件。移除后项目从列表消失、其洞察**停止加载**,
  但数据保留, `proj restore <id|name>` 可复活。
- **洞察链接**: 内容里写 `[[m:12]]` 即链接到洞察 #12 (跨项目/跨层级均可)。召回命中时自动把被链接洞察一起带出 (一层、限量), `recall --no-follow` 可关闭。
- **进化资产**: 用 `evolution add` 把可复用脚本/工具沉淀为 `~/.lclone/evolutions/` 下的文件;洞察用 `[[evo:name.ext]]` 指向它。项目内脚本用 `--ref` 只存路径(内容留仓库)。
- **整理合并**: `organize` 让 LLM 把"语义相近、说的是同一件事"的洞察合并成一条综合描述;硬约束为**同项目 + 同等级**才能合并, 跨区域由代码校验拒绝。
- **矛盾检测**: `conflicts` 找疑似互相矛盾/规则改版的 active 洞察对, 由 LLM 判定;只提示, 不自动改。
- **删除提示**: `suggest` 用算法扫描候选 (疑似重复/长期未确认草稿/长期未召回/已移除项目记忆), 每条给出删除命令; **删除始终由你手动执行**。

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
> 注意: 问答时检索到的洞察片段会随请求发给模型厂商(隐私边界)。

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
| `BRAIN_EMBED_DIM` | `384` | dummy 后端向量维度 |
| `BRAIN_TEMPERATURE` | `0.3` | 采样温度 |
| `BRAIN_HOST` / `BRAIN_PORT` | `0.0.0.0` / `8000` | Web 面板监听 |
| `LCLONE_API_KEY` | — | Web 服务鉴权(设了后 `/api/*` 与 `/mcp` 需带 `Authorization: Bearer <key>`, `X-API-Key: <key>`;留空=本地免鉴权) |
| `LCLONE_HOME` | `~` | `doctor`/`install` 查找 skill 与触发配置的家目录 |
| `LCLONE_CMD` | `lclone` | DSH 插件调用的 lclone 命令(可指到 `.venv/bin/python -m lclone`) |
| `LCLONE_EVO_DIR` | `~/.lclone/evolutions` | 进化资产目录(文件式, 可用 `~` 展开) |
| `DSH_SESSION_ID` | — | 外部会话 id, `capture` 用它做会话聚合(DSH 插件自动注入) |

## Web 面板

启动:

```bash
python -m lclone web
# 浏览器打开 http://127.0.0.1:8000
# 后台常驻: lclone serve start (stop/status/restart)
```

### 两个页面

| 页面 | 地址 | 功能 |
|---|---|---|
| 记忆工作台 | `/` | 层级树(全局层 → 项目) + 架构图; 卡片流分页; 添加/编辑/删除/移动洞察; 待确认洞察; 添加项目、移除/复活项目; 一键整理合并; 进化资产档位 |
| 问答 | `/ask` | 带记忆问答(回顾环, 可选项目, 会话自动延续, 显示召回引用) + 边界监督(规范环) |

### 记忆工作台

- **层级树**:左侧「全局层 → 项目」两轴, 点选节点即过滤右侧架构图。
- **架构图**:右侧按「全局 / 项目」两层渲染, 洞察卡片网格分页;洞察间 `[[m:N]]` 链接画成连线。
- **上升/下降**:打开洞察详情, 在「归属」下拉选目标层级(全局层或某项目), 点「移动到所选」即移动归属(项目 → 全局、全局 → 项目、项目间横搬)。
- **进化资产**:在「进化」档位按 文件名.类型 展示 `~/.lclone/evolutions/` 下的文件(只读文本预览, 修改请改文件本身)。
- **添加洞察**:右上角「＋ 添加记忆」弹窗, 选等级(洞察)、归属(全局/项目)。手动添加视为「当场已确认」, 洞察直接生效。
- **待确认**:顶栏「待确认 N」按钮打开草稿列表, 逐条 保留/编辑/删除;数量每 30s 轮询刷新。
- **整理**:工具栏「整理」让 LLM 把语义相近的洞察合并(不跨项目/等级)。
- **刷新**:工具栏「刷新」重新拉取洞察/项目/链接。

## REST API(供其他程序调用)

鉴权: 设了 `LCLONE_API_KEY` 时, 下列 `/api/*` 与 `/mcp` 需带
`Authorization: Bearer <key>` 或 `X-API-Key: <key>`; 未设则本地免鉴权。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 健康检查 `{ok, backend, db}` |
| GET | `/api/projects` | 项目列表 `{items}` |
| POST | `/api/projects` | 注册项目 `{name, path, charter}` |
| POST | `/api/projects/{pid}/sync` | 同步 spec 索引 |
| POST | `/api/projects/{pid}/remove` | 墓碑式移除项目(可 restore) |
| POST | `/api/projects/{pid}/restore` | 复活已移除项目 |
| POST | `/api/remember` | 主动记忆 `{content, level, project_id?, reason?}`(洞察直接生效) |
| POST | `/api/capture` | 自动捕获 `{text, project_id?, title?}` |
| GET | `/api/pending` | 待确认洞察列表 `{items}` |
| GET | `/api/memories` | 列出洞察 `?project_id&level&status&limit&layer` |
| GET | `/api/evolutions` | 进化资产(文件式): `~/.lclone/evolutions/` 目录树(含 content/size/mtime) |
| GET | `/api/links` | 洞察链接表(架构图连线用) |
| POST | `/api/review` | 确认草稿 `{id, action: keep/edit/delete, content?}` |
| POST | `/api/memories/{mid}/promote` | 上升: 项目洞察 → 全局层 |
| POST | `/api/memories/{mid}/demote` | 下降: 挂到项目 `{project_id}` |
| GET | `/api/suggest` | 删除提示(仅提示, 不删除) |
| POST | `/api/organize` | 整理: LLM 语义合并相近洞察 |
| POST | `/api/recall` | 回顾检索 `{query, project_id?, k?}` |
| POST | `/api/supervise` | 边界监督 `{proposal, project_id}` |
| POST | `/api/ask` | 带记忆问答 `{question, project_id?, thread_id?, k?, with_specs?}` |
| GET | `/api/threads/{tid}/messages` | 线程历史 |
| POST | `/mcp` | MCP over HTTP(JSON-RPC), 供 Claude Code / Codex / DSH 远程接入 |

交互式 API 文档(自动生成): 浏览器打开 `http://127.0.0.1:8000/docs`。

## MCP 工具(stdio + HTTP)

`mcp_server.py` 暴露的工具(stdio 本地 / HTTP `/mcp` 远程均可调用):

```
remember / capture / recall / bootstrap / promote / demote
suggest / projects / review / ask / organize
evolution_add / evolution_list / evolution_update / conflicts
```
