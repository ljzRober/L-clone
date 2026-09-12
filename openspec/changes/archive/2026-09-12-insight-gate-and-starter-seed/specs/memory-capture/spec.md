## MODIFIED Requirements

### Requirement: 记忆分类与确认

lclone 的自动捕获 SHALL 把内容提炼为**洞察(insight)**，不再分级为记录(note)。**insight SHALL 是原子化、自包含、内容丰富的知识/见解/教训**——每条是一件事（一个决定 / 一条经验 / 一个观察 / 一条复盘），**按四段卡写成一行（约 2-4 句）：要点｜背景/为什么｜影响/以后注意｜归属**，让人能独立读懂，不是逐字记录（那是 git / spec），也不是一行干巴巴结论。

**准入 SHALL 先过确定性闸门（脚本优先，LLM 兜底）**。capture 前 SHALL 经 `_strip_ingest_noise` 剥离宿主注入的标签块（`<system-reminder>`/`<private>`/`<claude-mem-context>`/`<available_skills>`/`<injected>`/`<context>`）避免污染；随后 SHALL 由纯脚本闸门（`lclone/gate.py`，SHALL NOT 依赖 LLM）把用户轮文本判为 `skip` / `candidate` / `uncertain` 三档：

- `skip` SHALL 直接丢弃，且 **SHALL NOT 调用任何 LLM**；
- `candidate` SHALL 直接交 LLM 提炼成卡，SHALL NOT 额外判定；
- `uncertain` SHALL 先做一次极便宜的 yes/no 判定，判否即丢弃。

闸门判定 SHALL 只在**用户轮**（按 `用户：`/`助手：` 切分）上做；SHALL 遵循否定作用域（信号词前 3 字内出现 `不`/`没`/`无需`/`不用`/`取消` 时该命中不计）；用户显式要求（`记住`/`记一下`/`记下来`）SHALL 旁路闸门。落库前 SHALL 过 `_filter_item`（排除「做了什么」、过短琐碎丢弃），SHALL 再做向量去重与**归一化文本去重**（去空白标点后前 80 字相同视为重复），且单轮成卡 SHALL NOT 超过 2 条。insight 进 pending 待人工确认。

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
THEN 每条是一件事、按四段卡自带背景与后果（约 2-4 句），不逐字转录对话/代码，也不压成一行

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

WHEN 一次 capture 的 LLM 提炼结果超过 2 条 insight
THEN 只写入前 2 条，其余丢弃

#### Scenario: 归一化文本去重

WHEN 同一归属内已存在与待写入内容「去空白标点后前 80 字相同」的记忆（含 active 与 pending）
THEN 本次不写入

#### Scenario: 闸门可自测

WHEN 运行 `lclone gate "<文本>"`
THEN 打印判定档位、命中的信号词与判定理由，且不调用 LLM

## ADDED Requirements

### Requirement: 闸门标准单一来源

记忆准入的判定标准（信号词表、长度下限、单轮上限、否定作用域）SHALL 集中在 `lclone/gate.py` 的常量块，作为唯一标准源（SSOT）；其它模块 SHALL NOT 复制该词表（「做了什么」标记由 `gate.DID_MARKERS` 别名引用）。闸门模块 SHALL 只依赖标准库，SHALL NOT 依赖 `llm`/`db`/`config`，以便离线单测与跨宿主复用。

#### Scenario: 标准改动点唯一

WHEN 需要放宽或收紧准入
THEN 只改 `gate.py` 顶部常量即可生效，无需改动 capture 或提示词

#### Scenario: 离线可测

WHEN `BRAIN_LLM=dummy` 且无 API key
THEN 闸门判定与 `lclone gate` 命令仍可正常运行
