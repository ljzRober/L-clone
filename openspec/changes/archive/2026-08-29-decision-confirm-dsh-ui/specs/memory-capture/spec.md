# memory-capture Delta

## MODIFIED Requirements

### Requirement: 决策强确认

后台捕获产生 pending 决策后，**呈现由宿主按端分派**：capture 输入 SHALL 含用户与助手文本（判断纳入「助手是否确认/落地」），分类器 SHALL 仅把被助手确认、落地或持续推进的用户选择/规则提炼为 decision；DSH 宿主 SHALL 不用 agent.steer 劫持主 agent，改由客户端轮询宿主 `/api/lclone-decisions` 以 UI 弹窗/角标提示，用户经 `/api/lclone-review` 保留/删除（主 agent 全程不参与确认）；非 web 端 SHALL 由 bootstrap 每轮带出【待确认决策】。

#### Scenario: bootstrap 带出待确认

WHEN 存在 pending 决策
THEN bootstrap 输出包含【待确认决策】段

#### Scenario: 会话中逐轮检查

WHEN turn/end 时探测到本轮产生了待确认决策
THEN 判断基于该轮「用户 + 助手」交换；DSH 由客户端轮询呈现，非 web 端由 bootstrap 带出，均不再用 agent.steer 劫持主 agent

#### Scenario: 弹窗确认

WHEN DSH 客户端轮询到新增 pending 决策
THEN 以 UI 弹窗（决策内容 + 保留/删除/稍后按钮）+ 侧边栏角标提示用户，用户点击保留/删除经 `/api/lclone-review` 落地；主 agent 不参与确认

#### Scenario: 去重防循环

WHEN 客户端已提醒过某批 pending 决策（其 id 已入 seen 集合）
THEN 该批不再重复弹窗；仅未见过的新 id（或用户处理失败未入 seen 的 id）触发渲染，避免刷屏

#### Scenario: 判断纳入助手实现

WHEN turn/end 提交「用户 + 助手」整段交换
THEN 分类器判断用户提出的选择/规则是否被助手确认、落地或持续推进，仅提炼为 decision；未获回应/未落地的一律不提炼
