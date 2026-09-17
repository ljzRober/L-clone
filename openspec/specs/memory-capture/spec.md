# memory-capture Specification

## Purpose
TBD - created by archiving change memory-capture-model. Update Purpose after archive.
## Requirements
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

#### Scenario: 自包含性与归属

WHEN 卡片只有「要点」而缺「背景」与「影响」
THEN 不成卡（残卡离开原始对话读不懂）

WHEN 卡片不含「归属」段（该段已废弃）
THEN 照常成卡——归属由数据库 project_id 表达，不再作为结构性拒绝理由

### Requirement: 准入质量可测量

每次人工确认动作（keep / edit / delete / promote）SHALL 写入 `review_log` 留痕，且该留痕
SHALL NOT 随记忆删除而级联清理（`delete` 会真删 `memories` 行，留痕必须比被删的记忆活得久，
否则队列精确率永远算不出来）。系统 SHALL 提供**内部相对指标**：队列精确率
（`keep+edit+promote / 已拍板`）、每会话复核负担（窗口内新成卡 / 出现卡片的会话数）、
复用率（被召回过的 active 卡占比）；无数据时 SHALL 返回空值而不是 0，避免把"没数据"读成"精度为零"。

#### Scenario: 指标可算且语义诚实

WHEN 运行 `lclone stats [--days N]`
THEN 打印队列精确率、每会话复核负担、复用率，并在没有拍板留痕时说明"需要动作才可算"

#### Scenario: 删除不留痕则精确率失效

WHEN 用户以 delete 处理一张待确认卡
THEN 记忆行被删除，但 `review_log` 里的该条动作仍在，可被指标统计

#### Scenario: 归一化文本去重

WHEN 同一归属内已存在与待写入内容「去空白标点后前 80 字相同」的记忆（含 active 与 pending）
THEN 本次不写入

#### Scenario: 闸门可自测

WHEN 运行 `lclone gate "<文本>"`
THEN 打印判定档位、命中的信号词与判定理由，且不调用 LLM

### Requirement: 分工边界

内容归位 SHALL 按**用途**判定（不按篇幅）：代码改动/接口变化/新增端点/重构/修 bug 归 git；需求/场景/⚠️边界变化归 sp-spec（openspec）；**说明性内容**——规范、准则、理由/权衡、观察、经验教训、**模板与示例**——归 **insight**（lclone 记忆）；只有**数据与可执行产物**（脚本、工具、配置、密钥表等独立存在说明不了任何内容、只能被运行或解析的东西）才归 **evolution**。边界判定遵循试金石：**内容能否改写成一条带 WHEN/THEN 的 requirement**。能 → 归 spec；不能 → 归记忆。**insight 的注入正文 SHALL 自足**（规范类卡片必须写到"照着就能做"，SHALL NOT 只写"去做 X 前先读 Y"）；规范篇幅大时 SHALL 收进 skill 全文（注入层）或写成**一条**内容完整的长卡；同类规范 SHALL 合并成一条，SHALL NOT 拆成多条卡或多个文件。**SHALL NOT 为控制注入体积把规范/说明移出记忆放进 evolution**。**引用纪律**：若 insight 明确对应仓库内某具体 spec / 源文件 / 数据或脚本资产，项目级记忆 SHALL 把 `[[spec:id]]` / `[[src:path]]` / `[[evo:名字]]` **就地写在提到它的那句话里**（link, not copy，权威内容留在仓库）；SHALL NOT 另起一行做引用列表（同一资产写两遍会渲染出两个相同引用、召回时也会重复带出）。全局级记忆无仓库上下文，不标此类链接（只有 `[[m:N]]`）。

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

#### Scenario: 规范与说明归 insight

WHEN 内容是一条准则、一个规范、一段理由、一种做法或一份模板/示例
THEN 提炼为 insight（可被召回），SHALL NOT 建议或写入 evolution

#### Scenario: 规范卡注入正文自足

WHEN 一张规范类 insight 被注入会话
THEN 卡片正文自带可执行要点（照着就能做），不依赖再去取某个外部文档

#### Scenario: 不得为省体积外置规范

