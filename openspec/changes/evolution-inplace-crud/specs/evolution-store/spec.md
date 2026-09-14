## ADDED Requirements

### Requirement: 可编辑内容判定

lclone SHALL 在服务端判定每个进化资产是否可编辑，规则为「内容为合法 UTF-8」且「字节数不超过阈值」（默认 262144 字节，即 256 KB；环境变量 `LCLONE_EVO_MAX_EDIT_BYTES` 可覆盖）。判定结果 SHALL 随资产清单与内容接口一并下发（`editable` 布尔值与 `editable_reason` 原因码），前端 SHALL 只镜像该结果、SHALL NOT 自行判断内容是否可编辑。不可编辑的资产 SHALL 用下列原因码之一说明：`binary`（内容含 NUL 字节或不是合法 UTF-8）、`too_large`（字节数超过阈值）、`ref`（内容存放在项目仓库、不在内容库）、`missing`（内容对象缺失或与其哈希不匹配）。不可编辑的资产 SHALL 保持只读预览，且 SHALL NOT 因此阻塞其查看、版本历史与回滚、删除、改名等操作。

#### Scenario: 文本资产可编辑

WHEN 资产内容为合法 UTF-8 且字节数不超过阈值
THEN 该资产在清单与内容接口中的 `editable` 为真，`editable_reason` 为空

#### Scenario: 二进制资产只读

WHEN 资产内容不是合法 UTF-8（含非法字节序列，或含 NUL 字节）
THEN `editable` 为假且 `editable_reason` 为 `binary`，该资产仅可预览内容，编辑入口不可用

#### Scenario: 超大文件只读

WHEN 资产内容为合法 UTF-8 但字节数超过阈值
THEN `editable` 为假且 `editable_reason` 为 `too_large`

#### Scenario: 引用类资产只读

WHEN 资产是引用类（内容在项目仓库、内容库中无对应对象）
THEN `editable` 为假且 `editable_reason` 为 `ref`

#### Scenario: 内容对象缺失或损坏时只读

WHEN 资产的内容对象在内容库中缺失，或存在但与其哈希不匹配
THEN `editable` 为假且 `editable_reason` 为 `missing`

#### Scenario: 阈值可配置

WHEN 设置了环境变量 `LCLONE_EVO_MAX_EDIT_BYTES`
THEN 判定改用该值作为字节上限，无需改动代码

#### Scenario: 只读不阻塞其余操作

WHEN 某资产被判为不可编辑
THEN 它仍可被查看、查看历史、回滚、删除（墓碑）与改名

### Requirement: 看板原地增删改查

看板「进化」面板 SHALL 支持在既有文件清单的位置上完成增、删、改、查四类操作，SHALL NOT 要求用户改用命令行完成。编辑与新建 SHALL 复用显式发布通路：保存产生新版本，SHALL NOT 改写任何既有版本行或内容对象；新建 SHALL 以首次发布产生 v1。**编辑 / 删除 / 改名** SHALL 携带调用方读取时的 `base_version`；**新建** 没有前序版本可作乐观锁，SHALL 以 `only_if_new` 表达「期望不存在」（目标名已是活跃资产时返回 409 且不产生任何版本）。

#### Scenario: 原地编辑并保存

WHEN 用户在某可编辑资产的编辑区修改内容并保存，且其 `base_version` 与服务器当前版本一致
THEN 追加一个新版本，内容为本次提交内容，清单与看板刷新到该版本

#### Scenario: 内容未变的保存不产生新版本

WHEN 用户保存的内容与当前版本完全相同
THEN 不新增版本，返回当前版本号并标记为未变化

#### Scenario: 原地新建

WHEN 用户以新名字与内容新建资产
THEN 该名字首次发布为 v1，并出现在清单与看板中

#### Scenario: 新建重名被拒绝

WHEN 用户以清单中已存在的活跃名字新建
THEN 返回 409 且不产生任何版本，既有资产不被改动

#### Scenario: 只读资产不提供编辑入口

WHEN 用户打开一个 `editable` 为假的资产
THEN 面板只呈现内容，不提供编辑与保存入口

### Requirement: 乐观锁并发控制

**调用方持有读取视图时**，写操作（编辑 / 删除 / 改名）SHALL 携带该视图的 `base_version`（显式省略即表示不校验——服务端按"不校验"处理，SHALL NOT 把"未携带"当作"版本一致"）。服务端 SHALL 在该值不等于当前版本时拒绝写操作并返回 409，SHALL NOT 以任何形式静默覆盖。该枚举**不含** `restore` 与 `rollback` —— 这不是因为二者「天然豁免」，而是本枚举写在 `restore` 成为端点之前，且二者都不带「陈旧视图」危害：`restore` 只清墓碑、不产生新版本；`rollback` 只移动当前指针，版本行与内容对象都不丢、可再次回滚。lclone SHALL NOT 为此引入自动双向同步或冲突合并语义。

#### Scenario: 版本一致时放行

WHEN 写请求的 `base_version` 等于服务器当前版本
THEN 请求被接受并按其语义生效

#### Scenario: 版本不一致时拒绝

WHEN 写请求的 `base_version` 小于服务器当前版本（他人已发布新版本）
THEN 返回 409，响应中给出服务器当前版本号，且不产生任何新版本、不改动当前指针

