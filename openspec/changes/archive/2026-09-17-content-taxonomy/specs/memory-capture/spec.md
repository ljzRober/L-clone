## MODIFIED Requirements

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

## ADDED Requirements

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
