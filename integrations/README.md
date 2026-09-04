# integrations — 各端接入（下载与使用）

本目录是 L-clone 到各 AI 工具的**触发胶水层**（生命周期点 → 调 lclone），零业务逻辑。记忆引擎在 `lclone/`。

| 目录 | 环境 | 接入方式 | 生命周期 |
|---|---|---|---|
| `claude-code/` | Claude Code | hooks | SessionStart→`bootstrap`；Stop→`capture` |
| `codex/` | OpenAI Codex CLI | hooks + AGENTS.md | SessionStart→`bootstrap`；Stop→`capture` |
| `dsh/` | DeepSeek Harness | 插件（自包含/后端驱动） | 会话首轮→记忆注入；轮结束→`capture`(走后端 HTTP) |
| `skill/` | 任意支持 skill 的环境 | 指令注入（软兜底） | 会话开始→`bootstrap`；对话中→`capture` |

---

## 通用前提

先让 lclone 大脑就绪。两种装法：
- **A. 装 lclone（pip，Claude/Codex 必需）**：`pip install lclone`（或仓库 `pip install -e .`）。
- **B. DSH 自包含插件（新，免装大脑）**：插件自带大脑 + `scripts/install.js`。

装好后配置模型：`lclone setup`（选 provider + 填 key → `.env` + 初始化库）。

---

## DSH（DeepSeek Harness）

**方式 1 — 已装 lclone（常规）**
```bash
lclone setup                         # 配置模型后端
lclone web                           # 起后端(浏览器看板 + 插件走 HTTP)
lclone integrate --target dsh        # 装 skill + 提示如下
# → dsh plugin --profile web add <路径>/integrations/dsh -w
dsh plugin --profile web add /路径/integrations/dsh -w
# 设 LCLONE_WEB_URL=http://127.0.0.1:8000(或服务器地址)，重启 DSH web
```

**方式 2 — 自包含（发布后，免装大脑）**
```bash
dsh plugin --profile web add lclone-memory-dsh -w
node <包>/scripts/install.js         # 建 venv+装依赖+配模型+可启后端
# 设 LCLONE_WEB_URL=<后端地址>，重启 DSH web
```
> DSH 插件**走后端 HTTP**（`/api/capture`、`/api/bootstrap`），无需本机 `lclone`/`LCLONE_CMD`；**后台 web 必须跑着**。

## Claude Code

```bash
lclone setup
lclone integrate --target claude     # 装 skill + 合并 hooks → ~/.claude/settings.json
```
- hooks 自动：会话开始 `bootstrap`、结束 `capture`；用到的 `lclone` 在 PATH（或仓库 `.venv`）。
- **后台 web 不必起**（hooks 走 CLI 直接写库）；要浏览记忆才 `lclone web`。

## Codex (OpenAI Codex CLI)

```bash
lclone setup
lclone integrate --target codex      # 装 skill + 合并 hooks → ~/.codex/hooks.json
# 再把 integrations/codex/AGENTS.md 内容追加到仓库 AGENTS.md(记忆规则)
```
- hooks: SessionStart→`bootstrap`、Stop→`capture`；AGENTS.md 指导 agent 记忆行为。

---

## 各端对比

| 端 | 需要 lclone 大脑 | 连接方式 | 后台 web 必需? | 接入命令 |
|---|---|---|---|---|
| **Claude Code** | 是（pip） | hooks（CLI） | 否（浏览才要） | `lclone integrate --target claude` |
| **Codex** | 是（pip） | hooks + AGENTS.md | 否 | `lclone integrate --target codex` |
| **DSH** | 方式1 是 / 方式2 插件自带 | 插件 → 后端 HTTP | **是** | `lclone integrate --target dsh` 或 `dsh plugin add lclone-memory-dsh` |

## 自检

装完任一端：`lclone doctor`（后端 + 集成分段自检）。要可视化看板/改记忆：浏览器开 `lclone web`（部署到服务器时开服务器域名，`LCLONE_WEB_URL` 指向它）。

> 路径占位：示例用 `/Users/didi/github/L-clone`，实际按你的安装路径替换。
