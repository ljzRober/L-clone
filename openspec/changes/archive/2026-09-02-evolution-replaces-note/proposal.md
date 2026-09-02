## Why

note（过程性事实/记录）经实践发现价值过窄：大量 note 是原始回合转储（混系统提示/工具报错/注入段），真正够格的"免确认 gotcha"仅 3-4 条。用户拍板：**note 通道废弃，改由「evolution（自进化脚本/工具，实践中沉淀）」承接**；insight 补足检索/按需加载（本就已具备 recall/bootstrap），并把 insight 做厚（四段卡：要点/背景/影响/归属）。

## What Changes

- **取代 note → evolution**：新增 `evolutions` 实体（可复用脚本/工具）+ `insight→evolution` 链接（一个进化资产可被 1..N 个 insight 支撑）。存储：项目无关的通用脚本内容存记忆库本体（`content`）；项目内脚本只留路径引用（`ref`，内容留仓库）。`update_evolution` 用于脚本被改时同步最新版本（"稳定"= 暂不再修改，软收敛）。
- **memory 收窄为 insight**：`LEVELS` 由 `("note","insight")` 收窄为 `("insight",)`；`capture` 移除 note 通道（不再每轮无条件追加原文）；`_filter_item` 不再做 insight→note 降级，改为 insight 准入（排除「做了什么」/ 过短琐碎）。`bootstrap`/`recall` 只呈现/召回 insight，recall 顺 `insight→evolution` 边带出进化资产。
- **CLI/MCP**：`--level` 只取 insight；新增 `evolution add/list`（CLI）与 `evolution_add/list/update`（MCP tools）。

## 设计

- insight = 语义卡（每件事：要点/背景/影响/归属，2-4 句自包含），作检索与 embedding 单元。
- evolution = 程序性资产（可执行脚本/工具，实践中生成、会话中迭代、不再改即稳定）；insight 指向它阐明"为什么这么做/教训"。
- 检索：命中 insight → 顺边带出 evolution（复用 follow_links 思路）；反之 evolution→insight。
- note 通道（「记录按会话聚合」「note 滚动压缩」）移除；既有 note 旧数据保留但不再新建/呈现（后续可迁移为 insight 或 evolution）。

## Impact

- 代码：`lclone/db.py`（evolutions + evolution_links 表）、`lclone/memory.py`（LEVELS/capture/filter/bootstrap/recall/organize + evolution 函数）、`lclone/llm.py`（extract 只出 insight）、`lclone/cli.py`、`lclone/mcp_server.py`、`lclone/web.py`。
- 测试：`tests/test_offline.py`（去 note 断言 + evolution/链接/CLI 冒烟），全绿。
- Spec：`memory-capture`（记忆分类与确认/记忆整理合并 MODIFIED；记录按会话聚合 + note 滚动压缩 REMOVED；进化资产与链接 ADDED）。
