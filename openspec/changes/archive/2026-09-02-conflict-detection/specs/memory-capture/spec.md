## ADDED Requirements

### Requirement: 记忆矛盾检测

lclone SHALL 提供矛盾检测：扫描 active 洞察，找出语义相近（向量相似度 ≥ 阈值）的候选对，用 LLM 判定是否真矛盾（内容相反/规则改版/相冲突），输出 `{a, b, content_a, content_b, reason, hint}`。矛盾检测 SHALL 只提示候选、不自动改记忆，是否处理由用户决定（可经 review 删除/修订）。dummy 后端无法判定矛盾时 SHALL 返回"无候选/未发现矛盾"。

#### Scenario: 发现矛盾对

WHEN 一条新洞察与既有洞察语义相近且被 LLM 判为矛盾
THEN 输出该对 (id/内容/矛盾原因)，提示用户处理

#### Scenario: 只在有冲突才提示

WHEN 无矛盾候选或 LLM 判定无矛盾
THEN 空结果/未发现，不打扰用户

#### Scenario: 不自动改记忆

WHEN 检测到矛盾
THEN 仅提示，不自动删除/修订记忆；用户经 review 决定

#### Scenario: dummy 后端不判矛盾

WHEN 后端为 dummy（无真实 LLM）
THEN 返回"无候选/未发现矛盾"，不做矛盾判定
