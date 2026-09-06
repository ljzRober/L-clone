# @yueliudan/lclone-memory-dsh（DSH 插件：L-clone 记忆钩子 + 大脑看板）

让 [L-clone 外置大脑](https://github.com/ljzRober/L-clone) 在 DeepSeek Harness (DSH) 里自动工作。**薄插件**：本包只含 DSH 侧钩子（写侧 capture + 读侧 bootstrap + 看板 iframe）；L-clone 后端需**单独部署**（本仓库源码 / Docker），插件通过 `LCLONE_WEB_URL` 连它。

- **写侧（每轮自动 capture）**：DSH `turn/end` 把本轮「用户 + 助手」文本 **POST 到后端 `/api/capture`**，提炼为洞察（进草稿待确认）；
- **读侧（会话开始注入）**：会话首轮 **GET 后端 `/api/bootstrap`** 取记忆文本 + 本包 skill 全文，注入上下文；
- **「大脑看板」**：看板 iframe **后端面板**（后端 `lclone web` serve，前后台同源），一键打开记忆工作台。

> 前后台同源：web 面板由**后端**（`lclone web`）serve（`lclone/frontend/*.html` + API 同源）；插件只做**写侧 capture + 读侧 bootstrap** 钩子，看板按钮直接 iframe `LCLONE_WEB_URL`，无需插件内嵌前端/注入 `LCLONE_API_BASE`/跨域。

---

## 前置：单独部署 L-clone 后端

插件**只连后端**（不走本机 `lclone` 命令、无需 `LCLONE_CMD`、不带后端源码）。所以请**先单独部署** L-clone 后端（记忆服务）：

- **源码 / 宿主机**：克隆本仓库 → `python -m venv .venv` → `pip install -r requirements.txt` → `.env` 配置模型（`OPENAI_API_KEY`/`BRAIN_BASE_URL`/`BRAIN_CHAT_MODEL` 等，或 `python -m lclone setup`）→ `python -m lclone web`（后台常驻 `lclone serve start`）。
- **Docker**：`docker compose up -d`（数据在 volume `./data:/data`，`BRAIN_DB_PATH=/data/lclone.db`）。

后端起来后，插件用 `LCLONE_WEB_URL`（默认 `http://127.0.0.1:8000`）连它。

---

## 安装（npm，一行）

```bash
dsh plugin --profile web add @yueliudan/lclone-memory-dsh -w
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
| `LCLONE_WEB_URL` | `http://127.0.0.1:8000` | 后端基址（capture/bootstrap + 看板 iframe 都指向它）；部署到服务器时设为服务器地址 |
| `LCLONE_DOCS_URL` | `https://github.com/ljzRober/L-clone` | 「查看使用文档」链接 |
| `LCLONE_API_KEY` | — | 后端鉴权（设了后请求带 `X-API-Key`） |
| `LCLONE_HOME` | `~` | skill 查找家目录（`~/.agents/skills/lclone-memory/SKILL.md`） |
| `LCLONE_STATE_DIR` | `~/.lclone` | 插件日志等状态目录 |

> 后端模型配置用 lclone 自身的 env（`OPENAI_API_KEY`/`BRAIN_BASE_URL` 等，见 `lclone setup`），不经过插件。

---

## 首次运行 / 就绪引导

- **看板**检测到后端未达/skill 缺失时，显示**就绪清单**（"要跑起来还差这几步"）并附命令；
- **会话首轮**若后端不可达，注入一条提示（`python -m lclone web`）；
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