#### Scenario: 不静默覆盖

WHEN 乐观锁校验失败
THEN 调用方提交的内容 SHALL NOT 被写入，SHALL NOT 产生新版本

#### Scenario: 提示刷新后重试

WHEN 前端收到 409
THEN 面板按冲突性质如实提示：服务器已有新版本时引导刷新后重试，该名字已被墓碑删除时提示先恢复（该分支下刷新与重试都不会成功），且 SHALL NOT 丢弃用户已编辑的内容

### Requirement: 墓碑删除与恢复

删除 SHALL 为墓碑语义：把该名字标记为已删除，使其从默认清单与看板中消失，并 SHALL 保留其全部历史版本与内容对象。删除 SHALL NOT 删除或改写任何 `evo_versions` 行，SHALL NOT 删除任何内容对象。已删除的名字 SHALL 可恢复，恢复后其当前版本与删除前一致。清单接口 SHALL 支持显式请求包含已删除条目。

#### Scenario: 删除后从默认清单消失

WHEN 某资产被删除
THEN 不带显式参数的清单与看板不再包含该名字

#### Scenario: 历史与内容完整保留

WHEN 某资产被删除
THEN 其 `evo_versions` 行数与内容库对象数量均不变，历史版本仍可读取

#### Scenario: 显式列出已删除

WHEN 清单请求显式要求包含已删除条目
THEN 返回结果包含该名字并标注其已删除状态

#### Scenario: 恢复

WHEN 对已删除的名字执行恢复
THEN 它重新出现在默认清单中，当前版本与删除前一致

#### Scenario: 重复删除幂等

WHEN 对已删除的名字再次执行删除
THEN 结果与首次一致，不报错、不产生新版本

### Requirement: 改名语义

改名 SHALL 以新名字发布一版（内容继承改名时的当前版本），并 SHALL 把旧名字标记为已删除且记录其指向的新名字。lclone SHALL NOT 改写 `evo_versions` 中的名字，SHALL NOT 把旧名字的历史链迁移到新名字。目标名字已是活跃资产时 SHALL 拒绝改名。目标名字此前从未使用时，其首个版本 SHALL 为 v1；目标名字留有自身历史时（例如已墓碑），SHALL 沿用该名字自己的版本号递增，SHALL NOT 重置或改写它的历史。

#### Scenario: 改名后的状态

WHEN 对某资产执行改名，且目标名字此前从未使用
THEN 新名字以原当前内容发布为 v1，旧名字从默认清单消失并记录指向新名字的引用

#### Scenario: 改名到已墓碑的名字

WHEN 改名目标名字此前留有历史且当前处于墓碑状态
THEN 新名字以原当前内容发布为其历史最大版本加一，旧名字同样被标记为已删除并记录指向新名字

#### Scenario: 历史不迁移

WHEN 改名完成
THEN 新名字的版本历史只含它自己的版本（不含旧名字的任何版本），旧名字的历史版本保持不变且仍可查询

#### Scenario: 目标名冲突被拒绝

WHEN 改名目标名字已是活跃资产
THEN 返回 409，既不发布新名字也不改动旧名字

#### Scenario: 改名可追溯

WHEN 查看旧名字的墓碑信息
THEN 能读到它指向的新名字

## MODIFIED Requirements

### Requirement: 本地只读缓存与同步

本地进化目录 SHALL 只是**可复现的缓存**：`pull` SHALL 按清单取内容、校验哈希后写文件，并更新本地清单（`.lclone-manifest.json`）；对本地已被修改（内容与清单哈希不一致）的文件，`pull` SHALL 拒绝覆盖并报告为 `dirty`，只有显式 `--force` 才覆盖（覆盖前 SHOULD 另存 `<name>.dirty.bak`）。`status` SHALL 给出六种状态：`in-sync` / `behind` / `dirty` / `missing` / `untracked` / `deleted`（`deleted` = 服务器已把该名字标为墓碑，**无论本地是否仍留有副本**；它 SHALL NOT 被当作可上传的 `untracked`，恢复须走显式 `restore`）。删除整个本地缓存目录后，`pull --all` SHALL 能完全还原。

#### Scenario: 拉取校验哈希

WHEN 从后端取回的内容其 sha256 与清单记录不一致（传输截断/被篡改）
THEN SHALL NOT 写入本地缓存，SHALL 报告为校验失败，且本地已有文件 SHALL NOT 被覆盖

#### Scenario: 首次拉取物化

WHEN 本地没有任何缓存文件
THEN `pull --all` 把服务器全部资产写入本地并写入清单

#### Scenario: 拒绝覆盖本地修改

WHEN 本地文件内容与清单记录的哈希不一致（被用户改过）
THEN `pull` 报告该文件为 dirty 且不覆盖；加 `--force` 才覆盖并保留 `.dirty.bak`

#### Scenario: 状态六态

WHEN 运行 `status`
THEN 每个名字给出 in-sync / behind / dirty / missing / untracked / deleted 之一

#### Scenario: 缓存可完全重建

WHEN 删除本地缓存目录后重新 `pull --all`
THEN 内容与清单完全还原，与服务器当前版本一致
