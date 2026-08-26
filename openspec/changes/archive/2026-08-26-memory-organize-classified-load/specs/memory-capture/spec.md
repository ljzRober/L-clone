## ADDED Requirements

### Requirement: 记忆整理合并

lclone SHALL 提供整理(organize)能力：LLM 把「语义相近、说的是同一件事」的记忆合并成一条综合描述。合并 SHALL 不能跨区域——只能合并 同项目 + 同等级(decision/note) + 同模块 的记忆；跨项目/跨等级/跨模块的合并由代码强制校验拒绝。

#### Scenario: 语义合并

WHEN 用户触发整理
THEN LLM 找出语义相近的记忆并合成一条综合描述，覆盖各条要点不遗漏

#### Scenario: 不跨区域

WHEN LLM 返回的合并组跨项目、跨等级或跨模块
THEN 代码校验拒绝该组合并，不执行

### Requirement: 分类加载

bootstrap 与 recall 加载记忆时 SHALL 按「项目 → 模块」分组展示（全局层按等级分组），而非扁平列表。

#### Scenario: bootstrap 分类加载

WHEN bootstrap 加载相关记忆
THEN 按项目分组，项目内按模块分组列出

#### Scenario: recall 分类加载

WHEN recall 返回召回结果
THEN 按项目 → 模块分组展示
