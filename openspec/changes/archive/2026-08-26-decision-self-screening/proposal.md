## Why

自动捕获的 LLM 提炼偏「多提」，把过程性琐碎、一次性、临时性内容也提炼成决策，弹给用户确认造成打扰。需要让 LLM 在提炼前先自筛：只提「真正值得长期记住、跨会话有用」的高价值内容，宁可少提甚至不提。

## What Changes

- `extract_memories` 提示词改为「记忆筛选器」：要求 LLM 提炼前自问「用户下次决策还用得到吗/值得跨会话保留吗」，只输出选型/约定/边界/关键事实，过程性琐碎/一次性/显而易见/临时性/代码改动一律不输出。
- 代码侧 `_filter_item` 保持不变，作为关键词安全网。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `memory-capture`: 「记忆分类与确认」新增「自筛低价值」场景。

## Impact

- 代码：`lclone/llm.py`（`extract_memories` 提示词）
- 接口：无
- 依赖：无

## 方案

```python
# llm.py: extract_memories 提示词强化自筛
"你是一个记忆筛选器… 提炼前先自问: 用户下次做相关决策时还用得到吗?"
"以下一律不要输出(宁可少提甚至不提): 过程性琐碎/一次性/显而易见/临时性/代码改动…"
```

## Spec Constraints

- `memory-capture` > 记忆分类与确认 > 「捕获决策」：选型/约定/边界才进 decision。
- `memory-capture` > 分工边界 > 「分类器排除代码改动」：代码改动不提炼。
