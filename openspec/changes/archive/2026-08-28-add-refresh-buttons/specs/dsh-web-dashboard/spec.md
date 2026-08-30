# dsh-web-dashboard Specification

## MODIFIED Requirements

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

## ADDED Requirements

### Requirement: 看板刷新

lclone-memory-dsh SHALL 在全屏看板顶栏提供主色「刷新」按钮（带图标），点击后重新加载看板 iframe（重新拉取 :8000 记忆工作台数据）并刷新健康状态指示。

#### Scenario: 点击刷新

WHEN 点击看板顶栏「刷新」按钮
THEN iframe 重新加载 :8000 看板数据，健康状态指示同步刷新

#### Scenario: 离线时刷新

WHEN 看板离线（:8000 未启动）且点击刷新
THEN 重新探测健康状态并保持离线提示（不残留旧空白 iframe）
