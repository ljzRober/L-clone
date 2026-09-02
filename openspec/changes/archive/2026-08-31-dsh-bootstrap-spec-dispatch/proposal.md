## Why

当前 DSH 里"全局思维先介入"依赖 agent 遵守 lclone-memory skill（软触发），不确定；且 sp-spec 需要用户手动 `/sp-spec` 触发。这与"人类逻辑：先全局思维（lclone bootstrap）、后取契约实施（sp-spec 加载 spec）"的确定性管线不符。本变更让 DSH 的 read-side（bootstrap 注入）也变硬触发，并让 lclone 作为编排层自动调度 sp-spec（默认 quick，升级由 sp-spec 自决），缺失时首次会话提醒一次。

## What Changes

- **DSH 插件 `integrations/dsh/dsh/index.js`**：新增**会话开始注入**——首个 turn 触发时运行 `lclone bootstrap`，经 `agent.steer({source:{kind:'plugin'}})` 注入当前会话上下文（每会话一次），补齐 `inject=['agents']`。此前插件只做写侧（capture）硬触发；本变更把 read-side 也变成硬触发。
- **`lclone-memory` skill**（`~/.agents/skills/lclone-memory/SKILL.md` ＋ 仓库源 `integrations/skill/SKILL.md`）升级为编排层：
  - 会话开始 bootstrap（走钩子 + skill 双保险）。
  - **检测 sp-spec 可用性**（`~/.agents/skills/sp-spec` 存在）。
  - **有** → 出现构建性任务时默认**自动加载 sp-spec 并走 quick**（是否升级 full/debug 由 sp-spec 自决），无需用户手动 `/sp-spec`。
  - **无** → **首次会话提醒一次**安装：`https://github.com/ljzRober/sp-spec`，不重复提醒。
- **Spec 更新**：`dsh-web-dashboard` 增"会话开始注入"需求；`memory-capture` 增"自动调度 sp-spec"需求并强化"分工边界"顺序（lclone 全局思维先介入 → sp-spec 后取契约）。

## Capabilities

### New Capabilities
- 无

### Modified Capabilities
- `dsh-web-dashboard`：新增需求 `会话开始注入`（read-side 硬触发）。
- `memory-capture`：新增需求 `自动调度 sp-spec`；强化 `分工边界`（明确"lclone 先全局、sp-spec 后契约"的顺序）。

## Impact

- 受影响系统：DSH 插件（`integrations/dsh/dsh/index.js`）、`lclone-memory` skill（全局安装 + 仓库源）。
- 受影响文档：`dsh-web-dashboard` / `memory-capture` spec；`integrations/dsh/README.md`（read-side 由 skill 软触发 → 改为插件硬触发）。
