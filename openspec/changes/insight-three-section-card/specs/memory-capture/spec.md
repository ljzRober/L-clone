## MODIFIED Requirements

### Requirement: 记忆分类与确认

lclone 的自动捕获 SHALL 把内容提炼为**洞察(insight)**，不再分级为记录(note)。**insight SHALL 是原子化、自包含、内容丰富的知识/见解/教训**——每条是一件事（一个决定 / 一条经验 / 一个观察 / 一条复盘），**按三段卡写成一行（约 2-4 句）：要点｜背景/为什么｜影响/以后注意**；指向进化资产 / 契约 / 源文件的引用 SHALL **就地写在提到它的那句话里**（`[[evo:名字]]` / `[[spec:标识]]` / `[[src:路径]]`），SHALL NOT 另起一行做引用列表，让人能独立读懂，不是逐字记录（那是 git / spec），也不是一行干巴巴结论。

**准入 SHALL 先过确定性闸门（脚本优先，LLM 兜底）**。capture 前 SHALL 经 `_strip_ingest_noise` 剥离宿主注入的标签块（`<system-reminder>`/`<private>`/`<claude-mem-context>`/`<available_skills>`/`<injected>`/`<context>`）避免污染；随后 SHALL 由纯脚本闸门（`lclone/gate.py`，SHALL NOT 依赖 LLM）把用户轮文本判为 `skip` / `candidate` / `uncertain` 三档：

- `skip` SHALL 直接丢弃，且 **SHALL NOT 调用任何 LLM**；
- `candidate` SHALL 直接交 LLM 提炼成卡，SHALL NOT 额外判定；
- `uncertain` SHALL 先做一次极便宜的 yes/no 判定，判否即丢弃。

闸门判定 SHALL 只在**用户轮**（按 `用户：`/`助手：` 切分）上做，且 SHALL 先剥掉**宿主注入块**（插件注入的 skill 全文 / bootstrap 记忆区，行首标记见 `gate.INJECTION_HEADS`）再判定——注入块不是用户说的话，其自带的触发词（skill 描述里的「记住」「记一下」与工具表里的 `remember`）SHALL NOT 命中显式要求旁路；SHALL 遵循否定作用域（信号词前 3 字内出现 `不`/`没`/`无需`/`不用`/`取消` 时该命中不计）；用户显式要求（`记住`/`记一下`/`记下来`）SHALL 旁路闸门；命中**短时性措辞**（`gate.EPHEMERAL_MARKERS`：这次/今天/目前/临时/`for now`/`today` …）且**未命中决策或教训信号**时 SHALL 判为 `skip`（可重测的近况不入库），命中决策信号的句子 SHALL NOT 因短时措辞被丢弃。落库前 SHALL 过 `_filter_item`（排除「做了什么」、过短琐碎丢弃、排除「无内容」元响应与元报告回声），SHALL 再做向量去重与**归一化文本去重**（去空白标点后前 80 字相同视为重复），且单轮成卡 SHALL NOT 超过 1 条（默认一条都不产出）。**auto 通道的卡片 SHALL 过「用户轮证据」**（`gate.has_user_evidence`：卡片主张要在用户轮里有出处，助手单方面查出的环境近况与通用常识不成卡）；用户显式要求记忆的轮次 SHALL 豁免该证据检查。**卡片形状 SHALL 满足自包含性**：必须含「要点」段且至少含「背景」或「影响」之一（只有一句结论的残卡不收）。insight 进 pending 待人工确认。

#### Scenario: 捕获记录

WHEN 分类器提炼出原子化的知识/见解/教训（决定/经验/观察/复盘）
THEN 写入 insight 且 status=pending，待用户确认

#### Scenario: 捕获决策

WHEN 分类器提炼出可跨会话复用的决策/规则/经验
THEN 写入 insight 且 status=pending，待用户确认

#### Scenario: 自筛低价值

WHEN 闸门判定为 skip（有效文本过短 / 剥掉代码块后无自然语言 / 命中「做了什么」 / 疑问句 / 短句寒暄）
THEN 不提炼、不落库，且不调用 LLM，不打扰用户

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
THEN 每条是一件事、按三段卡自带背景与后果（约 2-4 句），不逐字转录对话/代码，也不压成一行

#### Scenario: ingest 剥噪

WHEN capture 前文本含宿主注入的标签块（系统提示/私有/上下文）
THEN 经 _strip_ingest_noise 剥离后再提炼，避免污染洞察

#### Scenario: 闸门跳过不调 LLM

WHEN 闸门判定为 skip
THEN capture 不调用 extract_memories、不调用 judge_insight，直接返回空结果

#### Scenario: 闸门只看用户轮

WHEN 文本含 `用户：…` 与 `助手：…` 两轮，且只有助手轮含「修复/重构」等噪声
THEN 闸门只在用户轮上判定，助手轮内容不影响判定结果

#### Scenario: 否定作用域

WHEN 文本出现「这个不用统一」这类被否定的信号词
THEN 该信号不计命中，判定不因它升级为 candidate

#### Scenario: 显式要求旁路

WHEN 用户显式说「记住」/「记一下」/「记下来」
THEN 旁路闸门（长度与噪声都不拦），直接按 candidate 处理

#### Scenario: 单轮成卡上限

