## ADDED Requirements

### Requirement: MCP over HTTP

lclone SHALL 在 Web 服务上暴露 `POST /mcp` 端点，用 JSON-RPC over HTTP 提供与 stdio 相同的工具集。

#### Scenario: 列出工具

WHEN 客户端 `POST /mcp` 发 `tools/list`
THEN 返回 JSON-RPC 响应，含 10 个工具（bootstrap/capture/recall/remember/promote/demote/suggest/projects/review/ask）

#### Scenario: 调用工具

WHEN 客户端 `POST /mcp` 发 `tools/call`
THEN 复用 stdio 的分发逻辑执行工具并返回结果

#### Scenario: 通知类消息

WHEN 客户端 POST 无 `id` 的通知消息
THEN 返回 202 空响应

### Requirement: API key 鉴权

lclone SHALL 支持 `LCLONE_API_KEY` 环境变量；设置后 `/api/*` 与 `/mcp` 需带 `Authorization: Bearer <key>` 或 `X-API-Key: <key>`。

#### Scenario: 未设置 key

WHEN 未设置 `LCLONE_API_KEY`
THEN 本地请求免鉴权（向后兼容）

#### Scenario: 缺少凭证

WHEN 设置了 `LCLONE_API_KEY` 且请求不带凭证
THEN 返回 401

#### Scenario: 凭证有效

WHEN 设置了 `LCLONE_API_KEY` 且请求带正确 `Bearer` 或 `X-API-Key`
THEN 放行并返回正常响应
