# 部署到服务器

> 回到 [README](../README.md)

设计定位:**记忆在服务器, 模型走 API**(不本地部署模型, 无需 GPU)。

**前后台分离**: `lclone web` 在服务器上同时提供**前端**(`lclone/frontend/` 静态单页, 浏览器打开即记忆工作台) 与**后端**(REST `/api/*` + MCP `/mcp`)。前端是独立静态资源, 可被其它源 serve 后**跨域**(已开 CORS `allow-origin:*`)调用本后端——因此 DSH 插件可"自己 serve 前端、把 `LCLONE_WEB_URL` 指向本服务器"。

## 服务器选择

| 方案 | 成本 | 说明 |
|---|---|---|
| 云 VPS(推荐) | ~¥25-60/月 | 2C2G 足够; 国内需备案, 海外免备案(Hetzner / Vultr 等) |
| 家用常开电脑 / NAS | 电费 | 配 Tailscale 组网远程访问 |
| PaaS(Railway / Fly) | 免费额度起 | 免运维, 数据在第三方 |

## Docker 部署

**一键脚本(推荐)**:

```bash
# 服务器上:
git clone <你的仓库> && cd L-clone
./scripts/deploy_server.sh   # 交互生成 .env → docker compose up -d --build → 健康检查
```

**手动**:

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
工具:   remember / capture / recall / bootstrap / promote / demote
        suggest / projects / review / ask / organize
        evolution_add / evolution_list / evolution_update / conflicts
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

- 浏览器: 任何设备打开 `https://你的域名` 即用(前后台分离的 Web 面板)
- 命令行: `ssh 服务器` 后执行 `lclone ask "..."` 等
- AI 工具: 通过 MCP over HTTP(`POST /mcp`)让 Claude Code / Codex / DSH 直接读写大脑
- **DSH 插件**(`integrations/dsh`, 自包含): 设 `LCLONE_WEB_URL=<服务器地址>` 即连本后端;
  插件自己 serve 前端(看板)并跨域(CORS 已开放)调本后端, 无需在本机装大脑
