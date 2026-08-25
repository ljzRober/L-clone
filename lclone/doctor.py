"""自检 (doctor): 检查 lclone 接入是否完整, 输出 ✅/❌/⚠️ 清单 + 修复建议。"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import List, Optional

from . import config, db as db_mod, presets


def home_dir() -> Path:
    h = os.environ.get("LCLONE_HOME")
    return Path(h).expanduser() if h else Path.home()


def _env_file() -> Optional[Path]:
    for p in (Path.cwd() / ".env",
              Path(__file__).resolve().parent.parent / ".env"):
        if p.exists():
            return p
    return None


def _git_toplevel() -> Optional[Path]:
    try:
        p = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                           capture_output=True, text=True, timeout=10)
    except Exception:
        return None
    return Path(p.stdout.strip()) if p.returncode == 0 else None


def _git_config(key: str) -> str:
    try:
        p = subprocess.run(["git", "config", "--get", key],
                           capture_output=True, text=True, timeout=10)
    except Exception:
        return ""
    return p.stdout.strip() if p.returncode == 0 else ""


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def check_all(db_path: Optional[str] = None, home: Optional[Path] = None,
              check_llm: bool = False) -> List[dict]:
    home = Path(home) if home else home_dir()
    db_path = db_path or config.db_path()
    out: List[dict] = []

    def add(name: str, ok: bool, detail: str, hint: str = "") -> None:
        out.append({"name": name, "ok": ok, "detail": detail, "hint": hint})

    # 1. .env
    envf = _env_file()
    if envf is None:
        add("配置 .env", False, "未找到 .env",
            "运行 lclone install 生成")
    else:
        missing = []
        for k in ("BRAIN_LLM", "BRAIN_BASE_URL", "BRAIN_CHAT_MODEL",
                  "BRAIN_EMBED_BACKEND", "OPENAI_API_KEY"):
            if not config.get(k) and k not in ("BRAIN_BASE_URL", "BRAIN_CHAT_MODEL",
                                               "OPENAI_API_KEY"):
                missing.append(k)
        if config.get("BRAIN_LLM") != "dummy" and not config.get("OPENAI_API_KEY"):
            missing.append("OPENAI_API_KEY")
        add("配置 .env", not missing, str(envf),
            "缺: " + ", ".join(missing) if missing else "")

    # 2. provider 识别
    pname = presets.recognize_provider(config.get("BRAIN_BASE_URL"),
                                       config.get("BRAIN_LLM"))
    add("provider 预设", bool(pname), pname or "未识别",
        "" if pname else "BRAIN_BASE_URL 未匹配任何预设, 可用 lclone install 重配")

    # 3. 数据库
    try:
        conn = db_mod.init(db_path)
        add("数据库", True, f"{db_path}")
    except Exception as e:
        add("数据库", False, f"{type(e).__name__}: {e}", "检查 BRAIN_DB_PATH 目录权限")
        conn = None

    # 4/5. 项目
    if conn is not None:
        try:
            from . import projects as proj_mod
            rows = proj_mod.list_projects(conn)
            add("项目注册", bool(rows), f"{len(rows)} 个: " + ", ".join(
                r["name"] for r in rows), "" if rows else "lclone proj add <名> <路径>")
            root = _git_toplevel()
            if root is not None:
                pid = proj_mod.detect_project_by_git(conn)
                add("当前仓库已注册", pid is not None,
                    f"git={root}", "" if pid is not None else "lclone proj add")
        except Exception as e:
            add("项目注册", False, f"{type(e).__name__}: {e}")

    # 6. skill
    skill = home / ".agents/skills/lclone-memory/SKILL.md"
    add("skill 已装", skill.exists(), str(skill),
        "" if skill.exists() else "lclone install 会自动装")

    # 7. DSH 插件
    dsh_pkg = home / ".dsh/profiles/web/node_modules/lclone-memory-dsh"
    dsh_any = (home / ".dsh/plugins").exists()
    add("DSH 插件", dsh_pkg.exists(), "已装" if dsh_pkg.exists() else
        ("有插件目录但未装 lclone-memory-dsh" if dsh_any else "未检测到 DSH 插件"),
        "dsh plugin --profile web add <integrations/dsh>")

    # 8. Claude Code hooks
    cc = home / ".claude/settings.json"
    cc_txt = _read(cc)
    add("Claude Code hooks", "lclone" in cc_txt, str(cc),
        "" if "lclone" in cc_txt else "把 integrations/claude-code/settings.json 合并进去")

    # 9. Codex hooks
    cx = home / ".codex/hooks.json"
    cx2 = home / ".codex/config.toml"
    cx_txt = _read(cx) + _read(cx2)
    add("Codex hooks", "lclone" in cx_txt, f"{cx} / {cx2}",
        "" if "lclone" in cx_txt else "把 integrations/codex/hooks.json 合并进去")

    # 10. commit 钩子
    root = _git_toplevel()
    hooks_path = _git_config("core.hooksPath")
    commit_hook = bool(hooks_path) or (
        root is not None and (root / ".git/hooks/post-commit").exists())
    add("commit 钩子", commit_hook, f"hooksPath={hooks_path or '(未设)'}",
        "" if commit_hook else "git config core.hooksPath scripts/hooks")

    # 11. LLM 连通 (可选)
    if check_llm:
        try:
            from . import llm
            resp = llm.chat([{"role": "user", "content": "ping"}])
            add("LLM 连通", bool(resp), "OK" if resp else "空响应",
                "" if resp else "检查 key / base_url")
        except Exception as e:
            add("LLM 连通", False, f"{type(e).__name__}: {e}", "检查 key / base_url / 网络")

    return out


def render(results: List[dict]) -> str:
    lines = ["L-clone 自检:"]
    n_ok = sum(1 for r in results if r["ok"])
    for r in results:
        mark = "✅" if r["ok"] else "❌"
        lines.append(f"{mark} {r['name']}: {r['detail']}")
        if r.get("hint"):
            lines.append(f"   ↳ {r['hint']}")
    lines.append("")
    lines.append(f"通过 {n_ok}/{len(results)}")
    if n_ok < len(results):
        lines.append("按上面 ↳ 的提示修复, 再重跑 lclone doctor")
    return "\n".join(lines)
