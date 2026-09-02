## Why

insight 要真正做好检索与 embedding，需要"做厚"——否则一行干结论匹配不佳、检索反而增加复杂度。同时对诊断出的核心污染源（note #285/#319 里混入系统提示/注入段）在 ingest 阶段剥离，提升洞察提取质量。

## What Changes

- **insight 四段卡**：`extract_memories` 提示词要求每条 insight 按「要点｜背景/为什么｜影响/以后注意｜归属」写成一行（约 2-4 句），自包含可独立读懂。
- **ingest 剥噪**：`capture` 前先经 `_strip_ingest_noise` 剥离宿主注入的标签块（`<system-reminder>`/`<private>`/`<claude-mem-context>`/`<available_skills>`/`<injected>`/`<context>`），避免污染提取。

## Capabilities

- `memory-capture`：`记忆分类与确认` MODIFIED（加四段卡 + ingest 剥噪场景）。

## Impact

- 代码：`lclone/llm.py`（extract 提示词四段卡）、`lclone/memory.py`（新增 `_strip_ingest_noise`，capture 前调用）。
- 测试：`tests/test_offline.py` 新增 3 条 ingest 剥噪断言，全绿。
