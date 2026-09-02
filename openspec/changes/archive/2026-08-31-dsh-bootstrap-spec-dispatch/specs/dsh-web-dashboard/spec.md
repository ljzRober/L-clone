## ADDED Requirements

### Requirement: 会话开始注入

lclone-memory-dsh SHALL 在会话首个 turn 时运行 `lclone bootstrap ""` 并经 `agent.steer({source:{kind:'plugin'}})` 把返回文本注入当前会话上下文，实现"全局思维先介入"的确定性触发；每会话仅注入一次，不重复。host 端 SHALL 声明 `inject=['agents']` 以访问 `ctx.agents`。

#### Scenario: 会话首轮注入

WHEN 新会话首个 turn（turn/start 或首个 user/message）触发
THEN 插件运行 bootstrap 并经 agent.steer(source plugin) 注入返回文本到该会话上下文，且该会话不重复注入

#### Scenario: 注入失败静默

WHEN bootstrap 无输出或 agent/steer 不可用
THEN 静默记日志，不中断会话，不重复注入
