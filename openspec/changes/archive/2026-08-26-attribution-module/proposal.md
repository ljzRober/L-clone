## Why

自动捕获的「归属」打磨清楚了，但散在代码和 skill 里，没进 spec。需要固化两条：项目归属（git 优先、无 git 问用户）与模块归属（分类器按主题自动派生，同 sp-spec 分 spec 逻辑）。

## What Changes

- `memory-capture` spec 新增两条需求：
  1. 归属判定：git 检测到已注册项目优先归该项目；无 git 或匹配不到时必须问用户（新建 project 或升全局），不静默默认。
  2. 模块归属：分类器按工作主题自动派生 module（与 sp-spec 分 spec 同逻辑），capture 自动补录 modules 表。

## Capabilities

- **New Capabilities**: 无
- **Modified Capabilities**:
  - `memory-capture`：新增「归属判定」「模块归属」两条需求

## 方案

已在代码实现并提交（`7e13b3a`、`934aaaf`），本次纯补 spec 固化。

## Spec Constraints

- 不修改 web-hierarchy / cli-onboarding / server-api 既有 spec。
