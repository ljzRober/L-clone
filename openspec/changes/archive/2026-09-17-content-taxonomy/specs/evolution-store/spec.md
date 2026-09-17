## ADDED Requirements

### Requirement: 资产类型边界

进化资产（evolution）SHALL 只承载**数据与可执行产物**——脚本、工具、配置、数据表、密钥表等独立存在说明不了任何内容、只能被运行/加载/解析的文件。**说明性内容**（规范、准则、理由、观察、经验、模板、示例）SHALL 归 insight；可被检查的契约 SHALL 归 spec。系统 SHALL NOT 因为"正文太长、占注入体积"而把说明性内容移入 evolution。系统 SHALL 提供**只读巡检**（`lclone evolution audit`）按形态启发式列出疑似错位的资产，SHALL NOT 自动删除或改写它们（是否下架由用户显式决定）。

#### Scenario: 巡检列出疑似错位

WHEN 内容库里存在"以说明文为主"的资产（如带 markdown 标题的 `.md`）
THEN 巡检把它列出来并给出理由；已下架（墓碑）的资产不出现

#### Scenario: 脚本与纯数据不误报

WHEN 资产是可执行脚本（`.sh`/`.py`…）或纯数据文件（密钥表、JSON/YAML 配置）
THEN 巡检不把它列为疑似错位

#### Scenario: 巡检只读

WHEN 运行巡检
THEN 不产生新版本、不改动任何资产内容、不写本地缓存

#### Scenario: 不自动下架

WHEN 巡检发现疑似错位资产
THEN 仅提示；下架 SHALL 由用户显式执行 `evolution delete`（墓碑式，可 restore）
