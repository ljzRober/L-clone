## Why

项目归属当前以**本地路径**为唯一身份（`projects.path` + `_match_registered` 比 resolved path 相等），同一仓库换机器、换 clone 目录就会被自动注册成第二个项目——线上已经出现三组重复（`lclone` / `L-clone`、`expressdriver-drn` / `expressdriver-drn-2`、`expressdriver-android` / `expressdriver-android-2`），并且远端大脑下读侧 `/api/bootstrap?cwd=` 走服务端 git 检测必然失败，导致项目记忆在会话首轮**一张都不注入**。同一台仓库的 remote 是稳定的、跨机器一致的，应取代路径成为身份键。

## What Changes

- `projects` 新增 `remote` 列（归一化远端地址 `host/group/repo`），沿用 `db.init` 的幂等 `ALTER TABLE ADD COLUMN` 迁移；空值表示"尚未回填"。
- 归属匹配顺序改为 **remote 精确 → path（resolved 相等 / 上报路径最长前缀）→ 自动注册**；`path` 降级为"最近一次看到的位置"（单列，后写覆盖），不再作为身份键。
- 客户端（插件 / CLI / MCP 调用方）在会话所在机器解析仓库 remote 并随请求上报；服务端不再依赖对客户端路径执行 git 检测。
- 读侧修复：`GET /api/bootstrap` 接受 `project_id` / `repo_remote`（`cwd` 保留为向后兼容回落），DSH 插件在会话首轮复用既有 `resolveProject()` 的客户端解析结果，使项目会话真正注入【项目方向】+【项目记忆】。
- 惰性回填：客户端上报 `(remote, path)` 命中 `remote` 为空的既有项目时就地写入，项目 id 不变。
- 新增只读**重复项目探测**（`lclone proj dupes` + `GET /api/projects/duplicates`，按归一化 remote 分组）。
- 新增**显式合并**能力（`lclone proj merge <src> <dst>` + `POST /api/projects/merge`）：记忆与 spec 索引改挂目标项目、源项目打墓碑，合并前产出可回滚备份。
- 种子进化资产 `会话归属与落库约定.md` 正文随归属规则同步更新（内容变更，非需求变更）。

**BREAKING**：无。`projects.path` 与既有 `cwd` 入参保留；新增列有默认值；既有 `GET /api/projects` 只追加 `remote` 字段。

## Capabilities

### New Capabilities

（无。落地在既有 `memory-capture` 与 `dsh-web-dashboard` 能力上，不引入新 capability 路径。）

### Modified Capabilities

- `memory-capture`：**修改**「归属判定」（改为 remote 优先 + remote 上报 + 惰性回填，原 5 个场景全部保留并新增 4 个）；**修改**「按环境加载记忆」（读侧改为按客户端上报的 `project_id`/`repo_remote` 加载，`cwd` 降为回落，原 3 个场景保留并新增 2 个）；**新增**「项目身份与重复探测」一条需求（remote 为身份、path 非身份、只读探测、显式合并带备份）。
- `dsh-web-dashboard`：**修改**「会话开始加载 skill」（读侧 bootstrap 改为客户端解析归属后上报 `project_id`，原 6 个场景全部保留并新增 1 个）。

## Impact

- **数据模型**：`projects` 增列 `remote`（幂等迁移，不动既有行；回填靠客户端上报惰性补齐）。合并会改 `memories.project_id` 与 `specs_index.project_id`，并写 `project_removals`。
- **后端**：`lclone/projects.py`（归一化、remote 匹配、回填、探测、合并）、`lclone/db.py`（迁移）、`lclone/web.py`（`/api/bootstrap` 入参、`/api/projects` 追加 remote、重复探测与合并端点）、`lclone/mcp_server.py`（`projects`/`capture`/`remember`/`bootstrap`/`recall` 接受并透传 remote）、`lclone/evolutions.py`（`find_project` 增加 remote 匹配）、`lclone/cli.py`（`proj dupes` / `proj merge` / 上报 remote）。
- **插件**：`integrations/dsh/dsh/index.js`（读侧 bootstrap 传 `project_id`；写侧 capture 附带 remote）。
- **种子内容**：`lclone/data/starter/evolutions/会话归属与落库约定.md`。
- **部署**：需要在服务器重建容器（`db.init` 迁移 + 新代码）；生产库回填与合并另行确认后执行。
- **不影响**：记忆准入闸门、提炼提示词、进化资产版本库、鉴权层。

## 方案

### 归一化规则（`normalize_remote`）

输入取 `git -C <cwd> remote get-url origin`，缺失则取 `git remote -v` 第一条；输出 `host/group/repo`：

