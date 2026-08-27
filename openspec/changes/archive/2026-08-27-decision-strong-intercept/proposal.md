## Why

决策强确认之前依赖「agent 每轮自觉检查 pending 并弹窗」，模型可能不做。现在改为代码强制：宿主插件在 turn/end 用 `agent.steer` 注入引导消息唤醒 agent，agent 用 `ask_user_question` 强拦截逐条请用户确认。需要把最终机制固化进 spec。

## What Changes

- **决策强确认改为代码强制**：`turn/end → 探测 pending → agent.steer 注入（source=plugin）→ 唤醒 agent → ask_user_question 强拦截 → review 处理`。
- **去重防循环**：pending 数未增加时不重复注入。
- **只抓用户消息 + 过滤「无内容」元响应**：减少噪音（已实现）。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `memory-capture`: 「决策强确认」需求更新为 agent.steer 强制注入机制，新增「去重防循环」场景。

## Impact

- 代码：`integrations/dsh/dsh/index.js`（agent.steer 注入 + 去重）、`lclone/cli.py`（pending 命令）、`lclone/llm.py`（过滤无内容元响应）
- 无第三方依赖

## 方案

```
turn/end → runCapture 完成 → checkPending(lclone pending) → 若 pending 新增:
  ctx.agents.get(sessionId).steer({ source:{kind:'plugin', plugin:'lclone-memory'}, ... })
  → 唤醒 agent → agent 用 ask_user_question 逐条强拦截 → 用户拍板 → review 处理
```

## Spec Constraints

- `memory-capture` > 决策强确认 > 弹窗确认：用 ask_user_question 逐条请用户保留/删除。
