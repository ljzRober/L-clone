## Why

决策强确认只在「会话开始 bootstrap」触发，但后台 DSH 插件在会话进行中持续静默捕获决策进 pending，导致对话中产生的决策无人提示、一直挂着。需要把确认从「会话开始」扩展到「会话进行中每轮」。

## What Changes

- **决策强确认扩展到逐轮**：会话进行中每轮回复前也检查【待确认决策】并弹窗确认，不只在会话开始。
- **插件只捕获用户消息**：`integrations/dsh/dsh/index.js` 不再 buffer `assistant/message`，避免把 assistant 的总结/元陈述误当决策，减少 pending 噪音。
- **skill 规则 1b**：新增「会话进行中每轮回复前先检查待确认决策并弹窗确认」。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `memory-capture`: 「决策强确认」新增「会话中逐轮检查」场景。

## Impact

- 代码：`integrations/dsh/dsh/index.js`（只捕获用户消息）
- skill：`integrations/skill/SKILL.md` + `~/.agents/skills/lclone-memory/SKILL.md`（规则 1b）
- 无第三方依赖

## 方案

- 插件：`if (event.type === 'user/message')` 只 buffer 用户消息。
- skill 规则 1b：每轮回复前 `bootstrap`（query 空）检查【待确认决策】，有就 `ask_user_question` 逐条确认。

## Spec Constraints

- `memory-capture` > 决策强确认 > 弹窗确认：用工具弹窗逐条请用户保留/删除。
