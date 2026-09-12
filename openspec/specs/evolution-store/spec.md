# evolution-store Specification

## Purpose
TBD - created by archiving change evolution-versioned-store. Update Purpose after archive.
## Requirements
### Requirement: 版本化内容寻址存储

lclone SHALL 把进化资产的内容存为**不可变、可寻址**的对象：内容以 `sha256` 命名存放于内容库目录（默认跟随 `BRAIN_DB_PATH` 所在目录下的 `evolution-blobs/`，`LCLONE_EVO_BLOB_DIR` 可覆盖），相同内容 SHALL 只存一份。版本索引 SHALL 落在 SQL：`evo_versions` **只追加**（`UNIQUE(name, version)`），`evo_current` 保存当前版本指针。内容身份 SHALL 为内容哈希；哈希不匹配的内容 SHALL 视为缺失（缓存可自愈）。

#### Scenario: 相同内容只存一份

WHEN 两次发布内容完全相同的不同名字（或同一名字）
THEN 内容库中该内容只存在一个对象，索引两条记录指向同一哈希

#### Scenario: 发布幂等

WHEN 用与当前版本完全相同的内容再次发布
THEN 不新增版本，返回当前版本号且标记为未变化

#### Scenario: 版本号按历史最大值递增

WHEN 当前指针曾被回滚到较早版本后再发布新内容
THEN 新版本号取历史最大版本 + 1，不与非当前的历史版本冲突

#### Scenario: 损坏内容自愈

WHEN 内容库中某对象的内容与其哈希不匹配
THEN 读取视为缺失（返回空）而不是返回被篡改的内容；再次发布同一内容时 SHALL 重写该对象并恢复可读

### Requirement: 本地只读缓存与同步

本地进化目录 SHALL 只是**可复现的缓存**：`pull` SHALL 按清单取内容、校验哈希后写文件，并更新本地清单（`.lclone-manifest.json`）；对本地已被修改（内容与清单哈希不一致）的文件，`pull` SHALL 拒绝覆盖并报告为 `dirty`，只有显式 `--force` 才覆盖（覆盖前 SHOULD 另存 `<name>.dirty.bak`）。`status` SHALL 给出五种状态：`in-sync` / `behind` / `dirty` / `missing` / `untracked`。删除整个本地缓存目录后，`pull --all` SHALL 能完全还原。

#### Scenario: 拉取校验哈希

WHEN 从后端取回的内容其 sha256 与清单记录不一致（传输截断/被篡改）
THEN SHALL NOT 写入本地缓存，SHALL 报告为校验失败，且本地已有文件 SHALL NOT 被覆盖

#### Scenario: 首次拉取物化

WHEN 本地没有任何缓存文件
THEN `pull --all` 把服务器全部资产写入本地并写入清单

#### Scenario: 拒绝覆盖本地修改

WHEN 本地文件内容与清单记录的哈希不一致（被用户改过）
THEN `pull` 报告该文件为 dirty 且不覆盖；加 `--force` 才覆盖并保留 `.dirty.bak`

#### Scenario: 状态五态

WHEN 运行 `status`
THEN 每个名字给出 in-sync / behind / dirty / missing / untracked 之一

#### Scenario: 缓存可完全重建

WHEN 删除本地缓存目录后重新 `pull --all`
THEN 内容与清单完全还原，与服务器当前版本一致

### Requirement: 显式发布

把本地改动回流 SHALL 是**显式动作**：`publish` 读取本地缓存文件内容并发布为新版本（内容未变则不新增版本）；`publish --all` SHALL 一次推送全部 `dirty` 与 `untracked` 文件。lclone SHALL NOT 做本地与服务器之间的自动双向同步，也 SHALL NOT 要求冲突合并——本地永远不是权威。

#### Scenario: 推送本地改动

WHEN 本地文件被修改后执行 `publish <name>`
THEN 服务器新增一版（内容未变则不加版本），本地清单更新为已同步

#### Scenario: 元数据变更也产生新版本

