# memory-capture Specification

## MODIFIED Requirements

### Requirement: 记录按会话聚合

同一外部会话（session_key 相同）SHALL 只建一条 note，**把每轮原始对话内容直接追加**进这条 note（不依赖 LLM 提炼）；新会话（新 session_key）SHALL 新建一条 note，并写入该轮原始内容。

#### Scenario: 同会话追加

WHEN 相同 session_key 连续捕获（无论该轮 LLM 是否提炼出内容）
THEN 每轮原始对话文本追加到同一条 note，不新建

#### Scenario: 新会话新 note

WHEN 新 session_key 首次捕获
THEN 新建一条 note 并写入该轮原始内容

#### Scenario: 探索性轮次也记录

WHEN 某轮内容为探索/纯实现（LLM 提炼为空）
THEN 该轮原始内容仍追加到该会话 note（不因提炼为空而中断）

### Requirement: note 滚动压缩

note 追加原始内容后长度超过阈值（3000 字）时，SHALL 把整条 note 摘要压缩一次，保持有界。

#### Scenario: 超长触发压缩

WHEN 追加原始内容后 note 长度超过阈值
THEN 整条 note 被 LLM 摘要成有界摘要

#### Scenario: 压缩后继续追加

WHEN 压缩后的 note 在后续轮次继续追加
THEN 仍按「追加 → 超阈值再压缩」滚动处理
