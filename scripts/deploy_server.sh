#!/usr/bin/env bash
# 一键服务器部署 L-clone (Linux + Docker + Docker Compose)
#
# 用法:
#   ./scripts/deploy_server.sh
#
# 做的事: 检测 Docker → 交互生成 .env(选 provider + 填 key + 随机生成服务鉴权 key)
#         → docker compose up -d --build → 健康检查 → 打印访问地址与安全提醒。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

info() { printf '\033[36m==> %s\033[0m\n' "$*"; }
ok()   { printf '\033[32m✓ %s\033[0m\n' "$*"; }
warn() { printf '\033[33m⚠ %s\033[0m\n' "$*"; }

# ---- 1. 依赖检测 ----
if ! command -v docker >/dev/null 2>&1; then
  warn "未检测到 docker。请先安装: https://docs.docker.com/engine/install/"
  exit 1
fi
if docker compose version >/dev/null 2>&1; then
  DC="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  DC="docker-compose"
else
  warn "未检测到 docker compose 插件，请先安装 compose 插件。"
  exit 1
fi

# ---- 2. 生成 .env ----
if [ -f .env ]; then
  ok "已存在 .env，跳过生成"
else
  info "生成 .env（选模型服务商 + 填 API Key）"
  echo "  1) deepseek(默认, 无 embed 接口自动走本地向量)  2) openai"
  echo "  3) siliconflow                                    4) zhipu"
  read -rp "选 provider [1]: " prov_choice
  case "${prov_choice:-1}" in
    2) BASE_URL="https://api.openai.com/v1";        CHAT="gpt-4o-mini";           EMBED="text-embedding-3-small"; EMBED_BACKEND="api" ;;
    3) BASE_URL="https://api.siliconflow.cn/v1";    CHAT="Qwen/Qwen2.5-7B-Instruct"; EMBED="BAAI/bge-m3";          EMBED_BACKEND="api" ;;
    4) BASE_URL="https://open.bigmodel.cn/api/paas/v4"; CHAT="glm-4-flash";       EMBED="embedding-3";           EMBED_BACKEND="api" ;;
    *) BASE_URL="https://api.deepseek.com/v1";      CHAT="deepseek-v4-flash";     EMBED="";                       EMBED_BACKEND="local" ;;
  esac
  read -rsp "OPENAI_API_KEY: " API_KEY; echo

  # 服务鉴权 key(随机生成)
  if command -v openssl >/dev/null 2>&1; then
    AUTH_KEY="$(openssl rand -hex 24)"
  else
    AUTH_KEY="$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')"
  fi

  cat > .env <<EOF
# 由 deploy_server.sh 生成
BRAIN_LLM=api
BRAIN_BASE_URL=$BASE_URL
BRAIN_CHAT_MODEL=$CHAT
BRAIN_EMBED_MODEL=$EMBED
BRAIN_EMBED_BACKEND=$EMBED_BACKEND
BRAIN_TEMPERATURE=0.3
OPENAI_API_KEY=$API_KEY
BRAIN_HOST=0.0.0.0
BRAIN_PORT=8000
LCLONE_API_KEY=$AUTH_KEY
EOF
  ok ".env 已生成。服务鉴权 key(LCLONE_API_KEY)=$AUTH_KEY，请妥善保存。"
fi

# ---- 3. 构建并启动 ----
info "构建并启动容器 ..."
$DC up -d --build

# ---- 4. 健康检查 ----
info "等待服务就绪 ..."
if command -v curl >/dev/null 2>&1; then
  for _ in $(seq 1 30); do
    if curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
      ok "服务已就绪: http://127.0.0.1:8000"
      break
    fi
    sleep 1
  done
fi

# ---- 5. 收尾 ----
IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
cat <<EOF

部署完成。访问地址:
  本机:  http://127.0.0.1:8000
  内网:  http://${IP:-<服务器IP>}:8000

安全提醒(务必执行):
  1. 已在 .env 生成 LCLONE_API_KEY，远程访问 /api/* 与 /mcp 需鉴权，请勿泄露。
  2. 建议用 Caddy 加 HTTPS 并绑定域名(见 docs/DEPLOYMENT.md)。
  3. 定期备份 ./data/lclone.db(你的大脑数据比服务器值钱)。

常用命令:
  $DC logs -f lclone       # 看日志
  $DC down                 # 停止
  $DC up -d                # 再次启动
EOF
