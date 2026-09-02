# memory-capture Specification

## Purpose
TBD - created by archiving change memory-capture-model. Update Purpose after archive.
## Requirements
### Requirement: 记忆分类与确认

lclone 的自动捕获 SHALL 把内容提炼为**洞察(insight)**，不再分级为记录(note)。**insight SHALL 是原子化、自包含、内容丰富的知识/见解/教训**——每条是一件事（一个决定 / 一条经验 / 一个观察 / 一条复盘），**按四段卡写成一行（约 2-4 句）：要点｜背景/为什么｜影响/以后注意｜归属**，让人能独立读懂，不是逐字记录（那是 git / spec），也不是一行干巴巴结论。LLM 提炼前 SHALL 自筛；`capture` 前 SHALL 经 `_strip_ingest_noise` 剥离宿主注入的标签块（`<system-reminder>`/`<private>`/`<claude-mem-context>`/`<available_skills>`/`<injected>`/`<context>`）避免污染；落库前 SHALL 过 `_filter_item`（排除「做了什么」、过短琐碎丢弃）。insight 进 pending 待人工确认。

#### Scenario: 捕获记录

WHEN 分类器提炼出原子化的知识/见解/教训（决定/经验/观察/复盘）
THEN 写入 insight 且 status=pending，待用户确认

#### Scenario: 捕获决策

WHEN 分类器提炼出可跨会话复用的决策/规则/经验
THEN 写入 insight 且 status=pending，待用户确认

#### Scenario: 自筛低价值

WHEN LLM 判断内容无长期价值（过程性琐碎/一次性/显而易见/临时性）
THEN 不提炼，不打扰用户

#### Scenario: 排除做了什么

WHEN 内容命中「做了什么」标记（修复/重构/commit/fix/bug/迁移/回滚 等）
THEN 不记忆，归 git 或 spec

#### Scenario: 决策信号降级

WHEN 内容被判为 insight 但过短/空壳（< 4 字）
THEN 丢弃，不进待确认（note 降级通道已废弃）

#### Scenario: 琐碎丢弃

WHEN 内容过短（< 4 字）或空壳
THEN 不记忆

#### Scenario: 原子且丰富

WHEN 内容提炼为 insight
THEN 每条是一件事、按四段卡自带背景与后果（约 2-4 句），不逐字转录对话/代码，也不压成一行

#### Scenario: ingest 剥噪

WHEN capture 前文本含宿主注入的标签块（系统提示/私有/上下文）
THEN 经 _strip_ingest_noise 剥离后再提炼，避免污染洞察

### Requirement: 分工边界

代码改动/接口变化/新增端点/重构/修 bug SHALL 归 git；需求/场景/⚠️边界变化 SHALL 归 sp-spec（openspec）；lclone 记忆 SHALL 只留**洞察(insight)**（原子化的知识/见解/教训）与**记录(note)**（过程事实）。边界判定遵循试金石：**内容能否改写成一条带 WHEN/THEN 的 requirement**。能 → 归 spec；不能（是理由/权衡/过程事实/偏好/经验教训）→ 归记忆。**归属纪律**：若 insight 明确对应仓库内某具体 spec/文件，项目级记忆可标 `[[spec:id]]`/`[[src:path]]`（link, not copy，权威内容留在仓库）；全局级记忆无仓库上下文，不标此类链接（只有 `[[m:N]]`）。

#### Scenario: 分类器排除代码改动

WHEN 分类器遇到"做了什么改动"
THEN 不提炼成 insight 或 note

#### Scenario: 只留选择与约定

WHEN 分类器遇到"选了什么方案/定了什么规则/学到的经验教训"
THEN 提炼为 insight

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

### Requirement: 归属判定

自动捕获的项目归属 SHALL 优先按 git 检测；git 检测到仓库但未注册时 SHALL 自动注册项目；无 git 时 SHALL 问用户新建 project 或升到全局层，而非静默默认全局。

#### Scenario: git 优先

WHEN 会话所在 git 仓库匹配到已注册项目
THEN 记忆归该项目

#### Scenario: git 自动注册

WHEN git 检测到仓库但未匹配到已注册项目
THEN 自动注册项目（name=仓库 basename、path=仓库根、charter 留空）并把记忆归该项目

#### Scenario: 无 git 问用户

WHEN git 检测不到仓库
THEN 主动问用户新建 project（取名）还是升到全局层，不静默落全局

### Requirement: 记忆整理合并

lclone SHALL 提供整理(organize)能力：LLM 把「语义相近、说的是同一件事」的洞察合并成一条综合描述。合并 SHALL 不能跨区域——只能合并 同项目 + 同等级(insight) 的洞察；跨项目/跨等级的合并由代码强制校验拒绝。

#### Scenario: 语义合并

WHEN 用户触发整理
THEN LLM 找出语义相近的洞察并合成一条综合描述，覆盖各条要点不遗漏

#### Scenario: 不跨区域

WHEN LLM 返回的合并组跨项目或跨等级
THEN 代码校验拒绝该组合并，不执行

### Requirement: 分类加载

bootstrap 与 recall 加载记忆时 SHALL 按「项目」分组展示（全局层按等级分组），而非扁平列表；bootstrap 依据会话环境（`cwd` 是否落进已知项目）在【全局记忆】基础上决定是否额外加载【项目方向】与【项目记忆】。

#### Scenario: bootstrap 分类加载

WHEN bootstrap 加载相关记忆
THEN 按项目分组、项目内按等级列出；项目会话额外带【项目方向】+【项目记忆】

#### Scenario: recall 分类加载

