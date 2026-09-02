## Why

当前 DSH 插件在会话首轮**直接运行 `bootstrap` 并 steer 注入记忆**，且 `cwd` 硬编码成 lclone 仓库（在别的项目会话里判错）；环境判定（全局 vs 全局+项目）也没有，全靠插件硬编码。本变更把"装记忆"从插件挪到 skill：插件在会话开始**只加载 lclone-memory 全量 skill**，由 skill（始终在场）**根据当前环境（cwd 是否落在已知项目）决定**只加载全局记忆，还是额外加载对应项目的记忆。职责分离、修掉 cwd 硬编码。

## What Changes

- **DSH 插件 `integrations/dsh/dsh/index.js`**：
  - 移除会话首轮"运行 bootstrap + steer 注入记忆"的 `runBootstrap` 逻辑。
  - 改为**注册 lclone-memory 全量 skill**（`ctx.skills.registerProvider`，读 `~/.agents/skills/lclone-memory/SKILL.md`），`inject=['skills']`；写侧 capture 与 web 路由不变。
- **`bootstrap`（`memory.py`）＋ CLI**：支持 `--cwd`；内部用 `resolve_project(conn, cwd=...)` 判定会话是否落进已知项目——已知项目 → 输出 `【项目方向】+【项目记忆】(该项目近期洞察) +【全局记忆】`；非项目/全局 → 只输出 `【全局记忆】`。
- **DSH 确认弹窗（项目级提升到全局）**：`memory.review` 新增 `promote` 动作（提升到全局层 project_id=NULL 并确认落地 active）；`client.js` 确认弹窗对**项目级**待确认洞察额外提供「提升到全局」按钮，一步落地。
- **`lclone-memory` skill**（installed + 仓库源）：规则 1 改写——"会话开始：判断 cwd 是否落进已知项目 → 是则加载 全局+项目记忆，否则只加载全局；通过 bootstrap(cwd) 驱动"。插件只保证 skill 在场，记忆注入由 agent 依 skill 决定。
- **Spec 更新**：`memory-capture`（`分工边界`/`分类加载`/新增环境判定需求）、`dsh-web-dashboard`（`会话开始注入` 改为 `会话开始加载 skill`）。

## Capabilities

### New Capabilities
- 无

### Modified Capabilities
- `dsh-web-dashboard`：`会话开始注入` 改为 `会话开始加载 skill`（插件不再注入记忆）。
- `memory-capture`：强化 `分工边界`/`分类加载`，新增"按环境（cwd→项目）决定 全局 vs 全局+项目"需求。

## Impact

- 受影响系统：DSH 插件（`integrations/dsh/dsh/index.js`）、`bootstrap`（`memory.py` + `cli.py`）、`lclone-memory` skill（installed + 仓库源）。
- 受影响文档：`dsh-web-dashboard` / `memory-capture` spec；`integrations/dsh/README.md`（读侧改为"skill 按环境注入"）。
