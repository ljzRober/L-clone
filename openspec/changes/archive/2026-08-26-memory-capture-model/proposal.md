## Why

这一轮把「记忆捕获」的行为模型打磨清楚了，但这些规则散落在代码、skill、文档里，没有形成 spec。需要把它们固化成 `memory-capture` spec，作为后续"记忆该不该记、怎么记、怎么确认"的 SSOT。

## What Changes

- 新增 `memory-capture` spec，固化五条行为：
  1. 记忆分类：note 免确认直接 active；decision 进 pending 待确认
  2. 决策强确认：每轮 bootstrap 带出【待确认决策】，有决策时主动弹窗确认（保留/删除）
  3. 分工边界：代码改动/接口变化归 git，spec 变更归 sp-spec；lclone 只留决策（选型/约定）+ 记录（过程事实）
  4. 记录按会话聚合：同一 session_key 只一条 note，逐轮追加；新会话新 note
  5. note 滚动压缩：超长（>3000 字）时摘要压缩

## Capabilities

- **New Capabilities**:
  - `memory-capture`：记忆捕获与确认的行为模型
- **Modified Capabilities**: 无

## 方案

这些行为已在代码中实现并提交（`54270f9`、`3079333`、`7e14cf1`、`c512888` 等），本次纯为补 spec 固化，不改代码。

## Spec Constraints

- 不修改 `web-hierarchy` / `cli-onboarding` / `server-api` 既有 spec。

## Impact

- 文件：新增 `openspec/changes/memory-capture-model/specs/memory-capture/spec.md`
- 代码：无改动
