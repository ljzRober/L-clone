#!/usr/bin/env bash
# 外置大脑 - 离线一键演示 (Linux/macOS)
# 无需 API Key、无需安装任何第三方依赖
# 用法: ./scripts/demo_offline.sh
set -e
cd "$(dirname "$0")/.."

export BRAIN_LLM=dummy
export BRAIN_DB_PATH="$(mktemp -d)/brain_demo.db"

echo "=== 1. 初始化数据库 ==="
python3 -m brain init

echo ""
echo "=== 2. 注册项目 + 同步 spec 索引 ==="
python3 -m brain proj add demo examples/demo_project --charter "示例项目"
python3 -m brain proj sync demo

echo ""
echo "=== 3. 主动记忆 (C: 你说算, 直接生效) ==="
python3 -m brain remember "后端用 FastAPI, 边界: 单用户" --project demo

echo ""
echo "=== 4. 自动捕获 (B: 进草稿, 待确认) ==="
python3 -m brain capture "讨论后确定: 6月1日上线; 部署用 Docker Compose" --project demo

echo ""
echo "=== 5. 批量确认草稿 ==="
python3 -m brain review --all keep

echo ""
echo "=== 6. 回顾环: 检索记忆 ==="
python3 -m brain recall "FastAPI 边界" --project demo

echo ""
echo "=== 7. 规范环: 边界监督 ==="
python3 -m brain supervise "把数据库换成 PostgreSQL" --project demo

echo ""
echo "=== 8. 回顾环: 问答 ==="
python3 -m brain ask "我们项目定了什么? 有什么边界?" --project demo

echo ""
echo "演示完成!"
