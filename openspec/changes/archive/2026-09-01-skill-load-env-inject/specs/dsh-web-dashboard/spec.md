## ADDED Requirements

### Requirement: 会话开始加载 skill

lclone-memory-dsh SHALL 在插件加载时注册 lclone-memory 全量 skill（`ctx.skills.registerProvider`，读取已安装的 `~/.agents/skills/lclone-memory/SKILL.md`），保证该 skill 完整在场；插件 SHALL 不再在会话开始直接运行 bootstrap 注入记忆。记忆注入由 agent 依 lclone-memory skill 规则，按当前环境（cwd 是否落进已知项目）决定加载【全局记忆】还是【全局+项目记忆】。host 端 SHALL 声明 `inject=['skills']`。

#### Scenario: 注册全量 skill

WHEN 插件加载
THEN 通过 ctx.skills.registerProvider 注册 lclone-memory skill（读已安装 SKILL.md），skill 完整在场可被 agent 全量加载

#### Scenario: 不再注入记忆

WHEN 会话开始
THEN 插件不再直接运行 bootstrap/steer 注入记忆；记忆注入由 agent 依 skill 按环境决定

#### Scenario: 注册失败静默

WHEN 无法读取已安装 SKILL.md 或 registerProvider 抛错
THEN 静默记日志，不中断插件其余功能（capture / web 路由）

## REMOVED Requirements

### Requirement: 会话开始注入
**Reason**: read-side 改为"插件加载全量 skill + agent 依 skill 按环境注入"，不再由插件直接运行 bootstrap/steer 注入记忆。
**Migration**: 记忆注入交由 lclone-memory skill；`bootstrap` 新增 `--cwd` 环境判定。

## MODIFIED Requirements

### Requirement: 决策确认 UI

DSH 洞察确认 SHALL 由客户端表达（不进主 agent）：`client.js` SHALL 轮询 host `/api/lclone-decisions` 获取待确认洞察，检测到新增时以弹窗（洞察内容 + 保留/删除/稍后按钮）与侧边栏角标呈现；**若为项目级待确认洞察，弹窗 SHALL 额外提供「提升到全局」按钮**（一步：提升到全局层 project_id=NULL 并确认落地 status=active）。用户点击保留/删除/提升到全局 SHALL 经 `/api/lclone-review` 提交（host 代理到 lclone `/api/review`），「稍后」SHALL 把该洞察留作工作台 pending。

#### Scenario: 新增待确认弹窗

WHEN 客户端轮询到 id 未见过（未入 seen）的待确认洞察
THEN 渲染弹窗（洞察内容 + 保留/删除/稍后）+ 更新侧边栏角标计数，主 agent 不参与

#### Scenario: 保留/删除落地

WHEN 用户点击弹窗「保留」或「删除」
THEN 客户端 POST /api/lclone-review {id, action}，成功后弹窗移除该条并刷新角标

#### Scenario: 提升到全局落地

WHEN 用户点击项目级待确认洞察的「提升到全局」
THEN 客户端 POST /api/lclone-review {id, action:'promote'}，后端把该洞察提升到全局层(project_id=NULL)并确认落地(active)；弹窗移除该条并刷新角标

#### Scenario: 稍后留pending

WHEN 用户点击「稍后」
THEN 该洞察从弹窗消失、计入 seen，留在工作台 pending 待后续确认

#### Scenario: 服务离线

WHEN /api/lclone-decisions 拉取失败（lclone web 未启动）
THEN 清空角标并隐藏弹窗，轮询继续，服务恢复后重新呈现