WHEN 规范内容较长、考虑"正文放内容库、卡片只留指针"
THEN 不这样做——SHALL 拆成多条原子 insight 或收进 skill 全文；把规范放进 evolution 视为违规

#### Scenario: 同类规范合并成一条

WHEN 存在多份同类执行规范（例如两份外部准则文档）
THEN 合并为**一条**自足 insight（可含多个要点），SHALL NOT 拆成多条卡或多个文件——拆分会让执行逻辑发散、后续维护分散

#### Scenario: 数据与脚本才用 evolution

WHEN 内容是可执行脚本、工具、配置或数据文件（独立存在说明不了内容）
THEN 用 evolution 发布到内容库，并可被 insight 以 `[[evo:名字]]` 就地引用

### Requirement: 归属判定

自动捕获的项目归属 SHALL 优先按 **git remote** 检测：客户端取仓库 `origin` 的远端地址并归一化为 `host/group/repo`（去协议与凭据、去尾 `.git`、去尾 `/`、host 小写、path 保留大小写），服务端 SHALL 按归一化 remote **精确匹配**已注册项目；无 remote（含 `remote` 列为空的历史项目）时 SHALL 回落按仓库根路径匹配（resolved 相等，或客户端上报路径的最长前缀）。git 检测到仓库但未注册时 SHALL 自动注册项目（`name`=仓库 basename、`path`=本次看到的仓库根、`remote`=归一化值，撞名沿用后缀去重）；无 git 时 SHALL 问用户新建 project 或升到全局层，而非静默默认全局。**当后端部署在与会话不同的机器上（记忆在服务器）时，git 检测 SHALL 由客户端（会话所在机器）执行并把解析出的 `remote` 与 `project_id` 随请求一并上报**——服务端看不到客户端路径，不得据此静默降级为全局层。客户端上报 `(remote, path)` 命中一个 `remote` 为空的既有项目时，SHALL 惰性回填该项目的 `remote`，SHALL NOT 因此新建项目。

#### Scenario: git 优先

WHEN 会话所在 git 仓库匹配到已注册项目
THEN 记忆归该项目

#### Scenario: git 自动注册

WHEN git 检测到仓库但未匹配到已注册项目
THEN 自动注册项目（name=仓库 basename、path=仓库根、remote=归一化远端地址、charter 留空）并把记忆归该项目

#### Scenario: 无 git 问用户

WHEN git 检测不到仓库
THEN 主动问用户新建 project（取名）还是升到全局层，不静默落全局

#### Scenario: 客户端解析归属（远程后端）

WHEN 后端部署在与会话不同的机器上（服务端看不到会话 cwd）
THEN 客户端按本地 git 仓库解析归属并把 `remote` 与 `project_id` 随 capture 上报：命中已注册项目则归该项目，未注册则先自动注册再归该项目；不得因服务端 no_git 而把记忆静默落进全局层

#### Scenario: MCP 显式归属（远程后端）

WHEN agent 经 MCP（HTTP）调用 capture/remember 且后端为远程
THEN 显式传 `project`，或传 `repo_remote` 使服务端按 remote 匹配；使归属不依赖服务端的 cwd 判定

#### Scenario: remote 优先于 path

WHEN 客户端上报的归一化 remote 与某已注册项目一致，而该项目的 path 与本次仓库根不同（换机器 / 换 clone 目录）
THEN 记忆归该既有项目，且不新建项目

#### Scenario: 无 remote 回落 path

WHEN 仓库没有任何 remote，而其仓库根匹配到已注册项目的 path
THEN 记忆归该项目

#### Scenario: remote 惰性回填

WHEN 客户端上报 `(remote, path)` 命中一个 `remote` 为空的既有项目
THEN 就地写入该 remote，项目 id 与既有记忆归属不变

#### Scenario: 同一 remote 跨机器收敛

WHEN 同一 remote 的仓库在两台机器上以不同本地路径被检测
THEN 两次都解析到同一个项目，不产生第二个项目

### Requirement: 记忆整理合并