WHEN 内容不变但归属项目 / 类型 / 引用来源发生变化
THEN SHALL 新增一版以记录新元数据（SHALL NOT 静默丢弃归属变更）

#### Scenario: 回滚后的状态与拉取一致

WHEN 服务器当前指针被回滚到较早版本，而本地是干净的更高版本
THEN `status` SHALL 报 `behind`（而不是 `dirty`），`pull` SHALL 允许覆盖本地，
且 `publish --all` SHALL NOT 把回滚悄悄推回去

#### Scenario: 备份副本不当作资产

WHEN `pull --force` 留下 `<name>.dirty.bak` 安全副本
THEN 它 SHALL NOT 被当作进化资产（不出现在清单、不被 push、不被迁移摄入）

#### Scenario: 批量推送

WHEN 存在多个 dirty / 未收录文件时执行 `publish --all`
THEN 逐个发布并分别报告成功、未变化与失败，单个失败不影响其余

### Requirement: 版本历史与回滚

lclone SHALL 保留每个进化资产的全部历史版本，并 SHALL 提供 `history`（新→旧）与 `rollback`（回到指定版本）。回滚 SHALL 只修改当前版本指针，SHALL NOT 删除或改写任何内容对象，因此回滚 SHALL 可再次回滚。

#### Scenario: 查看历史

WHEN 对某资产请求版本历史
THEN 按版本倒序返回版本号、哈希、大小、说明与时间

#### Scenario: 回滚不删内容

WHEN 回滚到较早版本
THEN 当前指针指向该版本、读取到该版本内容，且内容库对象数量不变

#### Scenario: 回滚到不存在的版本

WHEN 请求回滚到不存在的版本号
THEN 报错且当前指针不变

### Requirement: 存量迁移与备份范围

lclone SHALL 提供把既有文件式进化资产**摄入为 v1** 的迁移能力，且 SHALL 幂等（已进索引的名字不再处理）。备份 SHALL 覆盖两处权威存储：SQLite 数据库与内容寻址库；本地物化缓存 SHALL NOT 进备份（可复现）。

#### Scenario: 存量文件摄入

WHEN 进化目录中存在尚未进索引的文件并执行迁移
THEN 每个文件发布为 v1；再次执行不产生新版本

#### Scenario: 迁移是服务端操作

WHEN 配置的是远端大脑地址且未显式指定本地
THEN `evolution migrate` SHALL 拒绝执行并提示在大脑所在机器执行（因为要读的是那边的目录），SHALL NOT 静默去动客户端本地库

#### Scenario: 备份覆盖内容库

WHEN 执行 `backup`
THEN 同时产出数据库快照与内容库快照，二者合起来足以完整还原大脑

### Requirement: 客户端后端路由

进化资产的客户端操作 SHALL 支持两种后端且逻辑一致：配置了远端大脑地址（`LCLONE_WEB_URL`）时 SHALL 走 HTTP（携带 `LCLONE_API_KEY` 鉴权），否则 SHALL 用本地数据库；SHALL 提供 `--local` 强制走本地。选择远端后端时 SHALL NOT 打开或初始化本地数据库。

#### Scenario: 配置了远端地址

WHEN `LCLONE_WEB_URL` 已设置且未指定 `--local`
THEN 操作通过 REST 发往远端大脑，且不读写本地数据库

#### Scenario: 未配置远端地址

WHEN 未设置 `LCLONE_WEB_URL` 或显式指定 `--local`
THEN 操作作用于本地数据库

### Requirement: 看板兼容

看板的进化资产端点（`GET /api/evolutions`）SHALL 保持既有响应形状（`items[{name,ext,size,mtime,is_dir,children,content}]`），底层数据源从"扫描目录"换成"读版本索引 + 内容库"。前端 SHALL NOT 需要改动即可继续工作。

#### Scenario: 看板端点形状不变

WHEN 看板请求进化资产列表
THEN 返回条目仍含 name/ext/size/mtime/is_dir/children/content 字段，content 为当前版本内容；可附加版本等新字段

