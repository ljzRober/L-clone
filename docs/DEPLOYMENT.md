# 部署到服务器

> 回到 [README](../README.md)

设计定位:**记忆在服务器, 模型走 API**(不本地部署模型, 无需 GPU)。

## 服务器选择

| 方案 | 成本 | 说明 |
|---|---|---|
| 云 VPS(推荐) | ~¥25-60/月 | 2C2G 足够; 国内需备案, 海外免备案(Hetzner / Vultr 等) |
| 家用常开电脑 / NAS | 电费 | 配 Tailscale 组网远程访问 |
| PaaS(Railway / Fly) | 免费额度起 | 免运维, 数据在第三方 |

## Docker 部署

```bash
# 服务器上:
git clone <你的仓库> && cd L-clone
cp .env.example .env        # 填写 API Key + LCLONE_API_KEY(服务鉴权)
docker compose up -d
# 访问 http://服务器IP:8000
```

数据持久化在 `./data/lclone.db`, 容器重启不丢失。

> 服务器上**务必设置 `LCLONE_API_KEY`**, 否则任何能访问 8000 端口的人都能读写你的记忆。

## MCP over HTTP（agent 远程接入）

Web 服务同时暴露 MCP 端点, Claude Code / Codex / DSH 等可远程读写大脑:

```
端点:   POST /mcp          (JSON-RPC over HTTP)
鉴权:   Authorization: Bearer <LCLONE_API_KEY>   或   X-API-Key: <key>
工具:   bootstrap / capture / recall / remember / promote / demote / suggest / projects / review / ask
```

配置示例(Claude Code 的 MCP server, 走 streamable-http):

```json
{
  "mcpServers": {
    "lclone": {
      "url": "https://lclone.yourdomain.com/mcp",
      "headers": { "Authorization": "Bearer <你的 LCLONE_API_KEY>" }
    }
  }
}
```

> 注意: 当前 `/mcp` 是 JSON-RPC over HTTP(请求-响应), 覆盖 tools/list + tools/call;
> 若客户端强制要求 SSE 流式响应, 后续可补 streamable-http 的 SSE 分支。

## 加 HTTPS(推荐 Caddy)

```
# Caddyfile
lclone.yourdomain.com {
    reverse_proxy 127.0.0.1:8000
}
```

## 安全建议

- SSH 密钥登录 + 关密码登录
- 防火墙只放行 22 / 80 / 443
- **定期备份 `data/lclone.db`**(你的大脑数据比服务器值钱), 可用 restic / rsync

## 多设备访问

- 浏览器: 任何设备打开 `https://你的域名` 即用(Web 面板)
- 命令行: `ssh 服务器` 后执行 `lclone ask "..."` 等
- AI 工具: 通过 MCP over HTTP(`POST /mcp`)让 Claude Code / Codex / DSH 直接读写大脑
