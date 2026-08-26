## Why

上一版把模块归属实现为「embedding 相似度增量聚类」，但当前后端 `BRAIN_EMBED_BACKEND=local`（DeepSeek 不提供 embedding 接口，用本地哈希向量）是非语义的：语义相同的内容余弦相似度实测仅 0~0.5，远低于聚类阈值 0.8，导致「一条记忆新建一个模块」，且 `name_module` 起了过度具体的名字、note 追加路径产生 0 记忆孤儿模块。

## What Changes

- **module 归属改为「LLM 分类到代码维护词表」**：`extract_memories` 在提炼时顺带把每条内容归到项目已有模块或给出粗粒度新关注点（提示词传入已有模块列表并要求复用）；代码经 `_resolve_module` 做词表强制（归一化、复用已有名、防泛名）。
- **移除 embedding 聚类**：删除 `assign_module`/`_update_centroid`/`name_module` 及 `MODULE_SIM_THRESHOLD`。
- **修 note 追加孤儿 bug**：只在真正新建记忆（decision 或新 note）时才解析模块，追加路径不再建模块。
- **清理存量碎片**：删除 0/1 记忆的碎片模块（19 个），其记忆 module 清空挂项目层。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `memory-capture`: 「模块归属」需求从「embedding 增量聚类」改为「LLM 分类到代码维护词表」。

## Impact

- 代码：`lclone/llm.py`、`lclone/memory.py`、`tests/test_offline.py`
- 数据：`lclone.db` 清理碎片模块（19 个）与孤儿 module 字符串
- 接口：`extract_memories(text, existing_modules=None)` 签名新增可选参数；移除 `name_module`

## 方案

### 模块归属（LLM 分类 + 代码词表强制）

```python
# llm.py: 提炼时给出 module, 传入已有模块列表要求复用
def extract_memories(text, existing_modules=None) -> [{level, module, content}]

# memory.py: 词表强制 (语义交给 LLM, 稳定性交给代码)
def _normalize_module(name):        # 小写 + 非字母数字转 '-' + 去首尾
def _resolve_module(conn, pid, name):  # 复用已有名 / 新名非泛名入表 / 泛名挂项目层
```

- `capture` 把 `existing_modules` 传给 LLM；只在建记忆时调 `_resolve_module`（decision 或新 note），追加路径不建模块。
- `remember` 的显式 `module` 参数同样走 `_resolve_module` 归一化。

## Spec Constraints

- `memory-capture` > 模块归属 > 「自动派生模块」：capture 提炼时给每条记忆模块名，代码补录 modules 表。
- `memory-capture` > 模块归属 > 「不硬编码模块」：模块动态派生、复用已有名，不预建空模块。
- `memory-capture` > 模块归属 > 「泛名挂项目层」：泛名不建模块。
