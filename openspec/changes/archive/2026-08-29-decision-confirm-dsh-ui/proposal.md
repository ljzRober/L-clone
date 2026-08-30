## Why

决策确认的现有实现（`决策强确认`）在每轮 `turn/end` 后检测到 pending 决策时，用 `agent.steer` 强制唤醒主 agent 去问用户保留/删除。这个「事后回顾 + 单独唤醒一问」的形态与「新起一个 agent」无异：它把主 agent 从当前事务里拖出去处理一张待办券，打断感强，且每一步都依赖 LLM 判断，漏掉/误判都会造成打扰或丢失。工作台已有「待确认决策」弹窗（`/api/pending` + keep/delete），覆盖了「沉淀后集中确认」这条路径。本变更把**判断**留在 `turn/end`（并且纳入助手回应作为「是否落地」的信号），把**呈现**从「劫持主 agent」改为「分端原生 UI」——DSH 用 UI 弹窗/角标表达，不进主 agent；非 web 端（CLI）暂不新增路径，维持 bootstrap 带出待确认。

## What Changes

- **判断时机不变，输入变丰富**：host 端从「只捕获用户消息」改为「按会话累计用户+助手消息」，`turn/end` 时把整段交换喂给 `lclone capture`；分类器据此判断「用户说了什么 + 助手是否实现/确认了 → 能否落成一条决策」。
- **去掉 steer 劫持（*BREAKING，DSH*）**：`index.js` 移除 `agent.steer` 强制注入主 agent；pending 决策改由 DSH 客户端以 UI 呈现，主 agent 全程不参与确认。
- **DSH 决策确认 UI**：`client.js` 轮询 host 新增的 `/api/lclone-decisions`，检测到新增 pending 决策时在对话区弹一个非侵入弹窗（决策内容 + 保留/删除按钮），用户点击后经 `/api/lclone-review` 调 `lclone review` 生效；侧边栏「大脑看板」按钮同步展示待确认角标。忽略则落工作台（已有兜底）。
- **分类器纳入「助手实现」信号**：`llm.extract_memories` 提示词补充「只有用户提出的选择/规则被助手确认、落地或持续推进才算 decision；仅随口一提未获回应的排除」，配合传入的整段交换生效。
- **host 代理路由**：`index.js` 在既有 `ctx.inject(['webServer'])` 中新增 `/api/lclone-decisions`（GET pending）与 `/api/lclone-review`（POST keep/delete），避免跨越 :8000 的 CORS/鉴权。
- **其他端暂不新增**：CLI/codex 等非 web 端本轮不实现新的确认 UI，维持 bootstrap 带出待确认（CLI agent 路径不变）。

## Capabilities

### New Capabilities

（无独立新 spec——DSH 决策确认 UI 作为 `dsh-web-dashboard` 的一条新增 Requirement 承载，不另立 spec。）

### Modified Capabilities

- `memory-capture`：`决策强确认` 的**呈现**从「宿主用 agent.steer 强制注入 + ask_user_question」改为「分端呈现：DSH=UI 弹窗/角标不进主 agent，非 web 端=bootstrap 带出」；判断输入纳入「用户+助手」整段交换。
- `dsh-web-dashboard`：`安装与加载` 的「host 逻辑不回归」场景更新（不再是 steer 提醒）；新增 Requirement `决策确认 UI`（客户端轮询 + 弹窗保留/删除 + 侧边栏角标 + host `/api/lclone-decisions`、`/api/lclone-review` 代理路由）。

## Impact

- `integrations/dsh/dsh/index.js`：捕获用户+助手消息、去 steer、新增 `/api/lclone-decisions`、`/api/lclone-review` 代理路由。
- `integrations/dsh/dsh/client.js`：新增决策确认弹窗/角标、轮询、keep/delete 提交。
- `lclone/llm.py`：`extract_memories` 提示词补充「助手实现/落地」判定约束。
- `integrations/dsh/dsh/client.js`（可选）：留观，不再改 `lclone/memory.py` 的 capture 聚合/准入逻辑。
- 无新增依赖；重装/重启 dsh web 生效（插件 symlink 链入，改 index.js/client.js 后重启即可）。