1. 去协议前缀 `ssh://` / `git://` / `https://` / `http://`；
2. scp 形式 `[user@]host:path` 按 `host` + `path` 拆开；
3. 去凭据段（`user@`、`user:token@`）；
4. 去尾 `/`、去尾 `.git`；
5. host 小写，port 保留（非默认端口时拼进 host）；**path 保留大小写**（自建 GitLab 可能大小写敏感，宁可少合并也不误合并）。

无 remote → 返回空串，匹配回落 path。同一 remote 不同本地路径 → 同一项目；fork 的 remote 不同 → 视为不同项目（已确认）。

### 匹配与回填

```
resolve(cwd, remote_hint) :
  remote = normalize(remote_hint or git_remote(cwd))
  if remote and (pid := match_by_remote(remote)): return pid          # 命中
  if repo := git_toplevel(cwd):                                       # 路径兜底
      if pid := match_by_path(repo): backfill_remote(pid, remote); return pid
      return register(name=repo.basename, path=repo, remote=remote)
  return no_git
```

`path` 单列、后写覆盖（本 change 明确取舍：多机下 spec 索引可能扫到别的机器路径而失败——失败 SHALL 报错，不静默跳过）。Windows 路径（`C:/...`）与 macOS/Linux 路径在 remote 命中后天然收敛到同一项目。

### 读侧修复

`GET /api/bootstrap` 入参优先级：`project_id`（客户端已解析）→ `repo_remote` → `cwd`（path 前缀回落）→ 无。插件在 `injectSessionStart` 内先跑既有 `resolveProject()`（含自动注册），把得到的 `project_id` 拼进 bootstrap 查询串。写侧解析逻辑一行不改，读侧复用同一函数。

### 重复探测与合并

- 探测：`GET /api/projects/duplicates` 返回 `[{remote, items:[{id,name,path,mem_count}]}]`，纯读。
- 合并：`proj merge <src> <dst>`（或 `POST /api/projects/merge`）在一个事务里把 `memories.project_id`、`specs_index.project_id` 改挂 `dst`；`specs_index` 的 `UNIQUE(project_id, rel_path)` 冲突按"保留 dst 既有行、丢弃 src 重复行"处理并计入报告；`src` 写 `project_removals` 墓碑；合并前把两项目相关行导出为 JSON 备份文件，配套 `--rollback <备份文件>` 还原。

### 文件

- `lclone/projects.py`：`normalize_remote` / `git_remote` / `match_by_remote` / `backfill_remote` / `duplicate_groups` / `merge_projects` / `resolve_project` 扩展
- `lclone/db.py`：`projects.remote` 迁移
- `lclone/web.py`：`/api/bootstrap` 入参、`/api/projects` 追加 `remote`、`/api/projects/duplicates`、`/api/projects/merge`
- `lclone/evolutions.py`：`find_project(ref, repo_path, repo_remote)`
- `lclone/mcp_server.py`：`projects` 输出含 `remote`，`capture`/`remember`/`bootstrap`/`recall` 透传 `repo_remote`
- `lclone/cli.py`：`proj dupes` / `proj merge` / `proj rollback` / capture 上报 remote
- `integrations/dsh/dsh/index.js`：读侧传 `project_id`、写侧附 `repo_remote`
- `lclone/data/starter/evolutions/会话归属与落库约定.md`：归属规则改写
- `tests/test_offline.py`：归一化、remote 匹配、回填、探测、合并、读侧入参优先级、跨机器同项目

## Spec Constraints

- `memory-capture` > 归属判定：「无 git 时 SHALL 问用户新建 project 或升到全局层，而非静默默认全局」——remote 与 path 都拿不到时才触发，不得因服务端 no_git 触发。
- `memory-capture` > 归属判定 > 客户端解析归属（远程后端）：上传的是**客户端解析结果**；服务端 SHALL NOT 依据自身 git 失败降级。
- `memory-capture` > 跨层去重（不变）：写项目层时仍跨层比对全局层；合并项目后判重语义不因 project_id 变更而改变。
- `memory-capture` > 删除项目（不变）：墓碑式移除语义保持；合并的源项目复用同一 `project_removals` 机制，不得物理删除。
- `evolution-store` > 客户端后端路由（不变）：`LCLONE_WEB_URL` 已设时仍走 HTTP；`find_project` 只增加 remote 匹配，不改路由选择。
- `dsh-web-dashboard` > 会话开始加载 skill：「每会话仅注入一次」与「完整 UserMessage 形状」两条硬边界不变，本次只改注入内容里的归属来源。
