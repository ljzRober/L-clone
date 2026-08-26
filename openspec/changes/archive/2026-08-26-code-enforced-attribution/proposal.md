## Why

归属判定、模块划分、记录聚合、决策确认四条核心流程目前依赖模型意图识别（skill 软规则），而非代码强制。实测后果：git 项目不自动生成、module 被 LLM 乱起名（core/textview/deploy…）、记录不增量聚合、决策静默进 pending 无人询问。需把这些流程下沉为代码确定性执行，只保留必须由模型承担的「内容提炼」与「弹窗 UX」。

## What Changes

- **project 归属（git 自动生成）**：新增 `resolve_project` 三态判定 `matched / created / no_git`。git 检测到仓库但未注册时**自动注册**（name=仓库 basename、path=仓库根、charter 留空）；无 git 时返回结构化「需用户决策」信号，**fail-closed 不静默落全局**。
- **module（增量聚类 + 一次性命名）**：`extract_memories` 只提炼 `level+content`，不再自由起模块名；代码用 embedding 余弦相似度把每条记忆归到最近模块（≥0.8）或新建模块；新模块名由一次性 LLM 标签并缓存进 `modules` 表；泛名黑名单 `core/misc/general/other/todo` 挂项目层。
- **记录增量添加**：`capture` 的 `session_key` 默认从 `DSH_SESSION_ID` 环境变量取（代码确定性），同一 session 一条 note 逐轮追加。
- **决策强确认**：`remember(level=decision)` 默认进 `pending`（除非显式 `confirmed=true`）；`capture` 返回结构化待确认决策列表；`bootstrap` 每次都带出待确认决策。
- **结构化返回**：MCP `capture`/`remember` 在未归属时返回结构化信号而非静默写入，客户端据此用弹窗询问用户。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `memory-capture`: 「归属判定」需求增加「git 检测到未注册仓库时自动注册项目」场景；「模块归属」需求从「按主题派生 module」改为「代码增量聚类 + 一次性命名」。

## Impact

- 代码：`lclone/projects.py`、`lclone/db.py`、`lclone/memory.py`、`lclone/llm.py`、`lclone/mcp_server.py`、`lclone/cli.py`
- 集成：`integrations/skill/SKILL.md`、`~/.agents/skills/lclone-memory/SKILL.md`、`integrations/dsh/dsh/index.js`
- 接口：MCP `capture`/`remember` 返回格式从自由文本改为结构化信号（未归属时 fail-closed）；`modules` 表新增 `centroid` 列
- 依赖：无新增第三方依赖

## 方案

### A. project 归属（代码强制）

```python
# projects.py
def resolve_project(conn, cwd=None):
    """返回 (status, project_id)。status ∈ matched | created | no_git"""
    repo = _git_toplevel(cwd)
    if repo is None:
        return ("no_git", None)
    for p in list_projects(conn):
        if p["path"] and Path(p["path"]).resolve() == repo.resolve():
            return ("matched", p["id"])
    # git 检测到但未注册 → 自动注册
    pid = add_project(conn, name=repo.name, path=str(repo), charter="")
    return ("created", pid)
```

- `capture`/`remember` 未显式传 project 时走 `resolve_project`；
- `no_git` → 返回结构化信号 `{"need": "user_decision", "options": ["create_project", "global"]}`，不写库；
- `matched`/`created` → 记忆归该项目。

### B. module（增量聚类 + 一次性命名）

```python
# memory.py
MODULE_SIM_THRESHOLD = 0.8
GENERIC_MODULES = {"core", "misc", "general", "other", "todo"}

def assign_module(conn, project_id, emb):
    """把一条记忆的向量归到最近模块；不够近则新建（一次性命名）。"""
    rows = conn.execute("SELECT id, name, centroid FROM modules WHERE project_id=?",
                        (project_id,)).fetchall()
    best, best_sim = None, 0.0
    for r in rows:
        if r["centroid"]:
            sim = _cosine(emb, unpack_vec(r["centroid"]))
            if sim > best_sim:
                best, best_sim = r, sim
    if best and best_sim >= MODULE_SIM_THRESHOLD:
        _update_centroid(conn, best["id"], emb)
        return best["name"]
    name = llm.name_module(content)  # 一次性标签, 缓存在 modules 表
    if (name or "").lower() in GENERIC_MODULES:
        return ""  # 泛名挂项目层
    _insert_module(conn, project_id, name, emb)
    return name
```

- `llm.extract_memories` 只返回 `level+content`，删除 module 字段；
- `llm.name_module(content)` 新增：一次性给关注点起英文短名，名字缓存进 `modules` 表，此后不再重复起名。

### C. 记录增量添加

- `capture` 的 `session_key` 缺省时读取 `os.environ.get("DSH_SESSION_ID")`；
- 同一 session_key 复用 session、同一条 note 逐轮追加（现有逻辑保持，仅补默认来源）。

### D. 决策强确认

- `remember(level="decision")` 默认 `status="pending"`，新增 `confirmed` 参数，显式 `confirmed=True` 才 `active`；
- `capture` 返回结构化结果 `{"decisions": [{"id", "content"}], "notes": [...]}`；
- `bootstrap` 保持每次都带出【待确认决策】。

### E. 数据迁移

- `modules` 表新增 `centroid BLOB` 列（`db.init` 内迁移，旧库自动补列）；
- 既有模块（无 centroid）不被硬编码复用：新捕获的聚类要么命中已有同名模块并回填质心，要么新建模块；泛名 `core` 等被 `GENERIC_MODULES` 黑名单拦截，不再参与模块归属（挂项目层）。存量乱模块的清理由用户在 Web 面板手动处理，不在本次代码改动内。

## Spec Constraints

- `memory-capture` > 归属判定 > 「git 优先」：会话所在 git 仓库匹配到已注册项目 → 记忆归该项目。
- `memory-capture` > 归属判定 > 「无 git 问用户」：git 检测不到已注册项目 → 主动问用户新建 project 还是升全局层。
- `memory-capture` > 模块归属 > 「自动派生模块」：每条记忆带主题 module，capture 自动补录 modules 表。
- `memory-capture` > 模块归属 > 「不硬编码模块」：模块由代码增量聚类动态派生，不预先硬编码空模块。
- `memory-capture` > 记录按会话聚合 > 「同会话追加 / 新会话新 note」。
- `memory-capture` > 决策强确认 > 「bootstrap 带出待确认 / 弹窗确认」。
