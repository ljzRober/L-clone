## MODIFIED Requirements

### Requirement: 版本化内容寻址存储

lclone SHALL 把进化资产的内容存为**不可变、可寻址**的对象：内容以 `sha256` 命名存放于内容库目录（默认 `BRAIN_DB_PATH` 所在目录下的 `evolution/blobs/`，即容器部署的 `/data/evolution/blobs/`，使服务器侧持久化收敛为**一处** `data/evolution/`；`LCLONE_EVO_BLOB_DIR` 可覆盖），相同内容 SHALL 只存一份。版本索引 SHALL 落在 SQL：`evo_versions` **只追加**（`UNIQUE(name, version)`），`evo_current` 保存当前版本指针。内容身份 SHALL 为内容哈希；哈希不匹配的内容 SHALL 视为缺失（缓存可自愈）。

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

#### Scenario: 服务器侧持久化只有一处

WHEN 容器化部署（`BRAIN_DB_PATH=/data/lclone.db`）且未覆盖默认值
THEN 内容库位于 `/data/evolution/blobs/`，与数据库同在 `/data` 卷上；服务器不再需要单独的进化缓存目录

#### Scenario: 内容类型可分辨

WHEN 资产以扩展名可推断类型（`.sh`/`.py`/`.md`）
THEN 索引中的 `kind` SHALL 记为该类型（script/tool/model），SHALL NOT 一律落为默认值；对历史上被错误标为默认值的资产，SHALL 能通过一次显式补正**发布新版本**修正（保留历史，不原地改写）
