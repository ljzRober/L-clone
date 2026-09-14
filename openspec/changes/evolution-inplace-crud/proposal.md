## Why

看板的「进化」面板只能看不能改 —— `lclone/frontend/index.html:722` 的 `showEvo()` 仅做 `textContent` 赋值，改一个进化资产必须回到命令行跑 `lclone evolution publish`。更严重的是后端只有 `publish` / `rollback`，**完全没有删除与改名能力**，错误沉淀的资产无法下架，只能靠再发一版去掩盖。

## What Changes

- 新增**可编辑判定**：内容为合法 UTF-8 且不超过阈值（默认 256 KB，`LCLONE_EVO_MAX_EDIT_BYTES` 可覆盖）的资产可编辑；二进制与超大文件保持只读预览，并由服务端下发不可编辑原因。
- 新增**原地编辑**：看板「进化」面板可就地编辑文本资产并保存，保存即 `publish` 新版本（沿用 append-only 语义）。
- 新增**原地新建**：面板可新建文件（名字 + 内容），首次发布为 v1。
- 新增**墓碑式删除与恢复**：删除把资产移出清单与看板，但保留全部历史版本与内容对象，且可恢复；**不删除、不改写任何 `evo_versions` 行与 blob**。
- 新增**改名**：以新名字发布 v1（内容继承当前版本），旧名字打墓碑并记录 `renamed_to` 指向新名字。
- 新增**乐观锁**：写操作（编辑 / 删除 / 改名）携带 `base_version`，与服务器当前版本不一致时返回 409 并拒绝，避免静默覆盖他人改动。
- 新增**版本历史与回滚的看板入口**：面板可查看版本历史、预览任一历史版本并回滚到该版本（后端 `history` / `rollback` 已存在，本次只补 UI 与 `base_version` 语义）。
- 扩展 `GET /api/evolution/index` 与 `GET /api/evolution/content` 的响应，追加可编辑性、当前版本号与墓碑字段；`GET /api/evolutions` 既有响应形状保持不变。

**BREAKING**：无。删除是墓碑语义，不改变既有读取与回滚行为；`/api/evolutions` 向后兼容（只追加字段）。

## Capabilities

### New Capabilities

（无。本次全部落在既有的 `evolution-store` 能力上，不引入新的 capability 路径。）

### Modified Capabilities

- `evolution-store`：新增「可编辑内容判定」「看板原地增删改查」「乐观锁并发控制」「墓碑删除与恢复」「改名语义」五条需求。既有「版本化内容寻址存储」与「版本历史与回滚」两条硬边界**不变**，故本 delta 只使用 `## ADDED Requirements`。

## Impact

- **数据模型**：`evo_current` 增两列 `deleted_at` / `renamed_to`（`db.init` 幂等迁移）；`evo_versions` 与 blob 存储不变。
- **后端**：`lclone/evolutions.py`（墓碑读写、改名、`base_version` 校验、可编辑判定）、`lclone/web.py`（新增 delete / restore / rename 端点，扩展 publish / index / content）。
- **前端**：`lclone/frontend/index.html` 的进化面板（编辑器、工具条、历史面板、409 冲突提示）。
- **CLI**：`lclone/cli.py` 补 `evolution delete` / `restore` / `rename`，与 HTTP 端点对齐。
- **兼容**：`GET /api/evolutions` 响应形状不变；新增环境变量 `LCLONE_EVO_MAX_EDIT_BYTES`。
- **不影响**：记忆读写路径、模型层、鉴权层。

## 方案

### 墓碑落位

给 `evo_current` 加列，而不新建表 —— 该表本就是「可变指针表」（回滚即改它），墓碑只是名字的一个状态：

```sql
ALTER TABLE evo_current ADD COLUMN deleted_at TEXT NOT NULL DEFAULT '';
ALTER TABLE evo_current ADD COLUMN renamed_to TEXT NOT NULL DEFAULT '';
```

`db.init` 按仓库既有幂等迁移模式（`PRAGMA table_info` 检查后 ALTER）执行；`ls()` 默认过滤 `deleted_at != ''`，`?include_deleted=1` 时返回并带 `deleted_at` / `renamed_to`。

### 可编辑判定（服务端唯一权威）

```python
MAX = int(os.environ.get("LCLONE_EVO_MAX_EDIT_BYTES", 262144))   # 256 KB
def editability(raw: bytes) -> tuple[bool, str]:
    if len(raw) > MAX:
        return False, "too_large"
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        return False, "binary"
    return True, ""
```

判定结果随 `index` / `content` 下发（`editable` + `editable_reason`），前端只镜像、不自行判断 —— 避免前后端判定分叉。

### 端点

| 端点 | 语义 |
| --- | --- |
| `POST /api/evolution/publish` | 扩展：可选 `base_version`；与当前版本不符 → 409 |
| `POST /api/evolution/delete` | 墓碑：置 `deleted_at`（幂等） |
| `POST /api/evolution/restore` | 恢复：清 `deleted_at` |
| `POST /api/evolution/rename` | 新名字发 v1（内容继承）+ 旧名字墓碑 + `renamed_to` 指向新名字；新名字已存在 → 409 |
| `GET /api/evolution/index` | 扩展：追加 `editable` / `editable_reason` / `base_version` / `deleted_at` / `renamed_to`，支持 `?include_deleted=1` |

### 改名为何不等于「移动」

版本化存储是**扁平命名空间**：`lclone/memory.py` 的 `list_evolution_files_sub` 明确写着「不再有子目录」，`evolutions.tree()` 产出的 `is_dir` 恒为 `False`、`children` 恒为空。因此不存在可移入的目录，「移动」在本模型下无意义。改名采用「新名字发 v1 + 旧名字墓碑」，沿用 append-only，不改写 `evo_versions.name`。

### 前端

可编辑时右侧渲染 `<textarea>` + 「保存」；不可编辑时保持纯文本预览并显示原因徽标。工具条：＋新建 / 重命名 / 删除 / 显示已删除（可恢复）/ 历史。写操作一律携带 `base_version`，409 时提示「服务器已有 vN，请刷新后重试」。动态内容全量转义，尊重 `prefers-reduced-motion`。

## Spec Constraints

引自 `openspec/specs/evolution-store/spec.md`（已按 T1 触发点直读全文）：

- **「版本化内容寻址存储」**：`evo_versions` **只追加**（`UNIQUE(name, version)`），`evo_current` 保存当前版本指针；内容身份为内容哈希。本次**不改这条** —— 墓碑只动 `evo_current`，不碰 `evo_versions`。
- **「版本历史与回滚」**：回滚 SHALL 只修改当前版本指针，SHALL NOT 删除或改写任何内容对象。本次**不改这条** —— 墓碑删除同样不删 blob，回滚可再次回滚。
- **「看板兼容」**：`GET /api/evolutions` SHALL 保持既有响应形状（`items[{name,ext,size,mtime,is_dir,children,content}]`），前端 SHALL NOT 需要改动即可继续工作。本次只追加字段，不删字段、不改既有字段语义。
- **「显式发布」**：publish 是显式动作；lclone SHALL NOT 做自动双向同步，也 SHALL NOT 要求冲突合并。乐观锁（拒绝 + 提示刷新）与之一致，未引入 merge 语义。
