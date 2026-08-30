## Why

L-clone 的记忆沉淀（capture）已由 dsh 插件在后台自动完成，但用户**只能通过 CLI 或独立浏览器打开 :8000 才能查看记忆工作台**——对话过程中想看一眼"大脑记住了什么、有哪些待确认决策"，必须切出 dsh GUI。dsh 生态已具备成熟的客户端 UI 插件机制（task-board / remote-web-ui 等先例），可以让 lclone-memory-dsh 插件补一个 client 面：在 dsh Web GUI 侧边栏提供一个「大脑看板」按钮，点击即在 GUI 内全屏打开记忆工作台，看完一键返回对话，全程不离开当前工作上下文。

## What Changes

- **新增** `integrations/dsh/dsh/client.js`：dsh 客户端 UI bundle（`window.__ModuleLoader__.load` 格式），实现：
  - 侧边栏导航区注入「大脑看板」按钮（task-board 同款 DOM 注入 + MutationObserver 自愈，New Session 按钮下方，图标 + 文字，折叠 rail 态只显图标）
  - 点击 → 中心对话列切换为全屏 iframe 看板（嵌入 `http://127.0.0.1:8000`，lclone 记忆工作台全功能）；再次点击或点「← 返回会话」回到对话（CSS data-attribute 切换，对话子树保持挂载不丢状态）
  - 与其他面板（task-board / ssh）通过 `dsh-panel-activate` 事件互斥
  - 健康状态：面板加载前探测 lclone 服务在线/离线，离线时给出启动提示而非白屏
- **修改** `integrations/dsh/package.json`：新增 `exports["./client"]` 与 `dsh.client: { platform: "web", inject: [] }` 声明（client bundle 发现机制，参照 dshmarket / skin-center 先例）
- **修改** `integrations/dsh/dsh/index.js`：保留现有 capture/决策强确认逻辑不变，追加 `webServer.register` 注册 `GET /api/lclone-health` 健康检查路由（探测 :8000 存活，供 client 端面板显示在线状态）
- **修改** `integrations/dsh/dsh/cordis.patch.yml`：无需改动（现有 insert 行已覆盖）

## Capabilities

- **New Capabilities**: `dsh-web-dashboard`
  - 侧边栏看板入口按钮
  - 全屏看板面板与对话切换
  - 面板互斥与健康状态
- **Modified Capabilities**: 无（不改 capture/决策强确认等既有 spec 行为；`web-hierarchy` 是 lclone :8000 面板自身的层级，本次只是从 dsh GUI 嵌入展示，不改变其需求）

## Impact

- **代码**：`integrations/dsh/`（package.json / dsh/index.js / dsh/client.js 新增）
- **依赖**：无新增 npm 依赖（client bundle 纯原生 DOM，不引 React，避免给服务端进程塞前端依赖）
- **运行**：需 lclone Web 服务（`python -m lclone web`，:8000）在运行；dsh web profile 重装插件 + 重启生效
- **spec**：新增 `openspec/specs/dsh-web-dashboard/spec.md`（archive 后落库）