WHEN 一次 capture 的 LLM 提炼结果超过 1 条 insight
THEN 只写入第 1 条，其余丢弃（默认一条都不产出，上限不是配额）

#### Scenario: 注入块不算用户轮

WHEN capture 文本里含宿主注入块（`【lclone-memory skill 全文】` / `【记忆】`）
THEN 判定前剥掉该块；即便块内含「记住」「记一下」`remember` 也不按显式要求旁路

#### Scenario: 用户轮证据

WHEN auto 通道提炼出的卡片主张在用户轮里找不到出处（助手自己排查出的环境近况、通用常识）
THEN 不成卡、不进待确认；用户显式说「记一下」的轮次豁免此检查

#### Scenario: 无内容元响应不成卡

WHEN 提炼器回「空」「无」`none` 这类空哨兵，或回一段带解释的「空」（未提炼任何卡片）
THEN 一条都不落库，也不进待确认

#### Scenario: 卡片形状校验

WHEN 提炼结果缺少三段卡标题（要点/背景·为什么/影响·以后注意）
THEN 视为元报告或对输入的回声，不成卡

#### Scenario: 短时性措辞不收

WHEN 用户轮命中短时性措辞（这次/今天/目前/临时）且没有决定性信号
THEN 判为 skip，不调 LLM、不落库（可重测的近况）

WHEN 同一句里还命中了决策/规则/教训信号
THEN 短时性措辞不作数，仍按 candidate 处理

#### Scenario: 自包含性

WHEN 卡片只有「要点」而缺「背景」与「影响」
THEN 不成卡（残卡离开原始对话读不懂）

WHEN 卡片不含「归属」段（该段已废弃）
THEN 照常成卡——归属由数据库 project_id 表达，不再作为结构性拒绝理由

### Requirement: 分工边界

代码改动/接口变化/新增端点/重构/修 bug SHALL 归 git；需求/场景/⚠️边界变化 SHALL 归 sp-spec（openspec）；lclone 记忆 SHALL 只留**洞察(insight)**（原子化的知识/见解/教训）。边界判定遵循试金石：**内容能否改写成一条带 WHEN/THEN 的 requirement**。能 → 归 spec；不能（是理由/权衡/过程事实/偏好/经验教训）→ 归记忆。**引用纪律**：若 insight 明确对应仓库内某具体 spec / 源文件 / 进化资产，项目级记忆 SHALL 把 `[[spec:id]]` / `[[src:path]]` / `[[evo:名字]]` **就地写在提到它的那句话里**（link, not copy，权威内容留在仓库）；SHALL NOT 另起一行做引用列表（同一资产写两遍会渲染出两个相同引用、召回时也会重复带出）。全局级记忆无仓库上下文，不标此类链接（只有 `[[m:N]]`）。

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

## ADDED Requirements

### Requirement: 引用去重

指向同一进化资产的引用 SHALL 在**一次召回**里只出现一次：一张洞察重复提及同一资产（例如正文里写了两遍 `[[evo:名字]]`）时，`insight→evolution` 边 SHALL 按资产名去重；召回顺边带出资产内容时 SHALL NOT 返回同一资产的多个副本。去重键 SHALL 为**资产名**（不是版本号或内容哈希——同一资产的不同版本仍是同一资产）。

#### Scenario: 同一张卡重复提及同一资产

WHEN 一张洞察正文里出现两遍 `[[evo:tool.sh]]`
THEN 反查与召回都只把它算作一次引用

#### Scenario: 两张卡指向同一资产

WHEN 两条洞察各自引用 `[[evo:tool.sh]]`
THEN 该资产的引用计数为 2（两条各算一次），但召回带出的资产内容仍只有一份

#### Scenario: 同资产不同版本不算不同资产

WHEN 同一资产已发布 v1 与 v2，洞察引用的是该资产名
THEN 去重按名称进行，不因版本不同而重复带出

### Requirement: 引用就地化

`evolution_add` / `link_insight_to_evolution` 把一条**既有洞察**关联到某进化资产时，SHALL 把引用**就地追加**进卡片正文，SHALL NOT 在正文末尾另起一行：目标卡含「影响/以后注意」段时 SHALL 追加到该行的末尾（形如 `（关联资产：[[evo:名字]]）`），卡片行数 SHALL NOT 改变；目标卡没有该段时 SHALL 追加到**最后一个非空行**的末尾。重复关联同一资产 SHALL 幂等（卡片内容不变）。

#### Scenario: 建链不新起行

WHEN 通过 `evolution_add` / `link_insight_to_evolution` 把一个既有洞察关联到某资产
THEN 引用追加在「影响/以后注意」那一行的末尾（形如 `（关联资产：[[evo:名字]]）`），卡片行数不变

#### Scenario: 缺段兜底

WHEN 目标卡没有「影响/以后注意」段
THEN 追加到最后一个非空行末尾，SHALL NOT 新起一行

### Requirement: 全局层注入上限

会话首轮 bootstrap 注入【全局记忆】时 SHALL 最多注入最新 100 条全局洞察（默认 `global_limit=100`）；项目层上限 SHALL 保持 20 条不变；「每会话只注入一次」的既有语义 SHALL NOT 改变。

#### Scenario: 默认上限 100

WHEN 会话首轮 bootstrap 注入【全局记忆】
THEN 最多注入最新 100 条全局洞察；项目层仍为 20 条，且「每会话只注入一次」的语义不变
