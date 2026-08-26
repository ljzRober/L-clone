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
| `bootstrap` | 会话启动引导：返回 charter + 全局层记忆 + 按话题召回 + 【待确认决策】 | `query`（可选）、`project` |
| `remember` | 主动记忆：用户已确认的决策/边界/事实 | `content`（必填）、`project`（名/id/global）、`level`（decision/note）、`confirmed`（boolean） |
| `capture` | 自动捕获：提炼决策/记录，返回结构化结果 | `text`（必填）、`project`、`cwd`、`session_key`、`module` |
| `recall` | 回顾检索：按关键词召回、回答"定了什么" | `query`（必填）、`k` |
| `promote` | 记忆上升：项目记忆→全局层 | `id` |
| `demote` | 记忆下降：挂到指定项目 | `id`、`project` |
| `suggest` | 删除提示：只提示候选，绝不主动删除 | 无 |
| `projects` | 列出项目 | 无 |
| `review` | 确认草稿：`keep` 保留 / `delete` 删除 | `id`、`action` |
| `ask` | 带记忆的问答 | `question` |

## 自动记忆规则（务必遵守）

1. **会话开始（硬性）**：先调 `bootstrap`（query=用户首条消息的话题关键词），把返回的【项目方向】+【全局记忆】+【相关记忆】纳入回答上下文；返回为空则跳过，不打扰用户。**若 bootstrap 返回了【待确认决策】，必须立刻用 `ask_user_question` 逐条请用户确认保留还是删除（keep/delete），用户拍板前不静默跳过。**
2. **对话中**：出现确定信息（决定了 X / 边界是 Y / 上线时间 / 值得记的过程性事实）时，自动 `capture`（传 `cwd=<工作目录>`、`session_key=<本会话 id>`）。capture 由代码强制完成归属/聚合/分类/模块：
   - 返回**结构化结果**：`记录(已生效)` 与 `决策(待确认)` 分开列出；
   - 若含 `决策(待确认)`，**必须立刻用 `ask_user_question` 逐条向用户确认保留/删除**；
   - 若返回以 `⚠️未归属` 开头，**必须先弹窗问用户归属**（新建项目并取名，还是 `project=global`），得到答复后重试，**不得静默默认全局**。
   - 用户明确说"记一下/直接记/记住"时用 `remember`：`level=note` 恒直接生效；`level=decision` 只有当用户**当场已确认**该决策时才传 `confirmed=true`，否则让它进待确认。
3. **归属判定（代码强制，无需你判断）**：capture/remember 不传 `project` 时会按 `cwd` 的 git 自动判定——命中已注册项目则归它；检测到仓库但未注册则**自动注册**（名=仓库 basename）；**只有无 git 才返回「⚠️未归属」信号**，此时才需要你弹窗问用户。
4. **模块归属（代码强制）**：module 由 lclone 代码按 embedding 增量聚类自动派生（与 sp-spec 分 spec 同逻辑、按关注点自组织），LLM 不起名；你无需也不应手动指定 module，除非用户明确点名某模块。
5. **回答"上次定了什么 / 上次做到哪"**：`recall` 后用结果如实总结，记忆不足就明说，不编造。
6. **删除纪律**：只允许 `suggest` 提示候选、`review` 执行用户明确要求的删除；绝不主动删除记忆。
7. **提取质量**：`capture` 的提炼依赖真实 LLM 后端（`BRAIN_LLM=api`），分类为决策(decision，进待确认)/记录(note，直接生效)；dummy 后端整段视为一条 note。若用户尚未配置 API Key，仍可先用 dummy 跑通，并在合适时机提醒配置。
8. **分工边界（sp-spec ↔ lclone）**：改变项目 spec（需求/场景/⚠️边界）走 sp-spec（openspec）；代码改动/接口变化/新增端点/重构/修 bug 走 git——**这两类都不 capture 进 lclone 记忆**。脑内记忆只留「决策」（选了什么方案/定了什么规则）与「记录」（过程性事实/观察）。lclone 只经 `specs_index` 索引 spec，不重复存全文；决策升格为硬边界时才进 sp-spec。

## 数据库

- 路径：`/Users/didi/github/L-clone/lclone.db`（BRAIN_DB_PATH，已在 mcporter 配置中固定）
- 配置：`/Users/didi/github/L-clone/.env`（OPENAI_API_KEY / BRAIN_BASE_URL / BRAIN_CHAT_MODEL / BRAIN_EMBED_MODEL）
- 项目源码：`/Users/didi/github/L-clone`（CLI 也可直接用 `python3 -m lclone <命令>`）
