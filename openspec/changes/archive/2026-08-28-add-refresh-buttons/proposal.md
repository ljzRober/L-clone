## Why

记忆工作台的数据（项目/记忆/链接/待确认数）会随会话捕获实时更新，但用户查看时需手动刷新/重进页面才能看到最新数据。为 lclone Web 面板与 dsh 看板各加一个「刷新」按钮，一键重新拉取数据，无需重载页面。

## What Changes

- **lclone Web 面板**（`lclone/web.py`）：记忆工作台工具栏在「整理」按钮前新增「刷新」按钮，`onclick="loadAll()"` 重新拉取项目/记忆/链接/待确认数并重渲染图形与树状导航。
- **dsh 看板**（`integrations/dsh/dsh/client.js`）：
  - 全屏看板顶栏在「返回会话」后新增「刷新」按钮（主色填充 + 图标，区别于 ghost），点击 reload iframe（重新加载 :8000 看板数据）并刷新健康状态指示。
  - 侧边栏入口按钮从底部 footer 挪回**导航区根**（与 task-board/ssh/技能中心同级，footer 区域在 collapsed 态 `display:none` 导致按钮不可见），并改为图标+文字的 full-width 行对齐（折叠态收敛为图标）。
  - 修复点击无反应：`ensure()` 在对话列未挂载时静默等待（不抛 `null.appendChild`），由 MutationObserver 重试，避免整包 mount 失败。
- **dsh 看板健康检测**：host 端 `/api/lclone-health` 路由保留；本次未改。

## Capabilities

- **New Capabilities**: 无
- **Modified Capabilities**:
  - `dsh-web-dashboard`：新增「看板刷新」需求（顶栏刷新按钮 reload iframe）；「侧边栏看板入口按钮」补导航区根挂载场景（修复 footer 不可见）；「全屏看板面板与对话切换」补点击无反应修复（对话列未挂载时静默等待）。
  - `web-hierarchy`：记忆工作台工具栏新增「刷新」按钮场景（loadAll 重拉数据）。

## Impact

- **代码**：`lclone/web.py`（toolbar 加按钮）、`integrations/dsh/dsh/client.js`（顶栏加按钮 + 入口挪导航区 + ensure 容错）
- **依赖**：无新增
- **行为**：刷新按钮重新拉取 + 重渲染当前视图；入口按钮在导航区可见可点；看板打开不再无反应。不影响既有编辑/整理/添加逻辑。
