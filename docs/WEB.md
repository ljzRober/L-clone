# Web 面板

> 回到 [README](../README.md)

启动:

```bash
python -m lclone web
# 浏览器打开 http://127.0.0.1:8000
# 后台常驻: lclone serve start (stop/status/restart)
```

## 两个页面

| 页面 | 地址 | 功能 |
|---|---|---|
| 记忆工作台 | `/` | 层级树(全局层 → 项目 → 模块) + 架构图; 卡片流分页; 添加/编辑/删除/移动记忆; 待确认决策; 添加项目、添加/删除模块、移除/复活项目; 一键整理合并 |
| 问答 | `/ask` | 带记忆问答(回顾环, 可选项目, 会话自动延续, 显示召回引用) + 边界监督(规范环) |

## 记忆工作台

- **层级树**:左侧「全局层 → 项目 → 模块」三级命名空间, 点选节点即过滤右侧架构图;
  展开项目显示其模块子节点, 行内垃圾桶可删除模块(连带删除该模块下决策记忆)。
- **架构图**:右侧按「全局 / 项目 / 模块」三层渲染, 记忆卡片网格分页;记忆间 `[[m:N]]` 链接画成连线。
- **上升/下降**:打开记忆详情, 在「归属」下拉选目标层级(全局层或某项目), 点「移动到所选」即移动归属(项目 → 全局、全局 → 项目、项目间横搬)。
- **添加记忆**:右上角「＋ 添加记忆」弹窗, 选等级(决策/记录)、归属(全局/项目)、模块(仅决策)。
  手动添加视为「当场已确认」, 决策直接生效。
- **待确认**:顶栏「待确认 N」按钮打开草稿列表, 逐条 保留/编辑/删除;数量每 30s 轮询刷新。
- **整理**:工具栏「整理」让 LLM 把语义相近的记忆合并(不跨项目/等级/模块)。
- **刷新**:工具栏「刷新」重新拉取记忆/项目/链接。

## REST API(供其他程序调用)

鉴权: 设了 `LCLONE_API_KEY` 时, 下列 `/api/*` 与 `/mcp` 需带
`Authorization: Bearer <key>` 或 `X-API-Key: <key>`; 未设则本地免鉴权。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 健康检查 `{ok, backend, db}` |
| GET | `/api/projects` | 项目列表 `{items}` |
| POST | `/api/projects` | 注册项目 `{name, path, charter}` |
| POST | `/api/projects/{id}/sync` | 同步 spec 索引 |
| GET | `/api/projects/{id}/modules` | 项目模块列表 |
| POST | `/api/projects/{id}/modules` | 添加模块 `{name}` |
| POST | `/api/projects/{id}/modules/delete` | 删除模块(连带删除其决策记忆) `{name}` |
| POST | `/api/projects/{id}/remove` | 墓碑式移除项目(可 restore) |
| POST | `/api/projects/{id}/restore` | 复活已移除项目 |
| POST | `/api/remember` | 主动记忆 `{content, level, project_id?, reason?, module?}`(决策直接生效) |
| POST | `/api/capture` | 自动捕获 `{text, project_id?, title?, module?}` |
| GET | `/api/pending` | 待确认列表 `{items}` |
| GET | `/api/memories` | 列出记忆 `?project_id&level&status&limit&layer` |
| GET | `/api/links` | 记忆链接表(架构图连线用) |
| POST | `/api/review` | 确认草稿 `{id, action: keep/edit/delete, content?, module?}` |
| POST | `/api/memories/{id}/promote` | 上升: 项目记忆 → 全局层 |
| POST | `/api/memories/{id}/demote` | 下降: 挂到项目 `{project_id}` |
| GET | `/api/suggest` | 删除提示(仅提示, 不删除) |
| POST | `/api/organize` | 整理: LLM 语义合并相近记忆 |
| POST | `/api/recall` | 回顾检索 `{query, project_id?, k?}` |
| POST | `/api/supervise` | 边界监督 `{proposal, project_id}` |
| POST | `/api/ask` | 带记忆问答 `{question, project_id?, thread_id?, k?, with_specs?}` |
| GET | `/api/threads/{id}/messages` | 线程历史 |
| POST | `/mcp` | MCP over HTTP(JSON-RPC), 供 Claude Code / Codex / DSH 远程接入 |

交互式 API 文档(自动生成): 浏览器打开 `http://127.0.0.1:8000/docs`。
