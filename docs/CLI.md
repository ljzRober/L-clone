# CLI 参考

> 回到 [README](../README.md)

## 命令总览

```
lclone init                           初始化数据库
lclone proj add <name> [仓库路径] [--charter "大方向"]
lclone proj list / sync <id|name> / rm / restore / show
lclone log "一句话摘要" [--project id]          # L0 流水
lclone remember "内容" [--level decision|note] [--project id]
lclone capture "本次工作内容" [--project id]     # B: 进草稿
lclone review [--id N --action keep|edit|delete --edit-new "…"] [--all keep|delete]
lclone recall "查询" [--project id] [--k 5] [--no-follow]
lclone bootstrap ["话题"] [--project id] [--k 5]   # 会话启动引导: charter+全局记忆+召回
lclone promote <id>                            # 记忆上升: 项目 -> 全局层
lclone demote <id> --project <id|name>         # 记忆下降: 挂到指定项目(含项目间横搬)
lclone suggest [--dup-threshold 0.92] [--stale-days 7] [--unused-days 30]  # 删除提示
lclone memories [--project id] [--level decision|note] [--status active|pending|archived] [--limit 20]
lclone supervise "新提议" --project id           # 规范环
lclone ask "问题" [--project id] [--thread id]  # 回顾环
lclone web [--host 0.0.0.0] [--port 8000]
lclone serve start|stop|status|restart                                       # 管理 web 后台服务
lclone install [--provider deepseek] [--api-key xx] [--target all] [--yes]   # 一键接入向导
lclone doctor [--check-llm]                                                 # 自检接入是否完整
lclone backup [--dest backups]                                              # SQLite 在线快照备份
```

所有子命令可用 `--db <路径>` 指定数据库(前后均可)。

## 生命周期与记忆整理

- **上升/下降**: 记忆的"生命周期"是读取时决定的, 不落状态字段。
  - `promote <id>`: 项目记忆升到**全局层** (个人区) —— 当你发现多个项目要共读它时。
  - `demote <id> --project X`: 挂到指定项目 —— 当它不需要全局保持时; 也用于项目 A → B 横搬。
  - 全局层记忆永远加载; 项目记忆只在项目"活着"时加载。
- **项目墓碑**: `proj rm` 不删行不加状态, 只登记移除事件。移除后项目从列表消失、
  其记忆**停止加载**, 但数据保留, `proj restore <id|name>` 可复活。
- **记忆链接**: 内容里写 `[[m:12]]` 即链接到记忆 #12 (跨项目/跨层级均可)。
  召回命中时自动把被链接记忆一起带出 (一层、限量), `recall --no-follow` 可关闭。
- **删除提示**: `suggest` 用算法扫描候选 (疑似重复/长期未确认草稿/长期未召回/
  已移除项目记忆), 每条给出删除命令; **删除始终由你手动执行**。

## 模型 API 配置参考

`BRAIN_BASE_URL` 可切任意 OpenAI 兼容服务:

| 服务 | BASE_URL | chat 模型示例 | embed 模型示例 |
|---|---|---|---|
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` | `text-embedding-3-small` |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` | (需配合其他 embed) |
| 硅基流动 | `https://api.siliconflow.cn/v1` | `Qwen/Qwen2.5-7B-Instruct` | `BAAI/bge-m3` |
| 智谱 | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-flash` | `embedding-3` |

> 若 embed 模型不可用, 可把 `BRAIN_EMBED_MODEL` 指到任一兼容服务;
> 注意: 问答时检索到的记忆片段会随请求发给模型厂商(隐私边界)。

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `BRAIN_DB_PATH` | `lclone.db` | 数据库文件路径 |
| `BRAIN_LLM` | `api` | `api`(真实模型) / `dummy`(离线自测) |
| `OPENAI_API_KEY` | — | API Key |
| `BRAIN_BASE_URL` | `https://api.openai.com/v1` | OpenAI 兼容接口地址 |
| `BRAIN_CHAT_MODEL` | `gpt-4o-mini` | 对话/提炼/监督模型 |
| `BRAIN_EMBED_MODEL` | `text-embedding-3-small` | 向量化模型 |
| `BRAIN_EMBED_BACKEND` | `api` | `api`(真实 embed 接口) / `local`(本地哈希向量, 用于 DeepSeek 等无 embed 接口的服务商) |
| `BRAIN_TEMPERATURE` | `0.3` | 采样温度 |
| `BRAIN_HOST` / `BRAIN_PORT` | `0.0.0.0` / `8000` | Web 面板监听 |
