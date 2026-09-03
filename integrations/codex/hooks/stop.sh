#!/usr/bin/env bash
# Codex Stop hook: 每轮结束时把本轮内容 capture 进大脑草稿 (洞察 insight)。
# stdin 收到 JSON (可能含 transcript_path), 读不到就退化用 stdin 原文, 静默失败不阻断。
set -uo pipefail

if command -v lclone >/dev/null 2>&1; then
  run() { lclone "$@"; }
else
  REPO="$(cd "$(dirname "$0")/../../.." && pwd)"
  run() { "$REPO/.venv/bin/python" -m lclone "$@"; }
fi

INPUT="$(cat 2>/dev/null || true)"
TRANSCRIPT="$(printf '%s' "$INPUT" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("transcript_path",""))' 2>/dev/null || true)"
if [ -n "$TRANSCRIPT" ] && [ -f "$TRANSCRIPT" ]; then
  TEXT="$(head -c 12000 "$TRANSCRIPT" 2>/dev/null || true)"
else
  TEXT="$(printf '%s' "$INPUT" | head -c 12000)"
fi
[ -n "$TEXT" ] && run capture "$TEXT" >/dev/null 2>&1 || true
exit 0
