#!/usr/bin/env bash
# 大脑备份 + 轮转: 快照 SQLite, 只保留最近 N 份 (默认 10)。
#
# 用法:  ./lclone-backup.sh [保留份数]
# 环境:  BRAIN_DB_PATH  数据库路径 (默认 lclone.db)
#        LCLONE_BACKUP_DIR  备份目录 (默认 backups)
set -euo pipefail

KEEP="${1:-10}"
DEST="${LCLONE_BACKUP_DIR:-backups}"
DB="${BRAIN_DB_PATH:-lclone.db}"

mkdir -p "$DEST"
python3 -m lclone backup --db "$DB" --dest "$DEST"

# 轮转: 按修改时间倒序, 保留前 KEEP 份
ls -1t "$DEST"/lclone-*.db 2>/dev/null | tail -n +$((KEEP + 1)) | while read -r f; do
  rm -f -- "$f"
done

echo "备份完成 (保留最近 ${KEEP} 份) → $DEST"
