#!/usr/bin/env bash
# Claude Code SessionStart hook: 会话开始时把 charter + 全局记忆注入上下文。
# 输出 JSON additionalContext, Claude Code 会把它加进上下文。
set -uo pipefail

if command -v lclone >/dev/null 2>&1; then
  run() { lclone "$@"; }
else
  REPO="$(cd "$(dirname "$0")/../../.." && pwd)"
  run() { "$REPO/.venv/bin/python" -m lclone "$@"; }
fi

CTX="$(run bootstrap "" 2>/dev/null || true)"
if [ -n "$CTX" ]; then
  ESC=$(printf '%s' "$CTX" | sed 's/\\/\\\\/g; s/"/\\"/g' | tr '\n' ' ')
  printf '{"hookSpecificOutput":{"additionalContext":"%s"}}\n' "$ESC"
fi
exit 0
