# dsh-web-dashboard Specification

## Purpose
lclone-memory-dsh 插件在 dsh Web GUI 侧边栏提供「大脑看板」按钮，点击后于对话中心区全屏打开 L-clone 记忆工作台（iframe 嵌入 :8000 Web 面板），支持一键返回对话，并与其他面板互斥、显示服务在线状态。

## ADDED Requirements

### Requirement: 侧边栏看板入口按钮

lclone-memory-dsh SHALL 在 dsh Web GUI 侧边栏底部 footer 区（settings 按钮同排、remote-web-ui 入口旁）注入「大脑看板」入口按钮，compact 仅图标形态，点击切换看板开合。

#### Scenario: 按钮出现

WHEN dsh web 页面加载且 lclone-memory-dsh client bundle 生效
THEN 侧边栏底部 footer（设置按钮同排）出现「大脑看板」图标按钮，样式复用 dsh 主题变量，深浅色模式自适应

#### Scenario: 紧凑图标形态

WHEN 侧边栏展开或折叠
THEN 按钮保持 36×36 紧凑图标形态，不显示文字，不占额外行距

#### Scenario: 自愈重挂

WHEN 页面 React 重新渲染导致注入的按钮被移除
THEN MutationObserver 检测到后自动重新插入按钮，不重复创建

### Requirement: 全屏看板面板与对话切换

点击看板按钮后，lclone-memory-dsh SHALL 将对话中心列切换为全屏看板面板（iframe 嵌入 lclone Web 面板 `http://127.0.0.1:8000`），看板顶部提供「← 返回会话」按钮与标题栏；切换使用 CSS data-attribute 控制，对话子树保持挂载不丢失状态。

#### Scenario: 打开看板

WHEN 点击「大脑看板」按钮
THEN 中心对话列切换为全屏 iframe 看板（lclone 记忆工作台），对话内容隐藏但保持挂载；看板容器铺满对话区（对话列 SHALL 建立 position:relative 定位上下文，避免 absolute 容器塌陷显示为空白）

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

lclone-memory-dsh SHALL 保持单一 npm 包双面结构：host 端（dsh/index.js）保留 capture/决策强确认逻辑，client 端（dsh/client.js）经 `package.json` 的 `exports["./client"]` 与 `dsh.client: { platform: "web" }` 声明被 dsh client-modules 扫描加载；安装方式不变（`dsh plugin --profile web add <目录>`）。

#### Scenario: client bundle 发现

WHEN dsh web 重启且 package.json 含 dsh.client 声明
THEN client-modules 扫描到该包并 serve `/plugins/lclone-memory-dsh/client.js`，页面加载后按钮出现

#### Scenario: host 逻辑不回归

WHEN 插件加载
THEN 原有每轮 capture 与待确认决策 steer 提醒行为保持不变
