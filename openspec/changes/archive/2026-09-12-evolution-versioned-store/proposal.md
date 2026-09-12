## Why

洞察(insight)的权威在服务器 DB，而进化资产(evolution)的权威却是「你当前在哪台机器」：`evo_dir()` 按进程解析，本机 CLI 写 `~/.lclone/evolutions/`、服务器进程写服务器的目录，全仓库没有任何 evolution 的同步或版本代码，`update_evolution` 就是复写文件。结果是**两个权威、两端静默分叉**——实测本地 1 个文件、服务器 5 个文件，谁也不认谁；内容也没有任何版本概念，改一次即永久覆盖。

用户已明确模型：**服务器是唯一权威，本地是只读缓存**（npx/cacache 式——本地可随手删、按需物化、哈希校验、不存在冲突合并），改动走显式 publish 产生新版本。

## What Changes

- 新增内容寻址存储：内容以 `sha256` 命名存放于 `<DB 目录>/evolution-blobs/<hash前2位>/<hash>`，**不可变、天然去重**；`LCLONE_EVO_BLOB_DIR` 可覆盖。内容与 DB 同域，天然落在同一个持久化卷与备份范围。
- 新增版本索引（新表名，避开 `db.py` 遗留的 `DROP TABLE IF EXISTS evolutions`）：`evo_versions`（只追加）+ `evo_current`（当前版本指针）。**回滚只改指针，blob 一动不动。**
- 新增 `lclone/evolutions.py` 承载上述能力（memory.py 已近千行，不再堆叠）；`memory.py` 既有公开函数保留为薄委托，调用方与测试不受影响。
- 本地缓存语义：`~/.lclone/evolutions/` + `.lclone-manifest.json`；
  - `pull` 校验 sha256 后写文件，**拒绝覆盖本地已改(dirty)的文件**，`--force` 才覆盖；
  - `publish` 显式推新版本，内容未变则**不加版本**（幂等）；支持 `--all` 一次推全部 dirty；
  - `status` 给出五态：`in-sync` / `dirty` / `behind` / `missing` / `untracked`。
- 接口面：REST `GET /api/evolution/{index,manifest,content,history}` + `POST /api/evolution/{publish,rollback}`；MCP 升级 `evolution_add` 为 publish 并新增 pull/content/history/rollback；CLI `lclone evolution list|pull|publish|status|history|rollback`，并新增「**设了 `LCLONE_WEB_URL` 就走 HTTP、否则用本地 DB**」的路由规则（顺带修掉本地 CLI 一直写那份没人读的旧库的问题）。
- **`GET /api/evolutions` 响应形状保持不变**（仍返回 `items[{name,size,mtime,is_dir,children,content}]`），底层由「扫目录」换成「读索引+blob」→ 前端零改动。
- 存量迁移：扫描进化目录现有文件，逐个 publish 为 v1。
- `starter seed` 改走 publish（否则绕过索引）；`lclone backup` 覆盖 **DB + blob 目录**（本地物化缓存可复现，不进备份）。
- **非 BREAKING**：`create_evolution` / `update_evolution` / `list_evolution_files` / `read_evolution_file` 的签名与返回保持兼容。

## Capabilities

### New Capabilities

- `evolution-store`: 进化资产的内容寻址存储 + 版本索引 + 本地只读缓存（pull/publish/status/history/rollback、dirty 保护、迁移、ref 类引用）

### Modified Capabilities

- `memory-capture`: 「进化资产与链接」需求的存储语义改写——从「内容存记忆库本体 / 文件式目录，无版本」改为「服务器权威的版本化内容寻址存储，本地为可复现缓存」，并订正其中「项目无关内容存 `content`」这句自 `1d3c1b2` 起就已过时的表述。

## Impact

