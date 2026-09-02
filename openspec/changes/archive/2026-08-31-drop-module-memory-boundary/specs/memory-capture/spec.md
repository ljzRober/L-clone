## MODIFIED Requirements

### Requirement: 分工边界

代码改动/接口变化/新增端点/重构/修 bug SHALL 归 git；需求/场景/⚠️边界变化 SHALL 归 sp-spec（openspec）；lclone 记忆 SHALL 只留决策（选型/约定）与记录（过程事实）。

边界判定 SHALL 遵循一条试金石：**内容能否改写成一条带 WHEN/THEN 的 requirement**。能 → 归 spec；不能（是理由/权衡/过程事实/偏好/时间点）→ 归项目记忆。

半契约半理由的内容 SHALL 拆开而非塞进单一桶：理由部分归记忆，契约部分归 spec。

升格规则：当"选了什么方案"进一步被锁定为"系统必须满足什么"且能写成 WHEN/THEN requirement 时，才在 spec 建/改这条 requirement；此时 SHALL 在记忆里写入指向该 spec 的引用（`[[spec:id]]`），或删除该记忆条让 spec 成为唯一权威，避免双份漂移。

#### Scenario: 分类器排除代码改动

WHEN 分类器遇到"做了什么改动"
THEN 不提炼成 decision 或 note

#### Scenario: 只留选择与约定

WHEN 分类器遇到"选了什么方案/定了什么规则"
THEN 提炼为 decision

#### Scenario: 契约归 spec

WHEN 内容是"系统必须满足的契约"（可改写为带 WHEN/THEN 的 requirement）
THEN 不进 lclone 记忆，归 sp-spec（openspec）

#### Scenario: 理由归记忆

WHEN 内容是"为什么这么选/观察到什么"（无法写成 WHEN/THEN requirement）
THEN 写入项目记忆

#### Scenario: 半契约半理由拆分

WHEN 一条内容既含理由又含契约
THEN 理由归记忆、契约归 spec，不整体塞进单一桶

#### Scenario: 记忆升格为 spec

WHEN 一条记忆进一步被锁定为"系统必须满足 X"且能写成 WHEN/THEN requirement
THEN 在 spec 建/改该 requirement；原记忆写入 `[[spec:id]]` 引用或删除，避免与 spec 双份漂移

### Requirement: 记忆整理合并

lclone SHALL 提供整理(organize)能力：LLM 把「语义相近、说的是同一件事」的记忆合并成一条综合描述。合并 SHALL 不能跨区域——只能合并 同项目 + 同等级(decision/note) 的记忆；跨项目/跨等级的合并由代码强制校验拒绝。

#### Scenario: 语义合并

WHEN 用户触发整理
THEN LLM 找出语义相近的记忆并合成一条综合描述，覆盖各条要点不遗漏

#### Scenario: 不跨区域

WHEN LLM 返回的合并组跨项目或跨等级
THEN 代码校验拒绝该组合并，不执行

### Requirement: 分类加载

bootstrap 与 recall 加载记忆时 SHALL 按「项目」分组展示（全局层按等级分组），而非扁平列表。

#### Scenario: bootstrap 分类加载

WHEN bootstrap 加载相关记忆
THEN 按项目分组、项目内按等级列出

#### Scenario: recall 分类加载

WHEN recall 返回召回结果
THEN 按项目 → 等级分组展示

## ADDED Requirements

### Requirement: 删除项目

lclone SHALL 支持删除项目：删除为墓碑式（登记 project_removals，不删行/记忆，可撤销，记忆读取时跳过）。

#### Scenario: 删除项目

WHEN 用户删除项目
THEN 项目登记到 project_removals（墓碑式），从列表消失、记忆停止加载，数据保留可撤销

## REMOVED Requirements

### Requirement: 模块归属
**Reason**: module 轴被移除——它只服务单项目、与 spec 词表漂移、产生空模块与「core」垃圾桶；项目内二级划分改由记忆引用 spec（`[[spec:id]]`）承担。
**Migration**: 既有 module 标签在迁移时丢弃，相关决策保留为项目层记忆（level 不变）。

### Requirement: 删除项目与模块
**Reason**: 模块删除随 module 轴移除而删除，仅保留项目（墓碑式）删除。
**Migration**: 原"删除模块连带删除该模块下所有决策记忆"行为不再需要；项目删除语义不变。
