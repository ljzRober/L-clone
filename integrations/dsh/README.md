# DSH 插件（L-clone 记忆钩子 + 大脑看板）

DSH 的插件有两种装法：

- **静态 bundle（本目录，推荐）**：npm 包 + `dsh/index.js`（host）+ `dsh/client.js`（浏览器 UI）+ `dsh/cordis.patch.yml`，用 `dsh plugin add` 安装，**标准模式直接生效，不用切预设**。
- 动态插件（`cordis_define`/`cordis_run`）：临时、进程级，需创造模式——不是我们要的。

本插件是**双面包**：host 端 `dsh/index.js` 订阅会话事件做记忆捕获；client 端 `dsh/client.js`（经 `package.json` 的 `dsh.client` 声明被 dsh client-modules 扫描加载）在 Web GUI 侧边栏注入「大脑看板」按钮，点击在对话中心区全屏打开 L-clone 记忆工作台（iframe :8000），顶栏显示服务在线状态，支持一键返回会话并与 task-board/ssh 面板互斥。

## 已确认的事件（从 dsh-session 源码 + 官方 dsh-session-telemetry 包核实）

```js
ctx.on('session/event', (session, event) => { ... })   // 注意是 (session, event) 两个参数
```

| event.type | 时机 | event.data |
|---|---|---|
| `turn/end` | **每轮结束** | `{ turn, reason }` |
| `user/message` | 用户消息 | `{ content: [{type:'text', text}], role }` |
| `assistant/message` | 模型消息 | `{ message: { content: [{type:'text'|'reasoning', text}] }, turn, step }` |

本插件在 `dsh/index.js` 里：按 session 累计每轮的 user+assistant 文本 → `turn/end` 时调 `lclone capture` 沉淀为草稿。

## 安装（标准模式，一行）

```bash
dsh plugin --profile web add /Users/didi/github/L-clone/integrations/dsh -w
```

> 末尾的 `-w` 必须加：`dsh plugin add` 是 pnpm 的薄转发，profile 目录是 pnpm workspace 根，
> 新版 pnpm 会拒绝在根上 `add`（`ERR_PNPM_ADDING_TO_ROOT`），`-w` 显式声明"就装到根"。

- 也可以 `dsh plugin --profile web add github:<你的仓库> -w` 从远端装。
- 装完重启 DSH web 会话即生效。
- 插件是 symlink 链入仓库：改 host/client 代码后只需**重启 dsh web**（`lsof -ti :3080 | xargs kill; sleep 1; dsh web`），无需重新 add。

## 配置

- `LCLONE_CMD` 环境变量覆盖 lclone 命令。默认自动定位仓库 `.venv` 里的 python（Windows 用 `Scripts/python.exe`、Unix 用 `bin/python`），都找不到再退回 PATH 上的 `lclone`。
- **后台地址可配置**：`LCLONE_WEB_URL` 指定后端基址（默认 `http://127.0.0.1:8000`）。本地留空；部署到服务器时设为服务器地址 host 端健康探测/决策代理与 client 端看板 iframe 都指向它。
- **文档链接可配置**：`LCLONE_DOCS_URL`（默认 `https://github.com/ljzRober/L-clone`）。
- 若设置了 `LCLONE_API_KEY`，host 端请求后端自动带 `X-API-Key`。
- **本插件做前端展示 + 写侧捕获 + 会话开始注入，不负责启动后台/装 skill**（后台与 skill 需你自行就绪）：
  - 后台服务没起时，看板显示默认内容并提示「请先运行 `python -m lclone web`（或 `lclone serve start` 后台常驻）」+ 文档链接；
  - skill 缺失时，看板提示「请运行 `lclone integrate --target skill`」。
- 读侧（bootstrap 注入 charter+全局记忆）由本插件在会话首轮经 `agent.steer` **硬触发**（每会话一次）；lclone-memory skill 作兜底（agent 调 `bootstrap`）。写侧（capture）由插件在 `turn/end` **硬触发**。
- 看板依赖 lclone Web 服务（后端 `LCLONE_WEB_URL`）；未启动时看板显示默认提示而非白屏。

## 参考

- 插件 bundle 格式照 `~/.dsh/plugins/superdesign-skill-src/`（dsh-market 里已装的 superdesign 插件）—— `package.json` 的 `dsh.bundle.patch` + `dsh/index.js`(导出 `name`/`apply`) + `dsh/cordis.patch.yml`(insert 一行)。
- client 面（双面包）格式照 `dshmarket` / `@linxin666/dsh-client-ui-task-board`：`exports["./client"]` + `dsh.client: { platform: "web", inject }` 声明 + `window.__ModuleLoader__.load({ id, factory })` bundle；侧边栏按钮 DOM 注入与面板切换照 task-board，面板互斥照 `dsh-panel-activate` 协议。
- 官方先例 `@deepseek-ai/dsh-session-telemetry` 就是 `ctx.on("session/event", (session, event) => ...)` 订阅会话事件流的。
