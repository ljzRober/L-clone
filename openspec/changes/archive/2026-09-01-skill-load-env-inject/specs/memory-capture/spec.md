## ADDED Requirements

### Requirement: 按环境加载记忆

bootstrap SHALL 根据会话环境决定加载范围：会话 `cwd` 落进**已知项目** → 注入【项目方向】(charter) +【项目记忆】(该项目近 project_limit 条洞察) +【全局记忆】；否则（无 cwd / 不在已知项目 / 全局会话）→ 只注入【全局记忆】。

#### Scenario: 项目会话加载

WHEN 会话 cwd 落进已知项目（detect_project_by_git 命中）
THEN bootstrap(--cwd) 注入 项目方向 + 项目记忆 + 全局记忆

#### Scenario: 全局会话加载

WHEN 会话不在已知项目（或无 cwd）
THEN bootstrap(不带项目) 只注入全局记忆

## MODIFIED Requirements

### Requirement: 分类加载

bootstrap 与 recall 加载记忆时 SHALL 按「项目」分组展示（全局层按等级分组），而非扁平列表；bootstrap 依据会话环境（`cwd` 是否落进已知项目）在【全局记忆】基础上决定是否额外加载【项目方向】与【项目记忆】。

#### Scenario: bootstrap 分类加载

WHEN bootstrap 加载相关记忆
THEN 按项目分组、项目内按等级列出；项目会话额外带【项目方向】+【项目记忆】

#### Scenario: recall 分类加载

WHEN recall 返回召回结果
THEN 按项目 → 等级分组展示
