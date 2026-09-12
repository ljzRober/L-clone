#!/usr/bin/env bash
# 待确认洞察摘要: 只读列出 pending 条目与对应的 review 命令, 不删任何东西。
#
# 用法:  ./lclone-pending-digest.sh
# 环境:  BRAIN_DB_PATH  数据库路径 (默认 lclone.db)
set -euo pipefail

DB="${BRAIN_DB_PATH:-lclone.db}"
JSON="$(python3 -m lclone pending --db "$DB")"

LCLONE_PENDING_JSON="$JSON" python3 - <<'PY'
import json
import os

items = json.loads(os.environ.get("LCLONE_PENDING_JSON") or "[]")
if not items:
    print("(没有待确认的洞察)")
    raise SystemExit(0)

print(f"待确认洞察 {len(items)} 条:\n")
for it in items:
    mid = it.get("id")
    body = " ".join((it.get("content") or "").split())
    print(f"#{mid}  {body[:100]}")
    print(f"    保留: lclone review --id {mid} --action keep")
    print(f"    删除: lclone review --id {mid} --action delete\n")
PY