WHEN recall 返回召回结果
THEN 按项目 → 等级分组展示

### Requirement: 删除项目

lclone SHALL 支持删除项目：删除为墓碑式（登记 project_removals，不删行/记忆，可撤销，记忆读取时跳过）。

#### Scenario: 删除项目

WHEN 用户删除项目
THEN 项目登记到 project_removals（墓碑式），从列表消失、记忆停止加载，数据保留可撤销

### Requirement: 自动调度 sp-spec

lclone-memory skill SHALL 在会话中检测 sp-spec 可用性（`~/.agents/skills/sp-spec` 存在）。检测到 sp-spec 时，出现构建性任务后 SHALL 默认自动加载 sp-spec 并运行 quick 模式（是否升级 full/debug 由 sp-spec 自决），无需用户手动 /sp-spec；未检测到 sp-spec 时，SHALL 仅在首次会话提醒用户安装 sp-spec（URL https://github.com/ljzRober/sp-spec），不重复提醒。

#### Scenario: 有 sp-spec 自动 quick

WHEN 会话中检测到 sp-spec 且进入构建性任务
THEN lclone 自动加载 sp-spec 并运行 quick 模式；sp-spec 自身按需升级 full/debug，用户不手动 /sp-spec

#### Scenario: 无 sp-spec 首次提醒

WHEN 未检测到 sp-spec 且为首次检测
THEN 提醒用户安装 sp-spec（https://github.com/ljzRober/sp-spec），且仅提醒一次，不重复

### Requirement: 洞察强确认

后台捕获产生 pending 洞察后，**呈现由宿主按端分派**：capture 输入 SHALL 含用户与助手文本（判断纳入「助手是否确认/落地」），分类器 SHALL 仅把被助手确认、落地或持续推进的用户选择/规则/经验提炼为 insight；DSH 宿主 SHALL 不用 agent.steer 劫持主 agent，改由客户端轮询宿主 `/api/lclone-decisions` 以 UI 弹窗/角标提示，用户经 `/api/lclone-review` 保留/删除（主 agent 全程不参与确认）；非 web 端 SHALL 由 bootstrap 每轮带出【待确认洞察】。

#### Scenario: bootstrap 带出待确认

WHEN 存在 pending 洞察
THEN bootstrap 输出包含【待确认洞察】段

#### Scenario: 会话中逐轮检查

WHEN turn/end 时探测到本轮产生了待确认洞察
THEN 判断基于该轮「用户 + 助手」交换；DSH 由客户端轮询呈现，非 web 端由 bootstrap 带出，均不再用 agent.steer 劫持主 agent

#### Scenario: 弹窗确认

WHEN DSH 客户端轮询到新增 pending 洞察
THEN 以 UI 弹窗（洞察内容 + 保留/删除/稍后按钮）+ 侧边栏角标提示用户，用户点击保留/删除经 `/api/lclone-review` 落地；主 agent 不参与确认

#### Scenario: 去重防循环

WHEN 客户端已提醒过某批 pending 洞察（其 id 已入 seen 集合）
THEN 该批不再重复弹窗；仅未见过的新 id 触发渲染，避免刷屏

#### Scenario: 判断纳入助手实现

WHEN turn/end 提交「用户 + 助手」整段交换
THEN 分类器判断用户提出的选择/规则是否被助手确认、落地或持续推进，仅提炼为 insight；未获回应/未落地的一律不提炼

### Requirement: 按环境加载记忆

bootstrap SHALL 根据会话环境决定加载范围，且**每会话只注入一次**：会话 `cwd` 落进**已知项目** → 注入【项目方向】(charter) +【项目记忆】(该项目近 project_limit 条洞察) +【全局记忆】；否则（无 cwd / 不在已知项目 / 全局会话）→ 只注入【全局记忆】。DSH 宿主由插件在会话首轮注入一次（`bootstrap --cwd`），不因后续轮次重复注入。

#### Scenario: 会话首轮注入一次

WHEN 会话首轮注入记忆
THEN DSH 插件运行 bootstrap --cwd 注入一次，同一会话不再重复注入

#### Scenario: 项目会话加载

WHEN 会话 cwd 落进已知项目（detect_project_by_git 命中）
THEN bootstrap(--cwd) 注入 项目方向 + 项目记忆 + 全局记忆

#### Scenario: 全局会话加载

WHEN 会话不在已知项目（或无 cwd）
THEN bootstrap(不带项目) 只注入全局记忆

### Requirement: 进化资产与链接

lclone SHALL 提供进化资产(evolution)——可复用脚本/工具，实践某个具体事物时沉淀、会话中反复修改、不再修改即稳定。存储 SHALL 分两种：项目无关的通用脚本/工具内容存记忆库本体(`content`)；项目内脚本只存路径引用(`ref`，内容留仓库、git 版本化)。每个 evolution SHALL 可被 1..N 个 insight 支撑（`insight→evolution` 链接）；脚本被改时 SHALL 用 `update_evolution` 同步最新版本。检索命中 insight 时 SHALL 顺 `insight→evolution` 边带出该资产。

#### Scenario: 沉淀 evolution

WHEN 实践中生成一个可复用脚本/工具（项目无关 或 项目内）
THEN 写入 evolutions（项目无关存 content；项目内存 ref），status=active

#### Scenario: insight 支撑 evolution

WHEN 一个 evolution 有 1..N 个 insight 阐明"为什么/教训"
THEN 建立 insight→evolution 链接，可被检索顺边带出

#### Scenario: 同步最新版本

WHEN 脚本后续被改（继续使用/迭代）
THEN update_evolution 同步 content/ref 到最新版本，status 可置 stable

