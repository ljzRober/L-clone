## Why

lclone 未来要部署在服务器上供远程 agent 使用。当前有两个缺口：MCP 服务器只有 stdio 传输（远程 Claude Code/Codex/DSH 连不上），且 REST/MCP 都没有鉴权（服务器上任何人都能读写记忆）。Docker 化已具备（Dockerfile + docker-compose 已跑 web.py REST + /data 持久化）。

本次做「最小可用服务化」：MCP 走 HTTP + API key 鉴权。存储暂用 SQLite（服务端单进程独占）。

## What Changes

- **鉴权**：新增 `lclone/auth.py`，读 `LCLONE_API_KEY`；设了则 `/api/*`、`/mcp` 必须带 `Authorization: Bearer <key>` 或 `X-API-Key: <key>`，不设则本地免鉴权（向后兼容）。
- **MCP 分发函数化**：`mcp_server.py` 抽出 `handle_message(msg)` 纯函数（initialize/tools/list/tools/call/ping），stdio 循环与 HTTP 共用，不再绑死 stdin/stdout。
- **MCP over HTTP**：`web.py` 挂 `POST /mcp` 端点（JSON-RPC over HTTP），复用 `handle_message`，返回 JSON。
- **鉴权中间件**：`web.py` 加 FastAPI 中间件，对 `/api/*`、`/mcp` 统一鉴权。

## Capabilities

- **New Capabilities**:
  - `cli-onboarding`：无变更
  - 新增 `server-api`：MCP over HTTP + API key 鉴权（本次新增 spec）
- **Modified Capabilities**: 无

## 方案

### 文件变更

- 新增 `lclone/auth.py`：`api_key()` 读配置 + `check(headers)` 校验 + `auth_middleware()` 中间件
- 改 `lclone/mcp_server.py`：抽 `handle_message(msg) -> dict|None`，`main()` 变薄循环
- 改 `lclone/web.py`：`create_app()` 挂 `POST /mcp` + 加鉴权中间件
- 改 `docs/DEPLOYMENT.md`、`docs/WEB.md`
- 改 `tests/test_offline.py`：补 handle_message 分发 + 鉴权(带/不带 key) 断言

### 关键设计

- **鉴权只在设了 `LCLONE_API_KEY` 时启用**：本地/单机不设 key，行为不变（向后兼容）；服务器设 key，强制鉴权。
- **MCP 用 JSON-RPC over HTTP**：`POST /mcp` 解析 body → `handle_message` → JSON 响应；通知类（无 id）返回 202。覆盖 tools/list + tools/call 即满足远程 agent 基本用法。
- **不引入第三方依赖**：沿用 lclone 零依赖哲学，手写最小 MCP HTTP（不引入 `mcp` SDK）。

## Spec Constraints

- 不改 `web-hierarchy`（Web UI 交互不变）与 `cli-onboarding`（CLI 不变）。
- 鉴权默认关闭，本地行为等价。

## Impact

- 文件：新增 `auth.py`，改 `mcp_server.py`/`web.py`/`docs`/`tests`
- 依赖：无新增
- 测试：`tests/test_offline.py` 全绿 + 补 MCP 分发/鉴权断言
