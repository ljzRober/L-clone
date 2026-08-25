"""安装向导 (install): 一条命令走完 lclone 接入。

流程: 检测环境 → provider+key → 写 .env → init DB → 注册项目 → 装 skill →
按环境配触发 → 自检。全程可 --yes 非交互。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

from . import config, db as db_mod, presets, projects as proj_mod
from .doctor import home_dir


def _package_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _detect_git() -> Optional[Path]:
    try:
        p = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                           capture_output=True, text=True, timeout=10)
    except Exception:
        return None
    return Path(p.stdout.strip()) if p.returncode == 0 else None


def _guess_charter(root: Path) -> str:
    for name in ("README.md", "README.MD", "readme.md"):
        p = root / name
        if not p.exists():
            continue
        try:
            for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                s = line.strip()
                if not s or s.startswith("#") or s.startswith(">"):
                    continue
                return s[:80]
        except OSError:
            continue
    return ""


def _write_env(provider: str, api_key: str, db_path: str) -> Path:
    env = presets.env_for(provider, api_key=api_key, db_path=db_path)
    target = Path.cwd() / ".env"
    target.write_text(presets.render_env(env), encoding="utf-8")
    return target


def _skill_source() -> Optional[Path]:
    for p in (_package_root() / "integrations/skill/SKILL.md",
              _package_root() / "data/skill/SKILL.md"):
        if p.exists():
            return p
    return None


def install_skill(home: Path, force: bool = False) -> str:
    src = _skill_source()
    if src is None:
        return "⚠️ 找不到 SKILL.md 源文件, 请手动复制到 ~/.agents/skills/lclone-memory/"
    dst = home / ".agents/skills/lclone-memory/SKILL.md"
    if dst.exists() and not force:
        return f"skill 已存在, 跳过 ({dst})"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    return f"skill 已安装 → {dst}"


def _merge_hooks(existing: Dict, ours: Dict) -> Dict:
    merged = dict(existing)
    for event, groups in (ours.get("hooks") or {}).items():
        cur = merged.setdefault("hooks", {}).setdefault(event, [])
        for g in groups:
            cur.append(g)
    return merged


def _configure_claude(home: Path) -> str:
    src = _package_root() / "integrations/claude-code/settings.json"
    ours = json.loads(src.read_text(encoding="utf-8")) if src.exists() else {}
    dst = home / ".claude/settings.json"
    existing = {}
    if dst.exists():
        try:
            existing = json.loads(dst.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
    merged = _merge_hooks(existing, ours)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        shutil.copyfile(dst, dst.with_suffix(".json.bak"))
    dst.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    return f"Claude Code hooks 已合并 → {dst}"


def _configure_codex(home: Path) -> str:
    src = _package_root() / "integrations/codex/hooks.json"
    ours = json.loads(src.read_text(encoding="utf-8")) if src.exists() else {}
    dst = home / ".codex/hooks.json"
    existing = {}
    if dst.exists():
        try:
            existing = json.loads(dst.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
    merged = _merge_hooks(existing, ours)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        shutil.copyfile(dst, dst.with_suffix(".json.bak"))
    dst.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    return f"Codex hooks 已合并 → {dst}"


def _configure_commit(root: Optional[Path]) -> str:
    if root is None or not (root / "scripts/hooks/post-commit").exists():
        return "commit 钩子: 不在本仓库或 scripts/hooks/post-commit 不存在, 跳过"
    try:
        subprocess.run(["git", "-C", str(root), "config", "core.hooksPath",
                        "scripts/hooks"], check=True, timeout=10)
        return f"commit 钩子已启用 (git config core.hooksPath scripts/hooks, 仓库={root})"
    except Exception as e:
        return f"commit 钩子启用失败: {e}"


def configure_triggers(home: Path, target: str, root: Optional[Path]) -> List[str]:
    """按 target 配置触发; 返回逐条结果。DSH 只打印命令, 不自动改运行时。"""
    results: List[str] = []
    if target in ("claude", "all"):
        results.append(_configure_claude(home))
    if target in ("codex", "all"):
        results.append(_configure_codex(home))
    if target in ("commit", "all"):
        results.append(_configure_commit(root))
    if target in ("dsh", "all"):
        dsh_dir = _package_root() / "integrations/dsh"
        results.append(
            f"DSH 插件请手动装 (避免改动当前运行时): dsh plugin --profile web add {dsh_dir}")
    return results


def run(provider: Optional[str] = None, api_key: Optional[str] = None,
        project: Optional[str] = None, charter: Optional[str] = None,
        target: Optional[str] = None, yes: bool = False,
        db_path: Optional[str] = None, home: Optional[Path] = None) -> int:
    home = Path(home) if home else home_dir()
    interactive = sys.stdin.isatty() and not yes
    lines: List[str] = []

    # 1. provider + key
    if provider is None:
        provider = "deepseek"
        if interactive:
            print("可选 provider:", ", ".join(presets.provider_names()))
            v = input(f"选 provider (默认 {provider}): ").strip()
            provider = v or provider
    if provider not in presets.PROVIDERS:
        print(f"❌ 未知 provider: {provider} (可选: {', '.join(presets.provider_names())})")
        return 1
    if api_key is None and provider != "dummy":
        api_key = ""
        if interactive:
            api_key = input("API key: ").strip()
    lines.append(f"provider={provider}")

    # 2. 写 .env
    dbp = db_path or str((Path.cwd() / "lclone.db").resolve())
    envf = _write_env(provider, api_key, dbp)
    lines.append(f".env → {envf}")
    # 刷新 config 缓存, 让后续 init 用新配置
    config._loaded = False
    config._load_dotenv()

    # 3. init DB
    conn = db_mod.init(dbp)
    lines.append(f"数据库 → {dbp}")

    # 4. 注册项目
    root = _detect_git()
    name = project or (root.name if root else Path.cwd().name)
    if charter is None:
        charter = _guess_charter(root) if root else ""
        if interactive:
            v = input(f"charter (默认: {charter or '(空)'}): ").strip()
            if v:
                charter = v
    if root is not None:
        try:
            pid = proj_mod.add_project(conn, name, str(root), charter)
            lines.append(f"项目已注册 #{pid} name={name} charter={charter or '(空)'}")
        except Exception as e:
            lines.append(f"项目注册失败 (可能已存在): {e}")
    else:
        lines.append(f"⚠️ 不在 git 仓库, 跳过项目注册 (可稍后 lclone proj add {name})")

    # 5. 装 skill
    lines.append(install_skill(home))

    # 6. 触发
    if target is None:
        target = "all"
    lines.extend(configure_triggers(home, target, root))

    # 7. 自检
    from . import doctor
    lines.append("")
    lines.append(doctor.render(doctor.check_all(db_path=dbp, home=home)))

    print("\n".join(lines))
    return 0