lclone SHALL 提供整理(organize)能力：LLM 把「语义相近、说的是同一件事」的洞察合并成一条综合描述。合并 SHALL 不能跨区域——只能合并 同项目 + 同等级(insight) 的洞察；跨项目/跨等级的合并由代码强制校验拒绝。

#### Scenario: 语义合并

WHEN 用户触发整理
THEN LLM 找出语义相近的洞察并合成一条综合描述，覆盖各条要点不遗漏

#### Scenario: 不跨区域

WHEN LLM 返回的合并组跨项目或跨等级
THEN 代码校验拒绝该组合并，不执行

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

bootstrap SHALL 根据会话环境决定加载范围，且**每会话只注入一次**：会话归属落进**已知项目** → 注入【项目方向】(charter) +【项目记忆】(该项目近 project_limit 条洞察) +【全局记忆】；否则（无归属 / 不在已知项目 / 全局会话）→ 只注入【全局记忆】。会话归属 SHALL 由会话所在机器解析后随请求上报（`project_id`，或可归一化的 `repo_remote`）；服务端 SHALL NOT 依赖在服务器上对客户端路径执行 git 检测来决定是否加载项目记忆。`cwd` 参数 SHALL 仅作为未提供 `project_id`/`repo_remote` 时的向后兼容回落。DSH 宿主由插件在会话首轮注入一次，不因后续轮次重复注入。

#### Scenario: 会话首轮注入一次

WHEN 会话首轮注入记忆
THEN DSH 插件运行 bootstrap 注入一次，同一会话不再重复注入

#### Scenario: 项目会话加载

WHEN 会话归属落进已知项目
THEN bootstrap 注入 项目方向 + 项目记忆 + 全局记忆

#### Scenario: 全局会话加载

WHEN 会话不在已知项目（或无归属）
THEN bootstrap 只注入全局记忆

#### Scenario: 客户端解析归属（远程后端）

WHEN 后端在服务器上且会话 cwd 在某个已注册项目的 git 仓库内
THEN 插件在客户端解析出 `project_id` 并随 bootstrap 上报，服务端据此注入 项目方向 + 项目记忆 + 全局记忆

#### Scenario: 服务端无 git 不降级

WHEN 服务端无法对客户端路径执行 git 检测
THEN 仍按上报的 `project_id` / `repo_remote` 加载项目记忆，不静默只注入全局层

### Requirement: 进化资产与链接

lclone SHALL 提供进化资产(evolution)——可复用脚本/工具/模板，实践某个具体事物时沉淀、会话中反复修改、不再修改即稳定。**权威 SHALL 唯一：内容存储在服务器侧的版本化内容寻址库**（`evo_versions` 只追加 + `evo_current` 当前指针 + 以 `sha256` 命名的 blob），本地目录只是**可复现的缓存**；SHOULD NOT 出现"本机是唯一副本"的进化资产。存储 SHALL 分两种：项目无关的通用脚本/工具内容入内容库（`evo_versions.hash` 指向 blob）；项目内脚本只记路径引用（`ref`，内容留仓库、git 版本化，不入内容库）。每个 evolution SHALL 可被 1..N 个 insight 支撑（`insight→evolution` 链接）；脚本被改时 SHALL 用 `update_evolution` 发布**新版本**（append-only，旧版本保留可回滚），SHALL NOT 原地覆盖历史。检索命中 insight 时 SHALL 顺 `insight→evolution` 边带出该资产。

#### Scenario: 沉淀 evolution

WHEN 实践中生成一个可复用脚本/工具（项目无关 或 项目内）
THEN 发布一版：项目无关内容入内容寻址库并指向 blob；项目内只记 `ref` 引用

#### Scenario: insight 支撑 evolution

WHEN 一个 evolution 有 1..N 个 insight 阐明"为什么/教训"
THEN 建立 insight→evolution 链接，可被检索顺边带出

#### Scenario: 同步最新版本

WHEN 脚本后续被改（继续使用/迭代）
THEN update_evolution 发布新版本（版本号按历史最大版本递增，历史版本保留）

#### Scenario: 项目内脚本只存引用

WHEN evolution 以 `ref` 形式登记（内容在项目仓库）
THEN 索引只记引用，内容库不存 blob，本地同步清单不含该条目，读取时返回指向仓库路径的说明

