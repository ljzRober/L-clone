# dsh-web-dashboard Specification

## Purpose
TBD - created by archiving change dsh-dashboard-button. Update Purpose after archive.
## Requirements
### Requirement: 侧边栏看板入口按钮

lclone-memory-dsh SHALL 在 dsh Web GUI 侧边栏导航区根容器（`[class*="logoRow"]` 的父元素，与 task-board/ssh/技能中心同级）注入「大脑看板」入口按钮，**展开态为图标+文字的 full-width 行，折叠态收敛为圆形小图标**，点击切换看板开合。

#### Scenario: 按钮出现

WHEN dsh web 页面加载且 lclone-memory-dsh client bundle 生效
THEN 侧边栏导航区根（技能中心旁）出现「大脑看板」入口按钮（图标+文字），与任务看板/SSH/技能中心同级对齐，样式复用 dsh 主题变量，深浅色模式自适应

#### Scenario: 紧凑图标形态

WHEN 侧边栏折叠为窄 rail
THEN 按钮收敛为仅图标的圆形小图标（label 隐藏），与 task-board/ssh/技能中心的折叠行为一致

#### Scenario: 自愈重挂

WHEN 页面 React 重新渲染导致注入的按钮被移除
THEN MutationObserver 检测到后自动重新插入按钮，不重复创建

### Requirement: 全屏看板面板与对话切换

点击看板按钮后，lclone-memory-dsh SHALL 将对话中心列切换为全屏看板面板（iframe 嵌入 lclone Web 面板 `http://127.0.0.1:8000`），看板顶部提供「← 返回会话」按钮、刷新按钮与标题栏；切换使用 CSS data-attribute 控制，对话子树保持挂载不丢失状态。

#### Scenario: 打开看板

WHEN 点击「大脑看板」按钮
THEN 中心对话列切换为全屏 iframe 看板（lclone 记忆工作台），对话内容隐藏但保持挂载；看板容器铺满对话区（对话列 SHALL 建立 position:relative 定位上下文，避免 absolute 容器塌陷显示为空白）

#### Scenario: 对话列未挂载时不报错

WHEN 页面加载早期对话列尚未挂载（querySelector 返回 null）
THEN ensure() 静默等待并由 MutationObserver 重试，不抛 null.appendChild，避免整包 mount 失败（保证点击看板始终有反应）

#### Scenario: 返回会话

WHEN 点击看板顶栏「← 返回会话」或再次点击侧边栏按钮
THEN 看板关闭，对话恢复显示且状态不丢失

#### Scenario: 点击会话行自动返回

WHEN 看板打开且用户点击侧边栏会话/项目/新建会话行
THEN 看板自动关闭，回到对话

### Requirement: 面板互斥

lclone-memory-dsh SHALL 与 dsh 其他全屏面板（task-board / ssh）通过 `dsh-panel-activate` 事件互斥：本插件面板激活时移除其他面板激活标记，其他面板激活时本插件面板自动关闭。

#### Scenario: 本面板激活互斥

WHEN 打开大脑看板
THEN 移除 ssh 等其他面板的激活标记并广播 dsh-panel-activate(lclone)，避免两面板同时显示

#### Scenario: 他面板激活互斥

WHEN task-board 或 ssh 面板激活（收到 dsh-panel-activate 且 detail 非 lclone）
THEN 大脑看板自动关闭

### Requirement: 健康状态显示

lclone-memory-dsh SHALL 通过 host 端 `/api/lclone-health` 路由探测 lclone Web 服务（:8000）存活状态，在看板顶栏显示在线/离线指示；离线时显示启动提示而非白屏。host 端探测 SHALL 在设置 `LCLONE_API_KEY` 时携带凭证。

#### Scenario: 在线状态

WHEN 点击打开看板且 :8000 服务在线（/api/health 返回 ok）
THEN 顶栏状态点为绿色「在线」，iframe 正常显示记忆工作台

#### Scenario: 离线提示

WHEN :8000 服务未启动
THEN 顶栏状态点为红色「离线」，面板显示「python -m lclone web」启动提示，不显示空白 iframe

#### Scenario: 带凭证探测

WHEN 设置了 LCLONE_API_KEY 且 host 端探测 :8000 /api/health
THEN 请求携带 X-API-Key 或 Bearer 凭证，避免 401 误判为离线

### Requirement: 安装与加载

lclone-memory-dsh SHALL 保持单一 npm 包双面结构：host 端（dsh/index.js）保留 capture 逻辑并新增 `/api/lclone-decisions`、`/api/lclone-review` 代理路由（决策确认不再经 agent.steer），client 端（dsh/client.js）经 `package.json` 的 `exports["./client"]` 与 `dsh.client: { platform: "web" }` 声明被 dsh client-modules 扫描加载；安装方式不变（`dsh plugin --profile web add <目录>`）。

#### Scenario: client bundle 发现

WHEN dsh web 重启且 package.json 含 dsh.client 声明
THEN client-modules 扫描到该包并 serve `/plugins/lclone-memory-dsh/client.js`，页面加载后按钮出现

#### Scenario: host 逻辑不回归

