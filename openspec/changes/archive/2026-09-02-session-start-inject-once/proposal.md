## Why

原 DSH read-side（会话开始注入记忆）被 `skill-load-env-inject` 改成「只注册 skill、由 agent 依 skill 规则按环境决定加载」，导致很多会话（如本仓库一次会话）**没注入记忆**——因为 skill 只登记成「可用」（目录里只有 description），未全量加载、也非主导。用户要求：会话开始时 skill 全量加载并占主导，注入【全局+项目】记忆；后续每轮**只 capture、不重复注入记忆**（每会话注入一次即可）。

## What Changes

- **`integrations/dsh/dsh/index.js`**：会话**首轮** user/message 时一次性运行 `lclone bootstrap --cwd <会话cwd>`（环境感知，命中项目→项目+全局，否则仅全局），并把【lclone-memory skill 全文】+【bootstrap 记忆】经 `agent.steer` 注入一次（完整 UserMessage 形状 + `source:{kind:'plugin'}`）；用 `bootstrapped` Set 保证**每会话只注入一次**。`inject` 补 `'agents'`。写侧 capture 与决策确认客户端 UI 不变。
- **`integrations/skill/SKILL.md`**（＋安装副本 `~/.agents/skills/lclone-memory/SKILL.md`）：规则 1 改为「记忆已由 DSH 插件注入一次，不重复；仅非 DSH 宿主/未注入时才补调 bootstrap」；规则 1b 改为「DSH 宿主不再每轮 bootstrap 查待确认（改由客户端 UI 弹窗/角标承接）」。
- **Spec**：`dsh-web-dashboard`「会话开始加载 skill」改为「会话开始注入」（插件首轮注入一次）；`memory-capture`「按环境加载记忆」明确为「按环境决定内容，但只注入一次」。

## 设计（按环境加载 + 只注入一次）

- **注入内容由环境决定**：`bootstrap --cwd` 走 `detect_project_by_git`——`cwd` 落进已知项目 → 注入【项目方向 + 项目记忆 + 全局记忆】；否则仅【全局记忆】。
- **注入频率**：每会话**一次**（会话首轮），不因后续轮次重复注入。skill 全文+记忆注入后主导整段会话。
- **写侧**：每轮 `turn/end` 仍 `capture` 记洞察；待确认洞察由客户端 UI（轮询 `/api/lclone-decisions`）承接，不靠每轮 bootstrap。

## Impact

- 代码：`integrations/dsh/dsh/index.js`（read-side 注入一次）
- 文档：`integrations/skill/SKILL.md`、安装副本 `~/.agents/skills/lclone-memory/SKILL.md`
- Spec：`dsh-web-dashboard`（`会话开始注入`）、`memory-capture`（`按环境加载记忆`）
- 行为：DSH 会话开始必定注入一次记忆（解决原「skill 只描述、未注入」的软失败）；后续不重复注入。
