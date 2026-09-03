---
name: lclone-memory
description: |
  对话自动记忆（L-clone 外置大脑）：本 skill 在每次会话中始终生效。
  会话开始时自动 bootstrap（无条件注入 charter+全局记忆 + 按话题召回相关记忆）；
  对话中出现确定的洞察、边界、值得记的事实/观察，或用户明确说"记一下/记住"时，
  自动写入本地记忆库；用户问"我们定了什么/上次做到哪"时，自动召回并总结。
  触发词：「记住」「记一下」「上次做到哪」「我们定了什么」「外置大脑」「lclone」，
  以及任何包含确定结论、边界条件、上线时间、重要事实的对话内容。
---

# L-clone 对话自动记忆

通过 `mcporter` 调用本地 lclone MCP 服务器（stdio），零依赖，任何客户端可用。

## 工具（调用方式：`mcporter call lclone.<工具> <参数>=<值>`）

| 工具 | 用途 | 关键参数 |
|---|---|---|
| `bootstrap` | 会话启动引导：返回 charter + 全局层记忆 + 按话题召回 + 【待确认洞察】 | `query`（可选）、`project` |
| `remember` | 主动记忆：用户已确认的洞察/边界/事实 | `content`（必填）、`project`（名/id/global）、`level=insight`、`confirmed`（boolean） |
| `capture` | 自动捕获：提炼洞察（进待确认），返回结构化结果 | `text`（必填）、`project`、`cwd`、`session_key` |
| `evolution_add` | 沉淀进化资产（可复用脚本/工具） | `name`、`content`/`ref`、`kind`、`reason`、`project` |
| `recall` | 回顾检索：按关键词召回、回答"定了什么" | `query`（必填）、`k` |
| `promote` | 记忆上升：项目记忆→全局层 | `id` |
| `demote` | 记忆下降：挂到指定项目 | `id`、`project` |
| `suggest` | 删除提示：只提示候选，绝不主动删除 | 无 |
| `projects` | 列出项目 | 无 |
| `review` | 确认草稿：`keep` 保留 / `delete` 删除 | `id`、`action` |
| `ask` | 带记忆的问答 | `question` |

## 自动记忆规则（务必遵守）

1. **会话开始（记忆已由 DSH 插件注入一次，不重复）**：DSH 宿主中，lclone-memory 插件已在**会话首轮**一次性把【skill 全文】+【bootstrap 记忆】注入进会话（agent 无需再调 bootstrap）。只有当上下文里**没有**记忆段时（非 DSH 宿主 / CLI / Codex / 插件未注入），agent 才补调一次 `bootstrap`：
   - `cwd` 落在**已知项目** → `bootstrap --cwd <当前cwd>`（【项目方向】+【项目记忆】+【全局记忆】）。
   - 否则 / 无 cwd → `bootstrap`（只注入【全局记忆】）。
   - Claude Code / Codex：SessionStart 钩子自动 `bootstrap ""` 注入，同样按 cwd 环境带回项目记忆。
   - 返回为空则跳过。记忆已在场时**不要重复注入**。
1b. **会话进行中（洞察已由客户端 UI 承接，不每轮 bootstrap）**：DSH 宿主中，待确认洞察由客户端轮询 `/api/lclone-decisions` 以弹窗/角标呈现（用户经 `/api/lclone-review` 保留/删除），agent 不调 bootstrap、不用 `ask_user_question` 重复确认。非 UI 宿主（CLI / codex）才在回复前调一次 `bootstrap`（query 可空）检查【待确认洞察】，并逐条 `ask_user_question` 请用户保留/删除，避免 pending 悬挂。
2. **对话中**：出现确定信息（决定了 X / 边界是 Y / 上线时间 / 值得记的经验教训）时，自动 `capture`（传 `cwd=<工作目录>`、`session_key=<本会话 id>`）。capture 由代码强制完成归属/自筛/剥噪，把内容提炼为**洞察(insight)**：
   - 返回**结构化结果**：`洞察(待确认)`（统一进草稿，须 review 才生效）；
   - 若含 `洞察(待确认)`，**呈现按宿主分**：DSH 已由客户端 UI（弹窗/角标 + `/api/lclone-review`）承接，agent 不再重复 `ask_user_question`；非 UI 宿主才用 `ask_user_question` 逐条确认；
   - 若返回以 `⚠️未归属` 开头，**必须先弹窗问用户归属**（新建项目并取名，还是 `project=global`），得到答复后重试，**不得静默默认全局**。
   - 用户明确说"记一下/直接记/记住"时用 `remember`：只有 `level=insight`（洞察一级）；若用户**当场已确认**该洞察则传 `confirmed=true` 直接生效，否则让它进待确认（后续 `review` 再盖章）。
   - 若用户做出了一个**可复用脚本/工具**（反复实践、稳定不再改），可用 `evolution_add`（项目内用 `ref`，项目无关用 `content`）。
