# integrations — 触发胶水层

本目录只放「生命周期点 → 调 lclone」的适配胶水，**零业务逻辑**。记忆引擎（capture/recall/bootstrap/分类器）全在 `lclone/`，这里不重复实现。

## 四个触发面

| 目录 | 环境 | 触发方式 | 生命周期点 |
|---|---|---|---|
| `claude-code/` | Claude Code | hooks | SessionStart→`bootstrap`；Stop→`capture` |
| `codex/` | OpenAI Codex CLI | hooks + AGENTS.md + MCP | SessionStart→`bootstrap`；Stop→`capture` |
| `dsh/` | DeepSeek Harness | Cordis 插件 | `agent/session-start`→`bootstrap`；轮结束→`capture` |
| `skill/` | 任意支持 skill 的环境 | 指令注入（软兜底） | 会话开始→`bootstrap`；对话中→`capture` |

## 前置

所有 shell 适配器统一调两个 CLI 命令（已实现）：

```bash
lclone bootstrap "话题"    # 会话开始：charter + 全局记忆(无条件) + 按话题召回 + 待确认决策
lclone capture "内容"      # 自动沉淀：decision→草稿待确认, note→直接生效
```

hook 脚本按以下顺序解析 `lclone`：PATH 里的 `lclone` → 本仓库 `.venv/bin/python -m lclone`。

## 安装

- **Claude Code**：把 `claude-code/settings.json` 里的 hooks 合并进 `~/.claude/settings.json`（或 `.claude/settings.json`）。
- **Codex**：把 `codex/hooks.json` 合并进 `~/.codex/hooks.json`；`codex/AGENTS.md` 内容追加到仓库 `AGENTS.md`。
- **DSH**：见 `dsh/README.md`（需要把 Cordis 插件打进 roster）。
- **skill**：`skill/SKILL.md` 是 `~/.agents/skills/lclone-memory/SKILL.md` 的版本化副本，保持同步。

> 路径占位：示例里用 `/Users/didi/github/L-clone`，迁移时改成本仓库实际路径。
