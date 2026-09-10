## Why

当前鉴权只有一把共享的 `LCLONE_API_KEY`（`.env` 明文，见 `server-api` 的「API key 鉴权」）。一把 key 泄露就得所有端全部轮换，无法按设备吊销，也无法知道哪把凭证在被使用。需要在**不破坏现有兼容**的前提下,支持"按设备发多把、可单独吊销、库里只存哈希"的 token 管理。

## What Changes

- 新增 `access_tokens` 表（`db.py` 的 `SCHEMA`，`db.init` 自动建表/迁移）：`id / name / token_hash / created_at / last_used_at / revoked_at`，**只存 `sha256(token)`，明文仅在创建时输出一次**。
- `auth.py` 校验扩展：先比 env `LCLONE_API_KEY`（向后兼容），再按 `sha256` 查未吊销 token；命中时更新 `last_used_at`。
- **强制开关**：设了 env `LCLONE_API_KEY` **或**库中已存在任何 token（含已吊销）→ 强制鉴权；两者皆无 → 免鉴权（保持既有"未设置免鉴权"场景）。一旦创建过 token，鉴权持续启用，**吊销最后一把也不会自动敞开**。
- `web.py` 鉴权中间件把 DB 连接传入校验（现中间件只读 env）。
- 新增 CLI 子命令 `auth`：`create <name>` / `list` / `revoke <name|--id N>` / `test <url> --token <tok>`。
- 文档补充：`docs/CLI.md`、`README(.zh-CN).md`、`docs/DEPLOYMENT.md` 的鉴权段。
- `LCLONE_API_KEY` 仍作**引导凭证**（`scripts/deploy_server.sh` 依旧自动生成），单 key 用法完全不变（向后兼容）。

## Capabilities

### New Capabilities
（无）

### Modified Capabilities
- `server-api`：扩展「API key 鉴权」需求以接受受管 token 并调整强制触发条件；新增「Token 管理」需求（多命名 token、哈希存储、吊销、最后使用时间、CLI 管理命令）。

## Impact

- 代码：`lclone/db.py`（schema）、`lclone/auth.py`（校验）、`lclone/web.py`（中间件传 conn）、`lclone/cli.py`（`auth` 子命令）。
- 数据：新增 `access_tokens` 表；`db.init` 幂等建表，旧库无缝升级，不迁移既有数据。
- 接口：`/api/*` 与 `/mcp` 的鉴权语义扩展（新增可接受受管 token）；`LCLONE_API_KEY` 行为不变。
- 测试：`tests/test_offline.py` 增补用例。
- 不影响：模型层、记忆读写路径、前端（前端已发送 `X-API-Key`，受管 token 同样适用）。

## 方案

**数据模型**（`db.py` `SCHEMA` 追加，`db.init` 跑 `executescript(SCHEMA)` 自动建表）：
```sql
CREATE TABLE IF NOT EXISTS access_tokens (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  name         TEXT NOT NULL,
  token_hash   TEXT NOT NULL UNIQUE,      -- sha256(token) hex
  created_at   TEXT NOT NULL DEFAULT (datetime('now')),
  last_used_at TEXT,
  revoked_at   TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_tokens_hash ON access_tokens(token_hash);
```

**token 生成/存储**：`secrets.token_hex(24)` → 48 hex；对外展示为 `lclone_<48hex>`（前缀便于识别，校验时对原串做哈希）。只存 `sha256(<明文>)`。`create` 打印一次明文，之后不可再取。

**校验与强制**（`auth.py`）：
- `check(headers, conn=None)`：依次 (1) 未启用鉴权 → 通过；(2) env `LCLONE_API_KEY` 匹配 → 通过；(3) 有 conn 时按 `sha256` 查未吊销 token → 通过并更新 `last_used_at`；否则拒绝。
- `enabled(conn)`：env key 非空 **或** 库中已存在任何 token（`SELECT 1 FROM access_tokens LIMIT 1`，含已吊销）命中。
- `web.py` 中间件：用请求作用域的 DB 连接调用 `auth.enforce`（`get_db` 已提供），保持 `/api/*` 与 `/mcp` 受保护、HTML 公开。

**CLI**（`cli.py` 新增 `auth` 子命令，沿用 `_conn(args)` 开库）：
| 命令 | 行为 |
|---|---|
| `lclone auth create <name>` | 生成 token → 存哈希 → 打印明文（仅此一次） |
| `lclone auth list` | 表格：id / name / created / last_used / 状态(active/revoked) |
| `lclone auth revoke <name\|--id N>` | 置 `revoked_at`（吊销即失效，不删行） |
| `lclone auth test <url> --token <tok>` | 带凭证请求 `<url>/api/health`，报告 ✅/❌ (200/401) |

**文件**：`lclone/db.py`、`lclone/auth.py`、`lclone/web.py`、`lclone/cli.py`、`docs/CLI.md`、`README.md`、`README.zh-CN.md`、`docs/DEPLOYMENT.md`、`tests/test_offline.py`、`openspec/changes/auth-token-management/specs/server-api/spec.md`。

**测试**：create→list→revoke 全链路；库内无明文（只有哈希）；sha256 命中/未命中；受管 token 有效=200、无效/已吊销=401；env key 仍有效；无 env 无 token=免鉴权。

**不做（YAGNI）**：scopes 权限、OAuth 2.1、admin 面板、限流、审计日志、per-client 源围栏——这些是 gbrain 多租户场景才需要。

## Spec Constraints

引用已加载的 `server-api` spec 约束（实施/验证前须对照）：
- 「API key 鉴权」既有三个场景（未设置 key 免鉴权 / 缺少凭证 401 / 凭证有效放行）**必须全部保留**，不得改名或删减。
- 鉴权只作用于 `/api/*` 与 `/mcp`；HTML 页面保持公开（既有行为）。
- 凭证头支持 `Authorization: Bearer <key>` 与 `X-API-Key: <key>` 两种。
