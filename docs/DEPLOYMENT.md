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
cp .env.example .env        # 填写 API Key
docker compose up -d
# 访问 http://服务器IP:8000
```

数据持久化在 `./data/lclone.db`, 容器重启不丢失。

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
- v1 起: MCP server, 让 Claude Code 等 AI 工具直接读写大脑
