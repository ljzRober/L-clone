## MODIFIED Requirements

### Requirement: 决策强确认

后台捕获产生 pending 决策后，宿主插件 SHALL 在 turn/end 时用 agent.steer 强制注入一条引导消息（source=plugin，不显示成用户消息）唤醒 agent；agent 被唤醒后 SHALL 用 ask_user_question 逐条弹窗请用户保留/删除，而非静默跳过；bootstrap SHALL 每轮带出【待确认决策】。

#### Scenario: bootstrap 带出待确认

WHEN 存在 pending 决策
THEN bootstrap 输出包含【待确认决策】段

#### Scenario: 会话中逐轮检查

WHEN turn/end 时探测到新增 pending 决策
THEN 宿主插件用 agent.steer 注入引导消息唤醒 agent（代码强制，不靠 agent 自觉）

#### Scenario: 弹窗确认

WHEN agent 被唤醒且存在待确认决策
THEN 用 ask_user_question 逐条弹窗请用户保留/删除，阻塞等用户拍板

#### Scenario: 去重防循环

WHEN pending 数未增加
THEN 不重复注入，避免 agent 自身响应轮造成死循环
