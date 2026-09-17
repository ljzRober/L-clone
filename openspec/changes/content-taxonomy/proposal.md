## Why

lclone 目前把"规范/说明/模板"这类**说明性内容**当成 evolution 存（`编码准则.md`、`偷懒阶梯.md`、`会话归属与落库约定.md`、`洞察格式模型.md`、`记忆准入标准.md` 五份），理由是"整段放记忆里占注入体积"。但这个理由站不住：**insight 有自己的召回通道（向量 + FTS，命中即进上下文），evolution 没有** —— 把规范放进 evolution 等于放进一个没有检索的桶，只能靠 `[[evo:]]` 指针 + 显式取，于是必须额外补一套"按需加载"机制（recall 顺边、skill 纪律、正文注入），而结果仍然是"读不到"（实测两份资产零引用）。

真正的判据是**"这个东西是干什么的"**，不是篇幅：规范 AI 行为的内容（准则/理由/观察/经验/模板/示例）只需要被**读到** → insight；只有**数据与可执行文件**（脚本/工具/配置/密钥表，独立存在说明不了任何内容、只能被运行或解析）才是 evolution。

## What Changes

- 明确**三类归位判据**（按用途，不按篇幅）：
  - 说明性内容（规范/准则/理由/观察/经验/**模板/示例**）→ **insight**；且**注入正文必须自足**，规范太长就拆成多条原子 insight 或收进 skill 全文（注入层）。
  - 数据/可执行产物（脚本/工具/配置/密钥表）→ **evolution**。
  - 可被检查的契约（WHEN/THEN）→ **spec**。
- **禁止**为控制注入体积把规范/说明移出记忆塞进 evolution。
- 提炼提示词、skill 全文、`evolution_add` 工具描述三处**同步写上该判据**（写侧强制：模型不再把规范建议成 evolution）。
- 新增只读巡检 `lclone evolution audit`（启发式标出疑似说明性文档，**只提示不自动删**，与 suggest 同纪律）。
- 种子内容不再包含说明性 `.md`（`lclone/data/starter/evolutions/` 清空，只留 `scripts/` 下的脚本），种子洞察去掉指向这些文档的 `[[evo:]]`。

**BREAKING**：无 API 形状变化。语义变化：`evolution-store` 的用途被收窄为"数据 + 可执行产物"；既有说明性资产需迁移为 insight 后由用户决定是否下架（工具只提示）。

## Capabilities

### New Capabilities

（无。）

### Modified Capabilities

- `memory-capture`：**修改**「分工边界」——补入三类归位判据与"注入正文必须自足""不得为省体积把规范移出记忆"两条硬约束，原 6 个场景全部保留并新增 4 个。
- `evolution-store`：**新增**「资产类型边界」一条需求（evo 只承载数据与可执行产物；巡检只提示；种子不含说明性文档）。
- `cli-onboarding`：**修改**「首次种子内容」——种子只含数据/脚本类进化资产，说明性文档 SHALL NOT 进种子（原文枚举的三份文档已被移除，本 delta 把契约对齐现实）。

## Impact

- **提示词**：`lclone/llm.py`（提炼提示词加分类判据）。
- **工具描述**：`lclone/mcp_server.py`（`evolution_add` 描述写明边界）。
- **巡检**：`lclone/evolutions.py::audit_misplaced`、`lclone/cli.py::evolution audit`。
- **skill**：`integrations/skill/SKILL.md` 规则 8 改写为"内容三类归位"（+ 同步安装副本）。
- **种子**：`lclone/data/starter/evolutions/` 清空、`insights.md` 去 `[[evo:]]` 指针。
- **数据迁移**：两份准则合并成**一条**自足 insight（去掉"正文外置"的理由段）；三份文档整体下架；五份资产墓碑；`洞察格式约定` 卡去掉 `[[evo:]]` 指针。
- **文档**：`docs/CONCEPTS.md`、`docs/CLI.md` 同步判据。
- **不影响**：发布/回滚/版本窗口/墓碑/改名/鉴权/召回打分。

## 方案

### 判据（写进三处）

```
说明性（规范/准则/理由/观察/经验/模板/示例） → insight（可召回；注入正文自足）
数据与可执行（脚本/工具/配置/密钥表）        → evolution（版本化内容库）
可被检查的契约（WHEN/THEN）                  → spec（openspec）
```

### 巡检（只提示）

`audit_misplaced(conn)` 用形态启发式：跳过 `ref` 类；扩展名属代码/数据类（sh/py/json/yaml/csv…）跳过；`.md/.rst` 直接判疑似；`.txt` 只有出现 markdown 标题或成句标点才算说明文（密钥表这类纯数据不误报）。**只返回清单，不删任何东西**。

### 迁移路径

1. 两份**执行准则**（`coding-guidelines.md` + `code-laziness-ladder.md`）→ **合并为一条**自足 insight（全局层，注入层），原文不再单独存在；
2. 三份**已无引用且内容已在 spec/skill/提示词/gate.py 有权威**的文档（`会话归属与落库约定.md` / `洞察格式模型.md` / `记忆准入标准.md`）→ 整体下架，不再保留副本；
3. 五份资产统一 `evolution delete`（墓碑，历史版本与内容对象保留，可 restore）；
4. 悬空 `[[evo:]]` 指针 → 从卡片正文移除；
5. 两个**运维脚本**（`lclone-backup.sh` / `lclone-pending-digest.sh`，其能力已被 `lclone backup` / `lclone pending` 覆盖）在库里下架（脚本本身不是规范，删它们属于用户对自有资产的决定）。

### 文件

- `lclone/llm.py`、`lclone/mcp_server.py`、`lclone/evolutions.py`、`lclone/cli.py`
- `integrations/skill/SKILL.md`（+ 安装副本）
- `lclone/data/starter/evolutions/`（清空）、`lclone/data/starter/insights.md`
- `docs/CONCEPTS.md`、`docs/CLI.md`、`tests/test_offline.py`（422-426）

## Spec Constraints

- `memory-capture` > 记忆分类与确认（不变）：三段卡形状与"insight 是原子化自包含知识卡"的定义不变；本变更只明确"说明性内容都归 insight"。
- `memory-capture` > 引用纪律（不变）：`[[evo:]]` 仍是 link-not-copy；但**规范类内容不再用 `[[evo:]]` 外置正文**（那会把它推进没有检索的桶）。
- `evolution-store` > 版本化内容寻址存储（不变）：同 hash 只存一份、append-only、可回滚。
- `evolution-store` > 版本历史与回滚（上一条已归档的变更）：保留窗口 5 版 ∪ 当前版本不变；本变更不影响版本语义。
- `cli-onboarding` > 首次种子内容（不变）：种子仍走版本化发布；只把说明性 `.md` 移出种子，洞察与脚本数量随之下调。
- `memory-capture` > 删除纪律（不变）：巡检只提示、绝不自动删。
