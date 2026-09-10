## Why

后端（记忆库）搬到服务器后，DSH 插件的自动捕获全部掉进全局层：服务端执行 `git -C <客户端路径>` 必然失败 → `resolve_project` 返回 `no_git` → `global_fallback` 静默落全局。表现是「项目节点收不到新记忆」和「待确认弹窗没有『提升至全局记忆』勾选框」（该勾选框只在项目级条目上渲染），用户会以为记忆没存上。同时插件请求超时只有 3s，而 capture 要跑一次 LLM 提炼（实测 4s+），服务端已落库、客户端却报 fail 并丢掉 ids；看板 iframe 常驻挂载，切回来不重新拉取，新记忆要手点「刷新」才可见。

## What Changes

- 归属改在**客户端**解析：`git -C cwd rev-parse --show-toplevel` → 匹配 `/api/projects` 的 `path` → 命中即随 capture 上报 `project_id`；未注册则 `POST /api/projects` 自动注册后再归属。不再依赖服务端文件系统。
- 请求超时按路由分级：capture/bootstrap 30s、review 15s、决策轮询 8s、健康探测 4s（原统一 3s）；`onDone` 加 done 标志，timeout 与 error 不再重复回调。
- 看板每次「关→开」重新加载 iframe（首次打开仍由 `ensure()` 的 src 负责，不重复加载）。
- 大脑合流：`mcporter` 的 `lclone` 由本机 stdio 改为 **MCP over HTTP** 直连服务器 `/mcp`，与插件自动捕获、大脑看板共用同一个大脑；skill 增加「远程后端下必须显式传 `project`」规则，并把「大脑位置」改写成服务器。
- 本机已安装 skill 从旧版（note 模型）同步为仓库当前版（insight/evolution 模型）。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `memory-capture`：归属判定新增「客户端解析归属」「MCP 显式归属」场景——远程后端下不再静默落全局。
- `dsh-web-dashboard`：看板刷新新增「面板每次打开自动重新拉取」场景；新增「捕获请求超时与回调去重」需求。

## 方案

- 归属必须放在客户端：只有会话所在机器知道自己的 git 仓库根，服务端看不到客户端路径是架构固有事实。故由插件解析后把 `project_id` 一并上报——后端 `/api/capture` 已支持显式 `project_id`，**不改后端、不需重新部署服务器**。
- 未注册项目走既有 `POST /api/projects` 自动注册（名=仓库 basename）；同名冲突时按 name 复用已有项目，不重复造项目。
- 客户端仍传 `cwd`，兼容本机后端（服务端 git 判定依旧有效）：显式 `project_id` 优先。
- 超时按路由分级，避免长超时把健康探测/决策轮询一起拖住。
- 大脑合流方向：统一到服务器（用户选定），记忆留在服务器；本机 `lclone.db` 降为历史副本，本地 `.env` 仅用于离线自测。

## Spec Constraints

- `memory-capture` > 归属判定：「git 检测到仓库但未注册时 SHALL 自动注册」「无 git 时不得静默默认全局」——远程后端下由客户端承担 git 检测与注册，恢复该约束。
- `dsh-web-dashboard` > 决策确认 UI：「项目级待确认洞察 SHALL 提供『提升至全局记忆』勾选框」——归属修复后项目级条目才会出现，该场景随之重新可达。
- `dsh-web-dashboard` > 看板刷新：保留既有「刷新按钮」场景，新增「打开即重新拉取」场景。
- `server-api` > MCP over HTTP / API key 鉴权：大脑合流直接复用既有端点与凭证（`baseUrl` + `Authorization: Bearer`），不改协议、不改后端。

## Impact

- `integrations/dsh/dsh/index.js`（客户端归属解析、超时分级、回调去重）
- `integrations/dsh/dsh/client.js`（面板打开即重新拉取）
- `integrations/dsh/package.json`（0.2.2 → 0.2.3）
- `integrations/skill/SKILL.md`（远程后端归属规则 + 大脑位置）
- 本机运行时：`~/.dsh/profiles/web/node_modules/@yeliudan/lclone-memory-dsh/dsh/*.js`、`~/.agents/skills/lclone-memory/SKILL.md`、`~/.mcporter/mcporter.json`
- 服务器端代码与容器：**不改动**
