## MODIFIED Requirements

### Requirement: 版本历史与回滚

lclone SHALL 保留每个进化资产**版本保留窗口**内的历史版本（窗口大小 `LCLONE_EVO_KEEP_VERSIONS`，默认 5；`<=0` 表示不限制），并 SHALL 提供 `history`（新→旧）与 `rollback`（回到指定版本）。窗口按版本号取**最近 N 个**，且 **`evo_current` 指向的当前版本 SHALL 永远保留**——即使它落在窗口之外，否则回滚到旧版后会被下一次发布剪掉，回滚语义当场失效。发布**成功新增版本后** SHALL 按窗口剪枝，SHALL NOT 改写任何版本的内容；`rollback` SHALL NOT 触发剪枝，SHALL 只修改当前版本指针，因此回滚 SHALL 可再次回滚。内容对象 SHALL 只在**没有任何剩余版本引用**时才回收（内容寻址，同一 hash 可能被多个版本或多个资产共享），SHALL NOT 删除仍被引用的对象。

#### Scenario: 查看历史

WHEN 对某资产请求版本历史
THEN 按版本倒序返回版本号、哈希、大小、说明与时间（只含窗口内仍保留的版本）

#### Scenario: 回滚不删内容

WHEN 回滚到较早版本
THEN 当前指针指向该版本、读取到该版本内容，且内容库对象数量不变（回滚不触发剪枝）

#### Scenario: 回滚到不存在的版本

WHEN 请求回滚到不存在的版本号
THEN 报错且当前指针不变

#### Scenario: 超出窗口的旧版本被剪掉

WHEN 某资产在默认窗口（5）下发布第 6 版
THEN 该资产的旧版本只保留最近 5 个，最旧的版本行被删除；被剪版本不再出现在 `history` 中

#### Scenario: 当前指针版本不被剪

WHEN 回滚到窗口外的旧版本后再次剪枝
THEN 该当前版本仍被保留（窗口 ∪ 当前版本），回滚结果不因剪枝失效

#### Scenario: 共享内容对象不误删

WHEN 内容相同（同 hash）的两个资产中，其中一个资产的版本被剪枝
THEN 该内容对象仍被保留，另一个资产仍可读到完整内容

#### Scenario: 手工巡检与真删

WHEN 运行 `lclone evolution prune`（默认 dry-run）
THEN 只报告将剪的版本与将回收的对象，不修改数据库与内容库；加 `--apply` 才真删

#### Scenario: 关闭版本上限

WHEN `LCLONE_EVO_KEEP_VERSIONS` 设为 `0`（或负数）
THEN 不剪任何版本，行为与既有"保留全部历史"一致