- 代码：新增 `lclone/evolutions.py`；改 `lclone/db.py`（两张新表 + 索引）、`lclone/memory.py`（薄委托 + `evo_dir` 语义）、`lclone/web.py`（新端点 + `/api/evolutions` 改底层）、`lclone/mcp_server.py`（工具升级/新增）、`lclone/cli.py`（evolution 子命令 + HTTP/本地分支 + backup 覆盖 blob）、`lclone/seed.py`（改走 publish）、`.gitignore`（`/evolution-blobs/`）
- 数据：新增 `evo_versions` / `evo_current` 表与 blob 目录；存量文件迁移为 v1；**不删不改**已有 `memories` 数据
- 兼容：`/api/evolutions` 与 memory.py 公开函数形状不变；前端（看板进化目录）零改动；`BRAIN_LLM=dummy` 下全部可离线跑通
- 测试：`tests/test_offline.py` 增 blob 去重/publish 幂等/版本递增/回滚不动 blob/pull 拒覆盖 dirty/status 五态/迁移 v1/API 形状不变/CLI 路由分支
- 文档：`docs/CONCEPTS.md`（进化资产章节重写为「版本化内容寻址 + 本地缓存」）、`docs/CLI.md`（evolution 子命令）、`docs/DEPLOYMENT.md`（blob 与备份范围）

## 方案

- **权威唯一，介质可以两样**：洞察留在 SQL（需要向量检索/FTS/去重/召回日志/pending），进化资产走「blob + 索引」——介质差异由技术需求决定，但**权威都在服务器、都在 `data/` 一个备份域**，这才是本次要修的根本。
- **内容寻址而非 commit**：`sha256` 即身份 → 校验、去重、脏检测全部退化为一次哈希比较；不引入 merge/diff/三方合并（脚本与模板的自动合并几乎必然要靠人肉，直接把冲突从模型里删掉）。
- **只追加 + 指针**：`evo_versions` 永不改写，`evo_current` 只换指向 → 回滚是 O(1) 且零数据风险。
- **入库与出库对称**：`put_blob` 先算哈希再决定是否落盘（同内容只存一份）；`pull` 先取 blob 再验哈希再写本地（缓存可被任意破坏并自愈）。
- **表名与遗留解耦**：`db.py:init()` 里的 `DROP TABLE IF EXISTS evolutions/evolution_links` 是旧文件式改造的清理语句，保留它、新表用 `evo_*` 名字，避免「每次启动删表」的坑。
- **模块切分**：`gate.py`（准入判定）/ `seed.py`（种子）/ `evolutions.py`（版本化存储）/ `memory.py`（编排与召回）——各自单一职责，便于离线单测。
- **客户端路由**：CLI 用 `LCLONE_WEB_URL` 是否存在决定走 HTTP 还是本地 DB，与 DSH 插件的既有约定一致（本机已设该变量，故本地 CLI 将直接对服务器操作）。

## Spec Constraints

来自已加载的 `memory-capture`（⚠️含边界）、`server-api`、`dsh-web-dashboard`、`cli-onboarding`：

- `memory-capture` > 记忆分类与确认：本次不改准入——洞察仍 SHALL 是四段卡、仍进 pending 待确认；闸门与 `_strip_ingest_noise` 不受影响
- `memory-capture` > 进化资产与链接：`[[evo:name.ext]]` 的解析语义 SHALL 保持（名字 → 内容）；检索命中 insight 时 SHALL 仍顺边带出进化资产
- `memory-capture` > 归属判定：进化资产的 `project_id` 归属 SHALL 与洞察同规则（显式传 / git 判定），SHALL NOT 因引入版本化而改变
- `server-api` > API key 鉴权：新增 `/api/evolution/*` 端点 SHALL 与既有端点同一鉴权（Bearer / X-API-Key），SHALL NOT 新开未鉴权入口
- `server-api` > MCP over HTTP：既有 MCP 工具名 SHALL 保持可用（`evolution_add`/`evolution_list`/`evolution_update`），只升级语义不动名字
- `dsh-web-dashboard` > 看板：`GET /api/evolutions` 的响应形状 SHALL NOT 改变（前端零改动）；看板刷新语义不变
- `cli-onboarding` > 首次种子内容：种子 SHALL 仍种入 4 条通用洞察 + 通用进化文件，且 SHALL NOT 覆盖已存在的进化文件；种子进化文件改走 publish 后 SHALL 仍满足幂等与「删掉不回灌」
- `cli-onboarding` > 一键接入：`setup`/`integrate` 的命令形态与 `--no-seed` SHALL NOT 改变
