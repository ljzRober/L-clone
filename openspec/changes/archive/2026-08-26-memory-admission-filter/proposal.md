## Why

自动捕获会把「纷繁杂乱无用」的内容也记进 lclone：代码改动/重构/bug 这类「做了什么」本应归 git 与 sp-spec，却被 LLM 提炼成决策；无决策信号的过程描述也被判成 decision，导致待确认列表膨胀。此外「记录(note)」不该挂模块——记录都应在项目层（偶尔全局层），只有「决策(decision)」才按关注点归模块。

## What Changes

- **记忆准入条件（代码强制）**：`capture` 落库前对每条 LLM 提炼结果做确定性过滤 `_filter_item`：
  - 命中「做了什么」标记（修复/重构/commit/fix/bug 等）→ 不记忆（归 git & spec）；
  - level=decision 但内容无决策信号（决定/采用/方案/边界/规则/约定等）→ 降级为 note；
  - note 过短（< 4 字）→ 丢弃。
- **记录无模块**：note 一律 `module=''`（项目层/全局层），不挂模块；仅 decision 挂模块（LLM 分类 + 词表强制）。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `memory-capture`: 「记忆分类与确认」增加决策准入/信号/琐碎场景；「模块归属」增加「记录无模块」场景。

## Impact

- 代码：`lclone/memory.py`（`_filter_item`、`DID_MARKERS`/`DECISION_SIGNALS`/`NOTE_MIN_LEN` 常量、capture/remember 的 note 无模块）
- 测试：`tests/test_offline.py`（新增 88–93 覆盖过滤与 note/decision 模块差异）
- 接口：`capture` 行为变化（note 不再带模块）

## 方案

```python
# memory.py: 准入条件 (LLM 提炼之后、落库之前, 确定性过滤)
DID_MARKERS      = ("修复", "重构", "迁移", "回滚", "commit", "fix", "bug", ...)
DECISION_SIGNALS = ("决定", "确定", "采用", "选择", "方案", "边界", "规则", "约定", ...)
NOTE_MIN_LEN     = 4

def _filter_item(item):
    # 1. 「做了什么」→ 不记忆
    # 2. decision 无信号 → 降级 note
    # 3. note 过短 → 丢弃
```

- `capture`: 每条 `_filter_item` 后，note 分支 `mod=""`（不挂模块），decision 分支才 `_resolve_module`。
- `remember`: `level=note` 时 `module=""`，`level=decision` 才走 `_resolve_module`。

## Spec Constraints

- `memory-capture` > 记忆分类与确认 > 「捕获决策」：选型/约定/边界才进 decision。
- `memory-capture` > 分工边界 > 「分类器排除代码改动」：代码改动不提炼进记忆。
- `memory-capture` > 模块归属 > 「自动派生模块」：capture 提炼时给模块名并补录 modules 表。
