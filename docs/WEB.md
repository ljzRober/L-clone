# Web 面板

> 回到 [README](../README.md)

启动:

```bash
python -m lclone web
# 浏览器打开 http://127.0.0.1:8000
```

## 五个页签

| 页签 | 功能 |
|---|---|
| 问答 | 带记忆的对话(回顾环), 可选择项目, 会话自动延续 |
| 记忆 | **记录一段对话**(粘贴内容 → LLM 自动提炼决策 → 进待确认); 主动记忆(直接生效); 回顾检索 |
| 项目 | 注册项目、同步 spec 索引(只读扫描仓库 `.specs/` 与 `doc/adr/`) |
| 监督 | 边界监督(规范环): 输入新提议 → 对照项目 spec 输出 ✅/⚠️/❌ 检查报告 |
| 待确认 | B 确认制: 批量保留 / 删除自动捕获的草稿记忆 |

## REST API(供其他程序调用)

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 健康检查 |
| GET | `/api/projects` | 项目列表 |
| POST | `/api/projects` | 注册项目 `{name, path, charter}` |
| POST | `/api/projects/{id}/sync` | 同步 spec 索引 |
| POST | `/api/remember` | 主动记忆 `{content, level, project_id?}` |
| POST | `/api/capture` | 自动捕获 `{text, project_id?, title?}` → 草稿 |
| GET | `/api/pending` | 待确认列表 |
| POST | `/api/review` | 确认草稿 `{id, action: keep/edit/delete, content?}` |
| POST | `/api/recall` | 回顾检索 `{query, project_id?, k?}` |
| POST | `/api/supervise` | 边界监督 `{proposal, project_id}` |
| POST | `/api/ask` | 带记忆问答 `{question, project_id?, thread_id?, k?}` |
| GET | `/api/threads/{id}/messages` | 线程历史 |

交互式 API 文档(自动生成): 浏览器打开 `http://127.0.0.1:8000/docs`。
