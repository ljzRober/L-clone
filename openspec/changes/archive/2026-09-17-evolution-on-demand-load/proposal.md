## Why

进化资产（`[[evo:名字]]`）的设计意图是「正文放服务器版本化库，记忆只留指路卡，用到时顺边带出」。实测这条链在项目会话里是断的：三张指路卡（#796/#797/#655）全在**全局层**，而 `recall` 一旦带 `project_id` 就在 SQL 里加 `AND m.project_id=?`（`lclone/memory.py:746`），全局卡被排除在候选集外，`insight→evolution` 顺边因此永不触发——`recall project=lclone query="偷懒阶梯 编码准则"` 一个资产都没带出。同时 skill 里没有「见到 `[[evo:]]` 必须取正文」的纪律，模型可能只凭卡片摘要动手。

## What Changes

- `recall()` 新增 `include_global` 开关（默认 `False`，保住既有「召回限定项目」的函数级语义与测试）。
- **面向会话的召回入口**改为覆盖「该项目 + 全局层」：MCP `recall`、`POST /api/recall`、`bootstrap` 的【相关记忆】段。依据是 spec 既有的「全局层在任何会话都加载」。
- 打分公式、阈值、顺边按资产名去重规则一律不变，只扩大候选集。
- lclone-memory skill 增加硬规则：正文出现 `[[evo:名字]]` 时必须先用 `evolution_content` 取正文再动手；随后同步安装副本 `~/.agents/skills/lclone-memory/SKILL.md`。
- 安装/启动指引补上 `lclone evolution pull --all`（本地缓存现停在 2026-09-12，缺 `coding-guidelines.md` 与 `code-laziness-ladder.md`）。

**BREAKING**：无。函数级默认行为不变；对外入口只是候选集变大。

## Capabilities

### New Capabilities

（无。落在既有 `memory-capture` 能力上。）

### Modified Capabilities

- `memory-capture`：**新增**「召回覆盖全局层」一条需求；**修改**「分类加载」（明确会话召回覆盖「该项目 + 全局层」，函数级默认保持只召回指定项目）。

## Impact

- **后端**：`lclone/memory.py`（`recall` 增加 `include_global`；`bootstrap` 的【相关记忆】传 `True`）、`lclone/mcp_server.py`（`recall` 传 `True`）、`lclone/web.py`（`/api/recall` 传 `True`）。
- **skill**：`integrations/skill/SKILL.md`（新增取正文纪律）→ 同步 `~/.agents/skills/lclone-memory/SKILL.md`。
- **文档**：`docs/CLI.md` / `docs/CONCEPTS.md` 中「召回限定项目」的表述按新语义澄清（会话召回覆盖全局层，函数默认不变）。
- **测试**：`tests/test_offline.py` 新增"项目会话召回带出全局指路卡及其 evo 正文"用例；既有「召回限定项目」断言（`check("12 召回限定项目")`）保持不变（测的是函数默认）。
- **不影响**：写入路径、闸门、去重、进化资产版本库、看板。

## 方案

### 候选集

```python
def recall(conn, query, k=5, project_id=None, alpha=0.7, status="active",
           follow_links=True, link_extra=3, include_global=False):
    where = "m.status=? AND m.level='insight' AND m.embedding IS NOT NULL"
    if project_id is not None:
        where += " AND (m.project_id=? OR m.project_id IS NULL)" if include_global \
                 else " AND m.project_id=?"
```

- `include_global=False`（默认）：与今天完全一致。
- `include_global=True` 且 `project_id=None`：与今天一致（本来就全库）。
- `include_global=True` 且 `project_id` 给定：项目 + 全局层共同参与打分。

### 入口矩阵

| 入口 | `include_global` | 理由 |
|---|---|---|
| `lclone recall`（CLI） | 新增 `--global/--no-global`，默认 `True` | 用户问"我们定了什么"要能带出全局规则 |
| MCP `recall` | `True` | agent 面向会话 |
| `POST /api/recall` | `True`（可传 `include_global=false` 覆盖） | 看板/问答面向会话 |
| `bootstrap` 的【相关记忆】 | `True` | 会话首轮按 query 召回 |
| 库内函数默认 | `False` | 保住既有语义与回归断言 |

### skill 纪律（新增第 10 条）

> 正文里出现 `[[evo:名字]]` 时，必须先用 `mcporter call lclone.evolution_content name=<名字>`（或 `lclone evolution content <名字>`）取到资产正文再动手；不得凭卡片里的一行摘要猜资产内容。取不到（名字写错/资产已删）时如实说明，不要编造资产内容。

### 文件

- `lclone/memory.py`、`lclone/mcp_server.py`、`lclone/web.py`、`lclone/cli.py`（recall 参数）
- `integrations/skill/SKILL.md` + 安装副本
- `docs/CLI.md`、`docs/CONCEPTS.md`
- `tests/test_offline.py`

## Spec Constraints

- `memory-capture` > 进化资产与链接（不变）：「检索命中 insight 时 SHALL 顺 `insight→evolution` 边带出该资产」——本 change 只让**全局层的指路卡也能被命中**，不改变顺边规则本身。
- `memory-capture` > 引用去重（不变）：顺边带出仍按**资产名**去重，一次召回同一资产只出现一份。
- `memory-capture` > 全局层注入上限（不变）：`global_limit=100` 与「每会话只注入一次」不变；本 change 只影响按 query 的【相关记忆】段，不扩大【全局记忆】全量注入。
- `memory-capture` > 跨层去重（不变）：判重阈值 0.92 与归一化文本规则不动，本 change 不碰写入路径。
- `memory-capture` > 闸门标准单一来源（不变）：本 change 不改 `gate.py`。
