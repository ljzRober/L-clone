# lclone-memory-dsh（DSH 插件：L-clone 记忆钩子 + 大脑看板）

让 [L-clone 外置大脑](https://github.com/ljzRober/L-clone) 在 DeepSeek Harness (DSH) 里自动工作。**自包含**：下载本包即带全套 L-clone 大脑源码 + 前端，无需另装大脑。

- **写侧（每轮自动 capture）**：DSH `turn/end` 把本轮「用户 + 助手」文本 **POST 到后端 `/api/capture`**，提炼为洞察（进草稿待确认）；
- **读侧（会话开始注入）**：会话首轮 **GET 后端 `/api/bootstrap`** 取记忆文本 + 本包 skill 全文，注入上下文；
- **「大脑看板」**：插件 **serve 包内前端**（前后台分离），并设 `LCLONE_API_BASE=后端地址`（CORS 跨域），一键打开记忆工作台。

> 前后台分离：前端（`brain/lclone/frontend/*.html`）是独立静态资源；后端（REST/MCP，`lclone web`）只做 API。插件 serve 前端、直连后端 API。

---

## 前置：让 L-clone 后端跑起来

插件**只连后端**（不走本机 `lclone` 命令、无需 `LCLONE_CMD`）。所以先保证后端（记忆服务）起来。

**一键初始化（推荐，含建 venv + 装依赖 + 配模型 + 可启后端）**：
```bash
node <本包>/scripts/install.js          # 建 ~/.lclone/venv + 装依赖 + 配模型
# 可选：env LCLONE_INSTALL_START=1 时直接后台常驻后端
```
配模型用的 env（有则写进 `~/.lclone/.env`）：`OPENAI_API_KEY` / `BRAIN_BASE_URL` / `BRAIN_CHAT_MODEL` / `BRAIN_EMBED_MODEL` / `BRAIN_LLM`。

或手动：`python -m lclone web`（后台常驻 `lclone serve start`）；配模型 `python -m lclone setup`。

> 没有 env 时 `install.js` 会提示用 `python -m lclone setup` 交互式配模型。

---

## 安装（npm，一行）

```bash
dsh plugin --profile web add lclone-memory-dsh -w
```
> 末尾 `-w` 必须加（pnpm workspace 根）。`dsh plugin add` 透传 pnpm，按你 `.npmrc` 的 registry 解析。
> 装完**重启 DSH web 会话**。

### 从源码/本地开发装
```bash
dsh plugin --profile web add /path/to/L-clone/integrations/dsh -w
```

---

## 配置（环境变量）

| 变量 | 默认 | 说明 |
|---|---|---|
| `LCLONE_WEB_URL` | `http://127.0.0.1:8000` | 后端基址（capture/bootstrap/看板 CORS 都指向它）；部署到服务器时设为服务器地址 |
| `LCLONE_DOCS_URL` | `https://github.com/ljzRober/L-clone` | 「查看使用文档」链接 |
| `LCLONE_API_KEY` | — | 后端鉴权（设了后请求带 `X-API-Key`） |
| `LCLONE_HOME` | `~` | skill 查找家目录（`~/.agents/skills/lclone-memory/SKILL.md`） |
| `LCLONE_STATE_DIR` | `~/.lclone` | 插件日志等状态目录 |

> 后端模型配置用 lclone 自身的 env（`OPENAI_API_KEY`/`BRAIN_BASE_URL` 等，见 `lclone setup`），不经过插件。

---

## 首次运行 / 就绪引导

- **看板**检测到后端未达/skill 缺失时，显示**就绪清单**（"要跑起来还差这几步"）并附命令；
- **会话首轮**若后端不可达，注入一条提示（`node <包>/scripts/install.js` 或 `python -m lclone web`）；
- 后端自检：`python -m lclone doctor`。

## 事件（dsh-session 已确认）

```js
ctx.on('session/event', (session, event) => { ... })   // (session, event)
```
| event.type | 时机 | data |
|---|---|---|
| `turn/end` | 每轮结束 | `{ turn, reason }` |
| `user/message` | 用户消息 | `{ content:[{type:'text',text}], role }` |
| `assistant/message` | 模型消息 | `{ message:{content:[{type:'text'|'reasoning',text}]}, turn, step }` |

## 参考

- bundle 格式照 `~/.dsh/plugins/superdesign-skill-src/`：`package.json` 的 `dsh.bundle.patch` + `dsh/index.js`(导出 `name`/`apply`) + `dsh/cordis.patch.yml`。
- client 面（双面包）照 `dshmarket` / `@linxin666/dsh-client-ui-task-board`：`exports["./client"]` + `dsh.client` 声明 + `window.__ModuleLoader__.load`。
- 官方先例 `@deepseek-ai/dsh-session-telemetry` 用 `ctx.on("session/event", ...)`。
