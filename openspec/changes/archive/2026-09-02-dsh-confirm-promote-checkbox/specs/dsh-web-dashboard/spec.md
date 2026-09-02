## MODIFIED Requirements

### Requirement: 决策确认 UI

DSH 洞察确认 SHALL 由客户端表达（不进主 agent）：`client.js` SHALL 轮询 host `/api/lclone-decisions` 获取待确认洞察，检测到新增时以弹窗（洞察内容 + 保留/删除/稍后按钮）与侧边栏角标呈现；**若为项目级待确认洞察，弹窗在按钮上方 SHALL 提供一个「提升至全局记忆」勾选框**（默认不勾选）。用户勾选后点「保留」→ 后端一步执行 `promote`（提升到全局层 project_id=NULL 并确认落地 status=active）；不勾选点「保留」→ 仅在项目级落地。用户点击保留/删除 SHALL 经 `/api/lclone-review` 提交（host 代理到 lclone `/api/review`），「稍后」SHALL 把该洞察留作工作台 pending。

#### Scenario: 新增待确认弹窗

WHEN 客户端轮询到 id 未见过（未入 seen）的待确认洞察
THEN 渲染弹窗（洞察内容 + 保留/删除/稍后）+ 更新侧边栏角标计数，主 agent 不参与

#### Scenario: 保留/删除落地

WHEN 用户点击弹窗「保留」或「删除」
THEN 客户端 POST /api/lclone-review {id, action}，成功后弹窗移除该条并刷新角标

#### Scenario: 提升到全局落地

WHEN 项目级待确认洞察勾选了「提升至全局记忆」并点击「保留」
THEN 客户端 POST /api/lclone-review {id, action:'promote'}，后端把该洞察提升到全局层(project_id=NULL)并确认落地(active)；弹窗移除该条并刷新角标

#### Scenario: 不勾选保留于项目级

WHEN 项目级待确认洞察未勾选「提升至全局记忆」并点击「保留」
THEN 客户端 POST /api/lclone-review {id, action:'keep'}，该洞察在项目级落地(active)，不提升到全局

#### Scenario: 稍后留pending

WHEN 用户点击「稍后」
THEN 该洞察从弹窗消失、计入 seen，留在工作台 pending 待后续确认

#### Scenario: 服务离线

WHEN /api/lclone-decisions 拉取失败（lclone web 未启动）
THEN 清空角标并隐藏弹窗，轮询继续，服务恢复后重新呈现
