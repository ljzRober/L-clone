## Why

上一版把进化资产改成「服务器内容寻址库 + 本地只读缓存」后，落盘命名沿用了旧的文件时代习惯，导致三处不一致：服务器内容库叫 `data/evolution-blobs/`、服务器**还额外留着一个** `data/evolutions/` 缓存目录（compose 里设的，文件时代为方便迁移而保留）、客户端缓存叫 `~/.lclone/evolutions/`（复数）。同时看板的「进化」面板标题写死了 `~/.lclone/evolutions/` 这个字面量，显示的是一个与任何机器都无关的旧路径；`evolution migrate` 又漏了按扩展名推断类型，导致 `.md` 规范文档与 `.sh` 脚本在元数据上都成了 `other`，分不出来。

## What Changes

- **统一命名并收敛持久化位置**：客户端缓存默认 `~/.lclone/evolution/`（原 `evolutions`）；服务器内容库默认 `<BRAIN_DB_PATH 目录>/evolution/blobs/`（原 `evolution-blobs/`）。容器部署下服务器侧持久化**只剩两处**：`/data/lclone.db` 与 `/data/evolution/`。`LCLONE_EVO_DIR` / `LCLONE_EVO_BLOB_DIR` 两个环境变量保留（仅默认值变化）。
- **去掉服务器侧多余的缓存目录**：`docker-compose.yml` 不再设 `LCLONE_EVO_DIR=/data/evolutions`；容器内的缓存是可复现的，不需要持久化。
- **修看板显示**：面板标题不再写死路径，改为从 `/api/evolution/index` 新增的 `dirs` 字段读取**服务器真实位置**（如「服务器内容库 /data/evolution/blobs · N 个资产」）；顺带订正两处过时文案（"文件本身即权威" 等）。
- **类型元数据**：`evolution migrate` 与种子种入共用同一份扩展名→kind 规则（`.sh→script`、`.py→tool`、`.md→model`）；新增 `lclone evolution retype`，把历史上被标成默认值的资产**发布一版修正**（保留历史，不原地改写）。
- **随包文档同步**：skill 源文件、`docs/*`、README 架构图里的路径与「进化资产」描述改为新模型。
- **非 BREAKING**：环境变量名不变；旧目录是缓存，`pull --all` 即可重建。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `evolution-store`: 内容库默认路径改为 `evolution/blobs/` 并新增「服务器侧持久化只有一处」「内容类型可分辨（含补正能力）」两条需求
- `cli-onboarding`: 种子进化文件物化目录默认改为 `~/.lclone/evolution/`，并把类型推断纳入存量摄入

## Impact

- 代码：`lclone/evolutions.py`（默认路径、`kind_of_name`、`retype_default_kinds`）、`lclone/cli.py`（`evolution retype`）、`lclone/web.py`（index 返回 `dirs`）、`lclone/frontend/index.html`（标题改为读服务器路径）、`lclone/db.py`/`lclone/memory.py`（注释）、`docker-compose.yml`（去掉 `LCLONE_EVO_DIR`）、`.gitignore`、`integrations/skill/SKILL.md`、`docs/*`、README ×2
- 数据：服务器上 `data/evolution-blobs/` 需移动到 `data/evolution/blobs/`（内容寻址，直接 `mv` 即可）；旧的 `data/evolutions/` 可删（内容已在库中）。客户端旧目录 `~/.lclone/evolutions/` 是缓存，可 `mv` 或直接 `pull --all` 重建
- 兼容：`GET /api/evolutions` 形状不变（`dirs` 加在新的 `/api/evolution/index` 上）；`LCLONE_EVO_DIR`/`LCLONE_EVO_BLOB_DIR` 名不变
- 测试：默认路径、retype 补正、migrate 类型推断、看板 `dirs` 字段

## 方案

- **命名对齐而不是新建镜像目录**：客户端缓存与服务器内容库同名（`evolution`），但**语义不对应** —— 客户端那份是从 API 物化出来的缓存，服务器上不存在"与客户端目录镜像"的目录。把服务器侧收敛成一处 `data/evolution/`（内含 `blobs/`），是为了让"服务器持久化了什么"一眼可见。
- **默认值改动走 env 兼容**：不改环境变量名，只改默认值，避免破坏既有配置。
- **元数据修正走版本而不是 UPDATE**：`evo_versions` 只追加是上一版的核心不变式，类型补正因此发布新版本并在版本说明里写明，历史可追溯。

## Spec Constraints

- `evolution-store` > 本地只读缓存与同步 / 显式发布 / 版本历史与回滚 / 客户端后端路由：本次只改默认路径与类型元数据，`pull` 拒覆盖 dirty、`publish` 语义、回滚只改指针、HTTP/本地路由 SHALL NOT 改变
- `evolution-store` > 看板兼容：`GET /api/evolutions` 的 `items` 形状 SHALL NOT 改变（`dirs` 加在新端点上）
- `memory-capture` > 进化资产与链接：`[[evo:name.ext]]` 解析与顺边带出 SHALL NOT 改变
- `cli-onboarding` > 一键接入：`setup` / `install` / `--no-seed` 形态 SHALL NOT 改变
- `server-api` > API key 鉴权：新增/改动的端点 SHALL 沿用同一鉴权
