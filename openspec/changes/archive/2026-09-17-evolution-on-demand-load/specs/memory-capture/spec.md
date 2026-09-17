## MODIFIED Requirements

### Requirement: 分类加载

bootstrap 与 recall 加载记忆时 SHALL 按「项目」分组展示（全局层按等级分组），而非扁平列表；bootstrap 依据会话归属在【全局记忆】基础上决定是否额外加载【项目方向】与【项目记忆】。**面向会话的召回入口**（MCP `recall`、`POST /api/recall`、bootstrap 的【相关记忆】段）SHALL 覆盖「该项目 + 全局层」；库内函数级默认（未显式开启 `include_global`）SHALL 保持「只召回指定项目」的既有语义，SHALL NOT 因本变更改变。

#### Scenario: bootstrap 分类加载

WHEN bootstrap 加载相关记忆
THEN 按项目分组、项目内按等级列出；项目会话额外带【项目方向】+【项目记忆】

#### Scenario: recall 分类加载

WHEN recall 返回召回结果
THEN 按项目 → 等级分组展示

#### Scenario: 会话召回覆盖全局层

WHEN 项目会话里通过 MCP/HTTP recall 或 bootstrap 相关记忆段按 query 召回
THEN 该项目与全局层的洞察都参与召回，结果按项目分组展示（全局层按等级分组）

## ADDED Requirements

### Requirement: 召回覆盖全局层

面向会话的召回 SHALL 在指定项目时同时覆盖该项目与全局层，使全局层的 `[[evo:名字]]` 指路卡能在项目会话中被 query 命中，并顺 `insight→evolution` 边带出资产正文（正文按需加载，SHALL NOT 内联进卡片）。扩大候选集 SHALL NOT 改变打分公式（`alpha` 向量/关键词加权）、相似度阈值、`link_extra` 顺链限量与按资产名去重的既有规则。库内函数级默认（未显式开启）SHALL 保持「只召回该项目」，以维持既有调用方语义。

#### Scenario: 项目会话命中全局指路卡

WHEN 项目会话里 query 命中全局层的 `[[evo:code-laziness-ladder.md]]` 指路卡
THEN 召回结果包含该卡，并顺边带出 `code-laziness-ladder.md` 的当前版本正文

#### Scenario: 函数默认语义不变

WHEN 直接调用 `recall` 且未开启 `include_global`
THEN 只返回该项目的记忆，不含全局层记忆

#### Scenario: 打分与去重不变

WHEN 全局层记忆参与召回
THEN 打分公式与阈值不变，同一资产的正文在一次召回里仍只出现一份

#### Scenario: 无 query 不额外加载

WHEN 会话只做首轮全量注入（无 query）
THEN 【全局记忆】仍按既有上限与顺序注入，SHALL NOT 因本需求把资产正文或额外记忆内联进注入文本
