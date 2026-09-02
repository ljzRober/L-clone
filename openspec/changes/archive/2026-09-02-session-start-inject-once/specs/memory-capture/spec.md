## MODIFIED Requirements

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
