## MODIFIED Requirements

### Requirement: 看板刷新

lclone-memory-dsh SHALL 在全屏看板顶栏提供主色「刷新」按钮（带图标），点击后重新加载看板 iframe（重新拉取后端记忆工作台数据）并刷新健康状态指示；**面板每次由关闭切到打开时 SHALL 同样重新加载 iframe**，使用户刚写入的记忆无需手动点击刷新即可看到（iframe 常驻挂载，不重新赋值 src 会一直停留在上一次的快照）。

#### Scenario: 点击刷新

WHEN 点击看板顶栏「刷新」按钮
THEN iframe 重新加载后端看板数据，健康状态指示同步刷新

#### Scenario: 离线时刷新

WHEN 看板离线（后端未启动）且点击刷新
THEN 重新探测健康状态并保持离线提示（不残留旧空白 iframe）

#### Scenario: 打开面板自动重新拉取

WHEN 看板面板由关闭切到打开（此前已加载过）
THEN iframe 重新加载以拉取最新记忆列表，刚 capture 进去的记忆立即可见；首次打开不重复加载

## ADDED Requirements

### Requirement: 捕获请求超时与回调去重

lclone-memory-dsh 的每轮 capture SHALL 允许不少于 30 秒的等待（capture 会触发一次 LLM 提炼，实测 4 秒以上），且同一请求的超时/错误路径 SHALL 只回调一次——避免出现「服务端已落库、客户端报 fail 并丢掉记录 ids」以及日志重复记两行 fail。

#### Scenario: 提炼慢于旧超时不误报失败

WHEN 后端 capture 的提炼耗时超过 3 秒但小于 30 秒
THEN 客户端继续等待并正常拿到记录 ids，不误报失败

#### Scenario: 超时与错误只回调一次

WHEN 同一请求同时触发 timeout 与 error
THEN 完成回调只被调用一次，日志不出现重复的 fail 行
