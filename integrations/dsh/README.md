# DSH 插件（L-clone 记忆钩子）

DSH 的插件有两种装法：

- **静态 bundle（本目录，推荐）**：npm 包 + `dsh/index.js` + `dsh/cordis.patch.yml`，用 `dsh plugin add` 安装，**标准模式直接生效，不用切预设**。
- 动态插件（`cordis_define`/`cordis_run`）：临时、进程级，需创造模式——不是我们要的。

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

## 配置

- `LCLONE_CMD` 环境变量覆盖 lclone 命令，默认 `lclone`（需在 PATH 上）。
  - 若 lclone 不在 PATH，设 `LCLONE_CMD="/Users/didi/github/L-clone/.venv/bin/python -m lclone"`。
- 读侧（bootstrap 注入 charter+全局记忆）由 `integrations/skill/SKILL.md` 的软触发兜底；本插件专管写侧（capture）的硬触发。

## 参考

- 插件 bundle 格式照 `~/.dsh/plugins/superdesign-skill-src/`（dsh-market 里已装的 superdesign 插件）—— `package.json` 的 `dsh.bundle.patch` + `dsh/index.js`(导出 `name`/`apply`) + `dsh/cordis.patch.yml`(insert 一行)。
- 官方先例 `@deepseek-ai/dsh-session-telemetry` 就是 `ctx.on("session/event", (session, event) => ...)` 订阅会话事件流的。
