## ADDED Requirements

### Requirement: 自动调度 sp-spec

lclone-memory skill SHALL 在会话中检测 sp-spec 可用性（`~/.agents/skills/sp-spec` 存在）。检测到 sp-spec 时，出现构建性任务后 SHALL 默认自动加载 sp-spec 并运行 quick 模式（是否升级 full/debug 由 sp-spec 自决），无需用户手动 /sp-spec；未检测到 sp-spec 时，SHALL 仅在首次会话提醒用户安装 sp-spec（URL https://github.com/ljzRober/sp-spec），不重复提醒。

#### Scenario: 有 sp-spec 自动 quick

WHEN 会话中检测到 sp-spec 且进入构建性任务
THEN lclone 自动加载 sp-spec 并运行 quick 模式；sp-spec 自身按需升级 full/debug，用户不手动 /sp-spec

#### Scenario: 无 sp-spec 首次提醒

WHEN 未检测到 sp-spec 且为首次检测
THEN 提醒用户安装 sp-spec（https://github.com/ljzRober/sp-spec），且仅提醒一次，不重复
