## MODIFIED Requirements

### Requirement: 决策强确认

每轮会话开始 bootstrap SHALL 带出【待确认决策】，会话进行中每轮回复前 SHALL 也检查【待确认决策】；存在待确认决策时，SHALL 主动用弹窗请用户逐条保留/删除，而非静默跳过。

#### Scenario: bootstrap 带出待确认

WHEN 存在 pending 决策
THEN bootstrap 输出包含【待确认决策】段

#### Scenario: 会话中逐轮检查

WHEN 会话进行中（后台插件持续捕获决策）
THEN 每轮回复前也检查【待确认决策】并弹窗确认，不只在会话开始

#### Scenario: 弹窗确认

WHEN 存在待确认决策
THEN 用工具弹窗（ask_user_question 等）请用户保留/删除，不用纯文本列表