### Requirement: 记忆矛盾检测

lclone SHALL 提供矛盾检测：扫描 active 洞察，找出语义相近（向量相似度 ≥ 阈值）的候选对，用 LLM 判定是否真矛盾（内容相反/规则改版/相冲突），输出 `{a, b, content_a, content_b, reason, hint}`。矛盾检测 SHALL 只提示候选、不自动改记忆，是否处理由用户决定（可经 review 删除/修订）。dummy 后端无法判定矛盾时 SHALL 返回"无候选/未发现矛盾"。

#### Scenario: 发现矛盾对

WHEN 一条新洞察与既有洞察语义相近且被 LLM 判为矛盾
THEN 输出该对 (id/内容/矛盾原因)，提示用户处理

#### Scenario: 只在有冲突才提示

WHEN 无矛盾候选或 LLM 判定无矛盾
THEN 空结果/未发现，不打扰用户

#### Scenario: 不自动改记忆

WHEN 检测到矛盾
THEN 仅提示，不自动删除/修订记忆；用户经 review 决定

#### Scenario: dummy 后端不判矛盾

WHEN 后端为 dummy（无真实 LLM）
THEN 返回"无候选/未发现矛盾"，不做矛盾判定

### Requirement: 闸门标准单一来源

记忆准入的判定标准（信号词表、长度下限、单轮上限、否定作用域、宿主注入块标记、用户轮证据阈值）SHALL 集中在 `lclone/gate.py` 的常量块，作为唯一标准源（SSOT）；其它模块 SHALL NOT 复制该词表（「做了什么」标记由 `gate.DID_MARKERS` 别名引用，「无内容」元响应词表由 `llm.EMPTY_RESPONSES`/`llm.NO_CONTENT_MARKERS` 承担）。闸门模块 SHALL 只依赖标准库，SHALL NOT 依赖 `llm`/`db`/`config`，以便离线单测与跨宿主复用。

#### Scenario: 标准改动点唯一

WHEN 需要放宽或收紧准入
THEN 只改 `gate.py` 顶部常量即可生效，无需改动 capture 或提示词

#### Scenario: 离线可测

WHEN `BRAIN_LLM=dummy` 且无 API key
THEN 闸门判定与 `lclone gate` 命令仍可正常运行

### Requirement: 跨层去重

记忆写入去重 SHALL 在**同域比较**之外支持**跨层扫描**，且跨层只扩大**扫描范围**，SHALL NOT 改变判重规则本身（向量相似度阈值 0.92、归一化文本「去空白标点后前 80 字相同」均不变）。扫描范围 SHALL 按「覆盖面」确定：写**项目层**记忆时 SHALL 同时比对全局层（全局层在任何会话都加载，语义等价即为重复）；写**全局层**记忆时 SHALL 仍只比对全局层，SHALL NOT 被任一项目层记忆阻断（项目层覆盖不到别的项目）；**首次种子内容**落库 SHALL 跨层比对全部层级。**扩大范围 SHALL NOT 被单一窗口截断**：跨层时各归属层级 SHALL 各自取各自的候选窗口，SHALL NOT 让 id 较小的层级（典型是全局层）被活跃项目挤出窗口而静默失去比对。本需求覆盖**自动捕获与种子落库**两条写入路径；`remember()`（用户显式记录通道）SHALL NOT 因此改变既有语义。

#### Scenario: 项目卡与全局卡同义

WHEN 自动捕获路径向项目层写入一条与全局层既有记忆语义等价（或归一化文本相同）的洞察
THEN 不写入，判定为重复（全局层已覆盖该内容）

#### Scenario: 项目层活跃不挤掉全局层

WHEN 目标项目已有大量记忆（超过单个候选窗口），而全局层存在一条与待写入内容等价的记忆
THEN 仍判定为重复——各层各自取窗口，全局层不因项目层活跃而被挤出比对范围

#### Scenario: 全局卡不被项目卡阻断

WHEN 全局层写入一条与某项目层既有记忆等价的洞察
THEN 仍按全局层范围内的判重结果决定，项目层记忆不构成阻断理由