3. **归属判定（代码强制，无需你判断）**：capture/remember 不传 `project` 时会按 `cwd` 的 git 自动判定——命中已注册项目则归它；检测到仓库但未注册则**自动注册**（名=仓库 basename）；**只有无 git 才返回「⚠️未归属」信号**，此时才需要你弹窗问用户。
4. **项目 vs spec 判定（代码强制）**：**凡是"代码必须满足的契约"**（能改写成带 `WHEN…THEN…` 的 requirement，如某参数必须转义、某超时阈值必须为 X）**一概归 sp-spec，不提炼为记忆**；只有"为什么这么选 / 观察到什么"这类**无法写成契约**的理由/事实才进记忆。半契约半理由要**拆开**：理由归记忆、契约归 spec。一条记忆**升格为契约**（被锁定为"必须满足 X"且能写成 WHEN/THEN）时才进 sp-spec，此时在记忆里写 `[[spec:id]]` 引用或删除，避免双份漂移。
5. **回答"上次定了什么 / 上次做到哪"**：`recall` 后用结果如实总结，记忆不足就明说，不编造。
6. **删除纪律**：只允许 `suggest` 提示候选、`review` 执行用户明确要求的删除；绝不主动删除记忆。
7. **提取质量**：`capture` 的提炼依赖真实 LLM 后端（`BRAIN_LLM=api`），把内容提炼为**洞察(insight)**（原子化、自包含、四段卡），统一进待确认、经 `review` 生效；`BRAIN_LLM=dummy` 无法真正提炼富洞察，会退化为记录原文草稿（仍待确认）。若用户尚未配置 API Key，仍可先用 dummy 跑通，并在合适时机提醒配置。
8. **分工边界（sp-spec ↔ lclone）**：改变项目 spec（需求/场景/⚠️边界）走 sp-spec（openspec）；代码改动/接口变化/新增端点/重构/修 bug 走 git——**这两类都不 capture 进 lclone 记忆**。脑内记忆只留**洞察**（选了什么方案/定了什么规则/学到什么经验教训，原子化富知识卡）与**进化资产**（可复用脚本/工具，`~/.lclone/evolutions/` 文件式，`[[evo:name.ext]]` 指向）。lclone 只经 `specs_index` 索引 spec，不重复存全文；洞察升格为硬边界时才进 sp-spec。
9. **自动调度 sp-spec（无需手动 /sp-spec）**：检测 sp-spec 是否已安装（`~/.agents/skills/sp-spec` 存在）。**有** → 会话中一旦进入构建性任务（改功能/修 bug/重构），默认**自动加载 sp-spec 并运行 quick 模式**（是否升级 full/debug 由 sp-spec 自决），不需要用户手动 `/sp-spec`。**无** → 仅在**首次**会话提醒一次用户安装 sp-spec：`https://github.com/ljzRober/sp-spec`，之后不再重复提醒（可在 lclone 写入一条"已提示安装 sp-spec"的全局记忆避免重复）。

## 数据库

- 路径：`<仓库根目录>/lclone.db`（BRAIN_DB_PATH，已在 mcporter 配置中固定）
- 配置：`<仓库根目录>/.env`（OPENAI_API_KEY / BRAIN_BASE_URL / BRAIN_CHAT_MODEL / BRAIN_EMBED_MODEL / BRAIN_EMBED_BACKEND）
- 项目源码：`<仓库根目录>`（CLI 也可直接用 `python3 -m lclone <命令>`）
