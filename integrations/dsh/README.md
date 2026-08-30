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
dsh plugin --profile web add /Users/didi/github/L-clone/integrations/dsh
```

- 也可以 `dsh plugin --profile web add github:<你的仓库>` 从远端装。
- 装完重启 DSH web 会话即生效。
- 插件是 symlink 链入仓库：改 host/client 代码后只需**重启 dsh web**（`lsof -ti :3080 | xargs kill; sleep 1; dsh web`），无需重新 add。

## 配置

- `LCLONE_CMD` 环境变量覆盖 lclone 命令，默认 `lclone`（需在 PATH 上）。
  - 若 lclone 不在 PATH，设 `LCLONE_CMD="/Users/didi/github/L-clone/.venv/bin/python -m lclone"`。
- 读侧（bootstrap 注入 charter+全局记忆）由 `integrations/skill/SKILL.md` 的软触发兜底；本插件专管写侧（capture）的硬触发。
- 看板依赖 lclone Web 服务（`python -m lclone web`，:8000）；未启动时看板顶栏显示离线提示而非白屏。若设置了 `LCLONE_API_KEY`，host 端健康探测自动携带凭证。

## 参考

- 插件 bundle 格式照 `~/.dsh/plugins/superdesign-skill-src/`（dsh-market 里已装的 superdesign 插件）—— `package.json` 的 `dsh.bundle.patch` + `dsh/index.js`(导出 `name`/`apply`) + `dsh/cordis.patch.yml`(insert 一行)。
- client 面（双面包）格式照 `dshmarket` / `@linxin666/dsh-client-ui-task-board`：`exports["./client"]` + `dsh.client: { platform: "web", inject }` 声明 + `window.__ModuleLoader__.load({ id, factory })` bundle；侧边栏按钮 DOM 注入与面板切换照 task-board，面板互斥照 `dsh-panel-activate` 协议。
- 官方先例 `@deepseek-ai/dsh-session-telemetry` 就是 `ctx.on("session/event", (session, event) => ...)` 订阅会话事件流的。
