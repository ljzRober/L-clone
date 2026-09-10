## MODIFIED Requirements

### Requirement: API key 鉴权

lclone SHALL 支持两种凭证：`LCLONE_API_KEY` 环境变量与库中受管 token。当设置了 `LCLONE_API_KEY` 或库中存在至少一个未吊销 token 时，`/api/*` 与 `/mcp` 需带有效凭证（`Authorization: Bearer <key>` 或 `X-API-Key: <key>`）。

#### Scenario: 未设置 key

WHEN 未设置 `LCLONE_API_KEY` 且库中无任何 token
THEN 本地请求免鉴权（向后兼容）

#### Scenario: 缺少凭证

WHEN 已启用鉴权（设置了 `LCLONE_API_KEY` 或库中存在未吊销 token）且请求不带凭证
THEN 返回 401

#### Scenario: 凭证有效

WHEN 已启用鉴权且请求带正确的 `LCLONE_API_KEY`（`Bearer` 或 `X-API-Key`）
THEN 放行并返回正常响应

#### Scenario: 受管 token 有效

WHEN 已启用鉴权且请求带一个未吊销的受管 token
THEN 放行并返回正常响应，且更新该 token 的最后使用时间

#### Scenario: 受管 token 已吊销

WHEN 请求带一个 `revoked_at` 非空的受管 token
THEN 返回 401

## ADDED Requirements

### Requirement: Token 管理

lclone SHALL 支持按名称创建多把访问 token；token 只以 `sha256` 哈希入库，明文仅在创建时输出一次；并支持列出与吊销。

#### Scenario: 创建 token

WHEN 运行 `lclone auth create <name>`
THEN 生成随机 token、入库其 `sha256` 哈希，并仅本次打印明文 token

#### Scenario: 列出 token

WHEN 运行 `lclone auth list`
THEN 输出每条 token 的 id / name / created_at / last_used_at / 是否已吊销，且不显示明文

#### Scenario: 吊销 token

WHEN 运行 `lclone auth revoke <name>`（或 `--id <N>`）
THEN 将该 token 标记为已吊销（不物理删除），其后续使用返回 401

#### Scenario: 鉴权冒烟测试

WHEN 运行 `lclone auth test <url> --token <tok>`
THEN 带该凭证请求 `<url>/api/health`；凭证有效时报告通过，无效时报告失败（401）
