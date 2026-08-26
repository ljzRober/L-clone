---
name: lclone-memory
description: |
  对话自动记忆（L-clone 外置大脑）：本 skill 在每次会话中始终生效。
  会话开始时自动 bootstrap（无条件注入 charter+全局记忆 + 按话题召回相关记忆）；
  对话中出现确定的决策、边界、值得记的事实/观察，或用户明确说"记一下/记住"时，
  自动写入本地记忆库；用户问"我们定了什么/上次做到哪"时，自动召回并总结。
  触发词：「记住」「记一下」「上次做到哪」「我们定了什么」「外置大脑」「lclone」，
  以及任何包含确定结论、边界条件、上线时间、重要事实的对话内容。
---

# L-clone 对话自动记忆

通过 `mcporter` 调用本地 lclone MCP 服务器（stdio），零依赖，任何客户端可用。

## 工具（调用方式：`mcporter call lclone.<工具> <参数>=<值>`）

| 工具 | 用途 | 关键参数 |
|---|---|---|
| `bootstrap` | 会话启动引导：一次性返回 charter + 全局层记忆（无条件）+ 按话题召回的相关记忆 | `query`（本次话题，可选）、`project` |
| `remember` | 主动记忆（C 类，直接生效）：用户已确认的决策/边界/事实 | `content`（必填）、`project`（可选，不传=全局层）、`level`（decision/note） |
| `capture` | 自动捕获（B 类，进草稿待确认）：对话中提炼候选决策/记录 | `text`（必填）、`project` |
| `recall` | 回顾检索：按关键词召回、回答"定了什么" | `query`（必填）、`k` |
| `promote` | 记忆上升：项目记忆→全局层（多项目共读） | `id` |
| `demote` | 记忆下降：挂到指定项目（不需要全局保持） | `id`、`project` |
| `suggest` | 删除提示：只提示候选，绝不主动删除 | 无 |
| `projects` | 列出项目 | 无 |
| `review` | 确认草稿：`keep` 保留 / `delete` 删除 | `id`、`action` |
| `ask` | 带记忆的问答 | `question` |

## 自动记忆规则（务必遵守）

1. **会话开始（硬性）**：先调 `bootstrap`（query=用户首条消息的话题关键词），把返回的【项目方向】+【全局记忆】+【相关记忆】纳入回答上下文；返回为空则跳过，不打扰用户。**若 bootstrap 返回了【待确认决策】，必须立刻把这些决策逐条列出，主动请用户确认保留还是删除（keep/delete），用户拍板前不静默跳过——这是「决策强确认」的硬规则。**
2. **对话中**：出现确定信息（决定了 X / 边界是 Y / 上线时间 / 值得记的过程性事实）时，自动 `capture`。capture 会自动分类：**决策(decision) 进草稿待确认**（在回复里告知"已记录决策草稿 #N，lclone review 确认"）；**记录(note) 直接生效，无需确认**。不要未经用户同意就 `remember` 直接生效——除非用户明确说"记一下/直接记/记住"（此时用 `remember`，C 类你说算）。
3. **归属判定（优先级：git → 全局判断 → 问用户）**：
   a. **先按 git 定项目**：确定当前对话/工作所在的 git 仓库（`git -C <目录> rev-parse --show-toplevel`），匹配 lclone 已注册项目；匹配到就用它——调用 `remember`/`capture` 时传 `project=<项目名>`，或传 `cwd=<仓库目录>` 让服务器自动检测。
   b. **再判断是否该升全局**：这条记忆是否被多个项目共读、是否不隶属于任何具体项目 → 是则不传 project（落到全局层，生命周期无限）；是否该把已有项目记忆 `promote` 也同理判断。
   d. **自动归模块**（项目内次级竖向）：确定项目后，根据本次工作内容判断它属于该项目的哪个模块——调用 `remember`/`capture` 时传 `module=<模块名>`（模块由你按工作主题判断，如 core/web/deploy；若项目已声明模块则优先匹配，拿不准时问用户或不传）。
   c. **拿不准就问用户**：不确定归属哪个项目、或不确定该不该全局时，**问用户，不要猜**。
4. **回答"上次定了什么 / 上次做到哪"**：`recall` 后用结果如实总结，记忆不足就明说，不编造。
5. **删除纪律**：只允许 `suggest` 提示候选、`review` 执行用户明确要求的删除；绝不主动删除记忆。
6. **草稿提醒**：如果 `capture` 产生了**决策**草稿，提醒用户去确认（CLI: `lclone review`；Web: 「待确认」页签）。记录(note) 无需提醒。
7. **提取质量**：`capture` 的提炼依赖真实 LLM 后端（`BRAIN_LLM=api`），分类为决策(decision，进待确认)/记录(note，直接生效)；dummy 后端整段视为一条 note。若用户尚未配置 API Key，仍可先用 dummy 跑通，并在合适时机提醒配置。
8. **分工边界（sp-spec ↔ lclone）**：改变项目 spec（需求/场景/⚠️边界）走 sp-spec（openspec），脑内记忆（决策/记录/charter）走 lclone。lclone 不重复存 spec 全文，只经 `specs_index` 索引；决策升格为硬边界时才进 sp-spec。

## 数据库

- 路径：`/Users/didi/github/L-clone/lclone.db`（BRAIN_DB_PATH，已在 mcporter 配置中固定）
- 配置：`/Users/didi/github/L-clone/.env`（OPENAI_API_KEY / BRAIN_BASE_URL / BRAIN_CHAT_MODEL / BRAIN_EMBED_MODEL）
- 项目源码：`/Users/didi/github/L-clone`（CLI 也可直接用 `python3 -m lclone <命令>`）