WHEN 插件加载
THEN 原有每轮 capture 保留；决策确认改由客户端轮询 `/api/lclone-decisions` + `/api/lclone-review` 提交，不再用 agent.steer 劫持主 agent

### Requirement: 看板刷新

lclone-memory-dsh SHALL 在全屏看板顶栏提供主色「刷新」按钮（带图标），点击后重新加载看板 iframe（重新拉取 :8000 记忆工作台数据）并刷新健康状态指示。

#### Scenario: 点击刷新

WHEN 点击看板顶栏「刷新」按钮
THEN iframe 重新加载 :8000 看板数据，健康状态指示同步刷新

#### Scenario: 离线时刷新

WHEN 看板离线（:8000 未启动）且点击刷新
THEN 重新探测健康状态并保持离线提示（不残留旧空白 iframe）

### Requirement: 决策确认 UI

DSH 洞察确认 SHALL 由客户端表达（不进主 agent）：`client.js` SHALL 轮询 host `/api/lclone-decisions` 获取待确认洞察，检测到新增时以弹窗（洞察内容 + 保留/删除/稍后按钮）与侧边栏角标呈现；**若为项目级待确认洞察，弹窗在按钮上方 SHALL 提供一个「提升至全局记忆」勾选框**（默认不勾选）。用户勾选后点「保留」→ 后端一步执行 `promote`（提升到全局层 project_id=NULL 并确认落地 status=active）；不勾选点「保留」→ 仅在项目级落地。用户点击保留/删除 SHALL 经 `/api/lclone-review` 提交（host 代理到 lclone `/api/review`），「稍后」SHALL 把该洞察留作工作台 pending。

#### Scenario: 新增待确认弹窗

WHEN 客户端轮询到 id 未见过（未入 seen）的待确认洞察
THEN 渲染弹窗（洞察内容 + 保留/删除/稍后）+ 更新侧边栏角标计数，主 agent 不参与

#### Scenario: 保留/删除落地

WHEN 用户点击弹窗「保留」或「删除」
THEN 客户端 POST /api/lclone-review {id, action}，成功后弹窗移除该条并刷新角标

#### Scenario: 提升到全局落地

WHEN 项目级待确认洞察勾选了「提升至全局记忆」并点击「保留」
THEN 客户端 POST /api/lclone-review {id, action:'promote'}，后端把该洞察提升到全局层(project_id=NULL)并确认落地(active)；弹窗移除该条并刷新角标

#### Scenario: 不勾选保留于项目级

WHEN 项目级待确认洞察未勾选「提升至全局记忆」并点击「保留」
THEN 客户端 POST /api/lclone-review {id, action:'keep'}，该洞察在项目级落地(active)，不提升到全局

#### Scenario: 稍后留pending

WHEN 用户点击「稍后」
THEN 该洞察从弹窗消失、计入 seen，留在工作台 pending 待后续确认

#### Scenario: 服务离线

WHEN /api/lclone-decisions 拉取失败（lclone web 未启动）
THEN 清空角标并隐藏弹窗，轮询继续，服务恢复后重新呈现

### Requirement: 会话开始加载 skill

lclone-memory-dsh SHALL 在插件加载时注册 lclone-memory 全量 skill（`ctx.skills.registerProvider`，读取已安装的 `~/.agents/skills/lclone-memory/SKILL.md`），并在**会话首轮**（第一个 user/message，`bootstrapped` Set 保证每会话一次）一次性运行 `lclone bootstrap --cwd <会话cwd>`，把【skill 全文】+【bootstrap 记忆】经 `agent.steer` 注入会话（完整 UserMessage 形状 + `source:{kind:'plugin'}`），**每会话仅注入一次**，不重复注入。注入内容按当前环境决定：`cwd` 落进已知项目 →【项目方向 + 项目记忆 + 全局记忆】；否则仅【全局记忆】。host 端 SHALL 声明 `inject=['skills','agents']`。skill 全文与记忆注入后主导整段会话。

#### Scenario: 注册全量 skill

WHEN 插件加载
THEN 通过 ctx.skills.registerProvider 注册 lclone-memory skill（读已安装 SKILL.md），skill 完整在场可被 agent 全量加载

#### Scenario: 不再注入记忆

WHEN 会话首轮注入完成
THEN 同一会话后续轮次不再重复注入记忆/重跑 bootstrap；每轮只 capture 记洞察

#### Scenario: 注册失败静默

WHEN 无法读取已安装 SKILL.md 或 registerProvider 抛错
THEN 静默记日志，不中断插件其余功能（capture / web 路由）

#### Scenario: 会话首轮注入一次

WHEN 会话产生第一个 user/message 且该会话未注入过
THEN 插件运行 bootstrap --cwd 并 steer 注入【skill 全文 + 记忆】；同一会话后续不再注入

#### Scenario: 项目会话注入

WHEN 会话 cwd 落进已知项目（detect_project_by_git 命中）
THEN bootstrap --cwd 注入 项目方向 + 项目记忆 + 全局记忆

#### Scenario: 全局会话注入

WHEN 会话不在已知项目（或无 cwd）
THEN bootstrap 只注入全局记忆

