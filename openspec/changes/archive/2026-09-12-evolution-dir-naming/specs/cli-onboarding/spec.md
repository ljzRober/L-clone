## MODIFIED Requirements

### Requirement: 首次种子内容

lclone SHALL 在首次部署后端时种入一份**通用**种子内容，让空库用户立刻看到「一条洞察长什么样、进化资产怎么用」：

- **通用洞察** 4 条，SHALL 落全局层（`project_id IS NULL`）、`status='active'`、`source_type='seed'`，且 **SHALL NOT 进 pending 待确认**（它是预置内容，不是捕获来的草稿）；
- **通用进化文件**（洞察格式模型 / 记忆准入标准 / 会话归属与落库约定 + 示例脚本），SHALL 走**版本化发布**写入进化资产库（详见 `evolution-store`），并物化到记忆区进化缓存目录（默认 `~/.lclone/evolution/`，可用 `LCLONE_EVO_DIR` 覆盖——该目录只是可复现缓存，容器化部署无需持久化）。种子 SHALL NOT 绕开版本库直接写文件。

种子内容 SHALL NOT 绑定具体项目，SHALL NOT 依赖具体 provider；`BRAIN_LLM=dummy` 下 SHALL 仍可种入。种子 SHALL NOT 覆盖记忆中已存在的等价内容，也 SHALL NOT 覆盖已存在的进化资产（含已在版本库中的名字、以及缓存目录里的同名文件）。种子内容 SHALL 与代码分离存放（`lclone/data/starter/`），以便非开发者增删条目。部署时若进化缓存目录已有存量文件，lclone SHALL 提供把它们摄入为 v1 的迁移能力（详见 `evolution-store`）。

#### Scenario: 首次种入

WHEN 在一个空库上运行 `lclone setup`
THEN 写入 4 条全局通用洞察与通用进化文件，并报告种入条数

#### Scenario: 全局层且直接生效

WHEN 种子洞察写入
THEN `project_id IS NULL`、`status='active'`、`source_type='seed'`，不出现在待确认列表、不弹确认框

#### Scenario: 不覆盖既有内容

WHEN 进化目录下已存在同名文件（用户改过）
THEN 种子不覆盖它，只在报告中计入跳过

#### Scenario: 离线可种

WHEN `BRAIN_LLM=dummy` 且无 API key
THEN 种子洞察仍可写入（embedding 走本地确定性哈希向量）

#### Scenario: 种子进化文件进版本库

WHEN 种子种入通用进化文件
THEN 它们以 v1 进入进化资产库（可被 `history` 查到、可被客户端 `pull` 到），而不是只存在于某台机器的目录里

#### Scenario: 升级时摄入存量资产

WHEN 进化缓存目录里已有版本库中不存在的文件（旧版本升级上来的情况）
THEN 迁移能力把它们摄入为 v1（并按扩展名记好类型），且重复执行幂等
