## MODIFIED Requirements

### Requirement: 会话开始加载 skill

lclone-memory-dsh SHALL 在插件加载时注册 lclone-memory 全量 skill（`ctx.skills.registerProvider`，读取已安装的 `~/.agents/skills/lclone-memory/SKILL.md`），并在**会话首轮**（第一个 user/message，`bootstrapped` Set 保证每会话一次）一次性运行 `lclone bootstrap --cwd <会话cwd>`，把【skill 全文】+【bootstrap 记忆】经 `agent.steer` 注入会话（完整 UserMessage 形状 + `source:{kind:'plugin'}`），**每会话仅注入一次**，不重复注入。注入内容按当前环境决定：`cwd` 落进已知项目 →【项目方向 + 项目记忆 + 全局记忆】；否则仅【全局记忆】。host 端 SHALL 声明 `inject=['skills','agents']`。skill 全文与记忆注入后主导整段会话。

#### Scenario: 注册全量 skill

WHEN 插件加载
THEN 通过 ctx.skills.registerProvider 注册 lclone-memory skill（读已安装 SKILL.md），skill 完整在场可被 agent 全量加载

#### Scenario: 不再注入记忆

WHEN 会话首轮注入完成
THEN 同一会话后续轮次不再重复注入记忆/重跑 bootstrap；每轮只 capture 记洞察

#### Scenario: 注册失败静默

WHEN 无法读取已安装 SKILL.md 或 registerProvider 抛错
THEN 静默记日志，不中断插件其余功能（capture / web 路由）

#### Scenario: 会话首轮注入一次

WHEN 会话产生第一个 user/message 且该会话未注入过
THEN 插件运行 bootstrap --cwd 并 steer 注入【skill 全文 + 记忆】；同一会话后续不再注入

#### Scenario: 项目会话注入

WHEN 会话 cwd 落进已知项目（detect_project_by_git 命中）
THEN bootstrap --cwd 注入 项目方向 + 项目记忆 + 全局记忆

#### Scenario: 全局会话注入

WHEN 会话不在已知项目（或无 cwd）
THEN bootstrap 只注入全局记忆
