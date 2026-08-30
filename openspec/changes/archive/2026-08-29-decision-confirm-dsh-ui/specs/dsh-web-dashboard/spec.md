# dsh-web-dashboard Delta

## MODIFIED Requirements

### Requirement: 安装与加载

lclone-memory-dsh SHALL 保持单一 npm 包双面结构：host 端（dsh/index.js）保留 capture 逻辑并新增 `/api/lclone-decisions`、`/api/lclone-review` 代理路由（决策确认不再经 agent.steer），client 端（dsh/client.js）经 `package.json` 的 `exports["./client"]` 与 `dsh.client: { platform: "web" }` 声明被 dsh client-modules 扫描加载；安装方式不变（`dsh plugin --profile web add <目录>`）。

#### Scenario: client bundle 发现

WHEN dsh web 重启且 package.json 含 dsh.client 声明
THEN client-modules 扫描到该包并 serve `/plugins/lclone-memory-dsh/client.js`，页面加载后按钮出现

#### Scenario: host 逻辑不回归

WHEN 插件加载
THEN 原有每轮 capture 保留；决策确认改由客户端轮询 `/api/lclone-decisions` + `/api/lclone-review` 提交，不再用 agent.steer 劫持主 agent

## ADDED Requirements

### Requirement: 决策确认 UI

DSH 决策确认 SHALL 由客户端表达（不进主 agent）：`client.js` SHALL 轮询 host `/api/lclone-decisions` 获取待确认决策，检测到新增时以弹窗（决策内容 + 保留/删除/稍后按钮）与侧边栏角标呈现；用户点击保留/删除 SHALL 经 `/api/lclone-review` 提交（host 代理到 lclone `/api/review`），「稍后」SHALL 把该决策留作工作台 pending。

#### Scenario: 新增待确认弹窗

WHEN 客户端轮询到 id 未见过（未入 seen）的待确认决策
THEN 渲染弹窗（决策内容 + 保留/删除/稍后）+ 更新侧边栏角标计数，主 agent 不参与

#### Scenario: 保留/删除落地

WHEN 用户点击弹窗「保留」或「删除」
THEN 客户端 POST /api/lclone-review {id, action}，成功后弹窗移除该条并刷新角标

#### Scenario: 稍后留pending

WHEN 用户点击「稍后」
THEN 该决策从弹窗消失、计入 seen，留在工作台 pending 待后续确认

#### Scenario: 服务离线

WHEN /api/lclone-decisions 拉取失败（lclone web 未启动）
THEN 清空角标并隐藏弹窗，轮询继续，服务恢复后重新呈现
