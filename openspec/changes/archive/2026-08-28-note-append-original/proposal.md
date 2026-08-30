## Why

memory-capture 的「记录按会话聚合 / note 滚动压缩」设计假设每轮都会产生内容，但实际大量轮次（探索、纯实现、闲聊）被 `extract_memories` 的 LLM 提炼判为空，导致 note **不建立、不追加、永不压缩**——会话记录链条断裂（本次"给 dsh 加看板按钮"对话即无任何记录）。用户期望 note 是**持续累积**的：每轮直接记录原始内容，到阈值再做 LLM 摘要压缩，不依赖 LLM 判断"值不值得记"。

## What Changes

- **note 通道改为记录原始内容**：`capture` 的 note 不再取自 `extract_memories` 的提炼结果，而是直接把本轮原始对话文本追加到该会话 note。
  - 每轮**无条件**记录（不依赖 LLM 提炼）；同一 session_key 仍只建一条 note、逐轮追加。
  - 追加后长度超阈值（3000 字）→ LLM `summarize` 滚动压缩（保持原逻辑）。
- **decision 通道保持 LLM 提炼**：`extract_memories` 只用于提炼 decision（`level == "decision"`），进 pending 待用户确认；归属判断（module 或 project）仍由 LLM 分类 + `_resolve_module` 词表强制。
- **note 只挂 project**：module 恒为空（不挂模块），符合"记录不挂模块"。

## Capabilities

- **New Capabilities**: 无
- **Modified Capabilities**: `memory-capture`
  - 修改「记录按会话聚合」：note 改为直接记录原始内容，不依赖 LLM 提炼
  - 修改「note 滚动压缩」：明确阈值触发为原始内容追加后判定（非提炼结果）

## Impact

- **代码**：`lclone/memory.py` 的 `capture` 函数（note 分支改为原始内容通道）
- **依赖**：无新增（`llm.summarize`/`embed_one` 复用）
- **行为**：note 现会记录含"做了什么"的原始对话文本（噪音更多），由滚动压缩兜底；decision 流程不变
