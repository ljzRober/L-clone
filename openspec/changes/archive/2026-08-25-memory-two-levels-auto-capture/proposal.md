## Why

一次对话后发现 lclone 的记忆等级存在两个问题：

1. **「重要修改点(milestone)」与 sp-spec 职责重复**：项目的"重要修改点"本质是 spec 变更历史，已由 sp-spec（openspec）承载——`openspec/changes/`(proposal+delta) + `archive` 后合并进 `openspec/specs/`，git 版本化。lclone 的 `specs_index`(L2) 专职索引这些文件，权威在仓库。大脑里再存一份 milestone 就是冗余。
2. **「记录(note)」没有任何写入路径**：schema/UI/spec 都有 note 这一档，但 `capture()` 把等级硬编码成 `decision`、`extract_decisions()` 只提炼"决策"，导致 note 一条都没存下来（实测 DB 只有 8 条 decision、0 条 note）。

此外，当前自动记忆依赖模型自觉（skill 的"会话开始 recall / 对话中 capture"是软指令），缺少硬触发，需要用户主动说"记一下"才能沉淀，不够自动。

## What Changes

- **等级收窄**：L1 记忆等级从 `decision/milestone/note` 收窄为 `decision/note`，去掉 milestone（重要修改点交由 sp-spec 的 spec 变更历史 + specs_index 承担）。
- **补 note 写路径**：新增 `extract_memories()` 分类器，把内容分类为 decision/note（替代只提炼决策的 `extract_decisions()`）；`capture()` 不再硬编码等级，decision 和 note 都能进草稿。
- **写入去重**：`capture()` 写入前用向量相似度（阈值 0.92，与 suggest 一致）去重，降噪前置。
- **会话注入（读侧自动）**：新增 MCP 工具 `bootstrap`，会话开始一次返回 charter + 全局层记忆（无条件注入）+ 按话题召回的项目记忆。
- **commit 钩子（写侧自动）**：新增 `scripts/hooks/post-commit`，每次 commit 后自动 `capture` commit 内容进草稿。

## Capabilities

- **New Capabilities**: 无
- **Modified Capabilities**:
  - `web-hierarchy`：修改「记忆工作台」需求——三个横向划分(决策/重要修改点/记录) 改为两个(决策/记录)

## 方案

### 分工模型（sp-spec ↔ lclone）

| 内容 | 归属 | 存储 |
|---|---|---|
| 需求/场景/⚠️边界 | sp-spec | openspec/specs/*.md（git 版本化） |
| 重要修改点（spec 变更史） | sp-spec | openspec/changes/*（delta + archive） |
| 决策 decision | lclone | memories(level=decision) |
| 记录 note | lclone | memories(level=note) |
| 大方向 charter | lclone | projects.charter |
| 会话流水 | lclone | sessions(L0) |

升级路径：lclone 决策(候选边界) → 验证为硬约束 → sp-spec ⚠️边界(写进 spec.md) → lclone specs_index 只读索引。spec 全文永远在仓库，脑里只留索引和"为什么"。

### 文件变更

- `lclone/llm.py`：`extract_decisions` → `extract_memories`（返回 `[{level,content,confidence}]`，分类 decision/note；dummy 后端整段视为一条 note）
- `lclone/memory.py`：`LEVELS` 收窄为 `("note","decision")`；`capture()` 改用分类器 + 写入去重；新增 `_is_duplicate`
- `lclone/db.py`：schema 注释同步（decision|note）
- `lclone/cli.py`：`--level` choices 收窄；capture 文案
- `lclone/mcp_server.py`：level enum 收窄；新增 `bootstrap` 工具
- `lclone/web.py`：三列→两列，去 milestone 颜色/选项/LN
- `scripts/hooks/post-commit`：新增 commit 钩子（自动 capture）
- `docs/DESIGN.md`、`docs/ARCHITECTURE.md`：三档→两档文案
- `tests/test_offline.py`：补 `extract_memories` 分类 / `capture` 写 note / LEVELS 不含 milestone 三条断言
- skill `lclone-memory`（全局，非本仓库）：去 milestone、capture 产出 decision+note、会话开始硬性 bootstrap

## Spec Constraints

- `web-hierarchy` > 记忆工作台：页面三个横向划分 → 两个横向划分（本次变更）
- `web-hierarchy` > 记忆工作台 > 无 spec 区分：界面不出现「记忆/spec」区分——保持

## Impact

- 文件：`lclone/llm.py`、`lclone/memory.py`、`lclone/db.py`、`lclone/cli.py`、`lclone/mcp_server.py`、`lclone/web.py`、`scripts/hooks/post-commit`、`docs/*.md`、`tests/test_offline.py`
- 测试：`tests/test_offline.py` 全绿（补 3 条断言）
- 依赖：无新增
- 数据：现有 DB 无 milestone 数据，无需迁移；`remember()` 保留"未知 level → fallback decision"防御
