# CLI 参考

> 回到 [README](../README.md)

## 命令总览

```
lclone init                           初始化数据库
lclone proj add <name> [仓库路径] [--charter "大方向"]
lclone proj list / sync <id|name> / rm / show
lclone log "一句话摘要" [--project id]          # L0 流水
lclone remember "内容" [--level decision|milestone|note] [--project id]
lclone capture "本次工作内容" [--project id]     # B: 进草稿
lclone review [--id N --action keep|edit|delete --edit-new "…"] [--all keep|delete]
lclone recall "查询" [--project id] [--k 5]
lclone memories [--project id] [--level decision|milestone|note] [--status active|pending|archived] [--limit 20]
lclone supervise "新提议" --project id           # 规范环
lclone ask "问题" [--project id] [--thread id]  # 回顾环
lclone web [--host 0.0.0.0] [--port 8000]
```

所有子命令可用 `--db <路径>` 指定数据库(前后均可)。

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
| `BRAIN_TEMPERATURE` | `0.3` | 采样温度 |
| `BRAIN_HOST` / `BRAIN_PORT` | `0.0.0.0` / `8000` | Web 面板监听 |
