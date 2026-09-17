## Why

进化资产的内容库目前**只增不减**：`evo_versions` 每个资产保留全部历史版本（现网 `记忆准入标准.md` 已到 v5，`洞察格式模型.md` v4）。版本是 append-only 的内容寻址存储，长期迭代下索引行与去重后的内容对象都会持续增长，而真正的回滚需求只看最近几版——旧版本的价值随时间迅速衰减，却永久占用清单、历史接口与备份体积。

## What Changes

- 引入**版本保留窗口**：每个资产只保留最近 N 个版本（`LCLONE_EVO_KEEP_VERSIONS`，默认 5；`<=0` 表示不限制）。
- **当前版本（`evo_current` 指向的版本）永远保留**，即使它落在窗口之外——否则"回滚到旧版"会被下一次发布剪掉，回滚语义当场失效。
- 内容对象（blob）**只在没有任何剩余版本引用时才回收**（内容寻址，同一 hash 可能被多版本/多资产共享），SHALL NOT 误删仍被引用的对象。
- 发布（`publish`）成功后自动按窗口剪枝，并在返回值里报告 `pruned_versions` / `pruned_blobs`。
- 新增服务端运维命令 `lclone evolution prune [--name N] [--keep K] [--apply]`（默认 dry-run，与 `evolution migrate` 同约定：远端大脑下在容器/服务器执行）。

**BREAKING**：无接口形状变化；语义变化是"历史版本不再无限保留"——`history` 只返回窗口内的版本，更早的版本不可再回滚。

## Capabilities

### New Capabilities

（无。落在既有 `evolution-store` 能力上。）

### Modified Capabilities

- `evolution-store`：**修改**「版本历史与回滚」——由"保留全部历史版本"改为"保留窗口内版本 ∪ 当前版本"，并补窗口剪枝、当前版豁免、共享对象不误删三条场景。

## Impact

- **后端**：`lclone/evolutions.py`（新增 `keep_versions()` / `prune_versions()` / `_gc_blobs()`；`publish()` 尾部自动剪枝）。
- **CLI**：`lclone/cli.py` 新增 `evolution prune`（dry-run 默认）。
- **配置**：新增 `LCLONE_EVO_KEEP_VERSIONS`（默认 5）。
- **数据**：剪枝会删除超出窗口的 `evo_versions` 行与无引用的 blob；现网数据当前最多 5 版，**暂无需要剪的存量**。
- **文档**：`docs/CLI.md` 补命令说明。
- **不影响**：发布幂等、乐观锁、墓碑/改名、回滚指针语义、客户端缓存同步（manifest 只取当前版本）。

## 方案

### 剪枝函数

```python
def prune_versions(conn, name=None, keep=None, dry_run=True):
    limit = keep_versions() if keep is None else int(keep)
    for nm in ([name] if name else all_names(conn)):
        vers = [v for v in versions_desc(nm)]          # [7,6,5,4,3,2,1]
        keep_set = set(vers[:limit]) if limit > 0 else set(vers)   # 最近 N 个
        keep_set.add(current_version(nm))               # 当前指针版豁免
        drop = [v for v in vers if v not in keep_set]
        if drop and not dry_run:
            DELETE FROM evo_versions WHERE name=? AND version IN (...)
    conn.commit() if not dry_run
    blobs_removed = _gc_blobs(conn, dry_run)            # 只删无人引用的 hash
```

### 与既有语义的关系

- **append-only 不变**：剪枝只删"窗口外的旧版本行"，SHALL NOT 改写任何版本内容；回滚仍只改指针。
- **乐观锁不变**：`base_version` 校验只看当前版本，与历史窗口无关。
- **`ref` 类不变**：无 blob（hash 为空），不参与对象回收。
- **幂等**：同一窗口重复剪枝为 no-op。

### 文件

- `lclone/evolutions.py`、`lclone/cli.py`、`docs/CLI.md`、`tests/test_offline.py`（415-421）

## Spec Constraints

- `evolution-store` > 版本化内容寻址存储（不变）：同 hash 只存一份、写入原子替换的语义不动；回收只删**无引用**对象。
- `evolution-store` > 版本历史与回滚 > 回滚不删内容：「回滚 SHALL NOT 删除或改写任何内容对象，内容库对象数量不变」——回滚**不触发**剪枝，该场景继续成立。
- `evolution-store` > 显式发布（不变）：内容与元数据都没变时仍不新增版本；剪枝只在**新增版本**的路径上发生。
- `evolution-store` > 本地只读缓存与同步（不变）：`manifest` 只携带当前版本，剪枝不影响客户端缓存；已物化的本地副本不因远端剪枝而失效。
- `memory-capture` > 引用就地化 / 引用去重（不变）：剪枝不改任何洞察正文与 `[[evo:]]` 引用。