#### Scenario: 种子跨层查重

WHEN 首次种子内容与库里任一层级（全局层或任一项目层）的既有记忆等价
THEN 该条不种入，报告为 skipped，且不产生重复行

#### Scenario: 判重规则不变

WHEN 需要收紧或放宽重复判定
THEN 改的仍是向量阈值与归一化文本规则；跨层开关只决定扫描哪些归属层级

### Requirement: 进化资产反向引用可查

系统 SHALL 支持**反向**查询「哪些洞察引用了某进化资产」：以 `[[evo:文件名]]` **精确匹配**（SHALL NOT 做大小写放宽或模糊匹配），只返回 `status='active'` 的 insight，并 SHALL 带出该 insight 的 `project_id` 与项目名，供看板与工具直接消费。反向引用 SHALL 是**只读派生视图**——读取 SHALL NOT 发布版本、写入本地缓存或改动资产内容。

#### Scenario: 反查引用者

WHEN 查询某资产名被哪些洞察引用
THEN 返回引用它的 active 洞察（含 id / project_id / project_name），pending 与已删除的不出现

#### Scenario: 精确匹配

WHEN 洞察正文写的是 `[[evo:a.py]]` 而查询名是 `b.py`
THEN 不匹配，不返回该洞察

#### Scenario: 只读派生

WHEN 看板读取反向引用
THEN 不产生新版本、不写本地缓存、不改动资产内容

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

### Requirement: 项目身份与重复探测

项目身份 SHALL 由归一化 git remote 表达；本地路径 SHALL 只作为「最近一次看到的位置」提示（单列，后写覆盖），SHALL NOT 作为身份键。系统 SHALL 提供**只读**的重复项目探测：按归一化 remote 分组，列出同一 remote 下的多个项目及其记忆数；探测 SHALL NOT 自动改动任何数据。合并 SHALL 由显式动作触发，且 SHALL 在一个事务内完成：把源项目的 `memories.project_id` 与 `specs_index.project_id` 改挂目标项目、给源项目登记墓碑（复用 `project_removals`，不物理删除），并在合并前产出可回滚备份；`specs_index` 的 `UNIQUE(project_id, rel_path)` 冲突 SHALL 保留目标项目既有行、丢弃源重复行并计入报告。

#### Scenario: 重复可探测

WHEN 库中存在归一化 remote 相同的两个项目
THEN 探测报告把它们列为一组（含各自 id/name/path/mem_count），且不修改任何数据

#### Scenario: 显式合并

WHEN 用户显式要求把源项目合并到目标项目
THEN 源项目的记忆与 spec 索引改挂目标项目、源项目登记墓碑，且合并前已产出可回滚备份

#### Scenario: path 不作身份

WHEN 同一 remote 的仓库在两个不同本地路径被检测
THEN 不产生第二个项目（path 只更新为最近一次看到的位置）

#### Scenario: 合并可回滚

WHEN 用户用合并产出的备份执行回滚
THEN 记忆与 spec 索引的 project_id 恢复为合并前的值，源项目墓碑被撤销

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

### Requirement: 资产类型边界

系统 SHALL 把 evolution 的用途限制为**数据与可执行产物**（脚本 / 工具 / 配置 / 数据表 / 密钥表等）。系统 SHALL 提供**只读**巡检能力（`lclone evolution audit`），按形态启发式列出疑似说明性文档的资产并给出理由，SHALL NOT 自动删除或改写任何资产（删除由用户显式决定，与 suggest 同纪律）。首次种子内容 SHALL NOT 包含说明性文档（种子只含通用洞察与脚本类资产）。

#### Scenario: 巡检只提示

WHEN 运行 `lclone evolution audit`
THEN 列出疑似说明性文档的资产（含名字/类型/大小/理由），不修改任何数据

#### Scenario: 脚本与数据不误报

WHEN 资产是 `.sh` 脚本或纯数据文件（如密钥表）
THEN 巡检不把它列为疑似错位

#### Scenario: 种子不含说明性文档

WHEN 在空库执行首次种子
THEN 只种入通用洞察与脚本类进化资产，不种入任何说明性 `.md`

