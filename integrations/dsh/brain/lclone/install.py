"""接入向导: 把「部署后端」与「接入前端工具」拆成两条命令。

  lclone setup      部署后端: 选 provider + key → 写 .env → init DB → 后端自检 (空项目起步)
  lclone integrate  接入工具: 选 target → 装 skill + 配对应工具钩子/插件 → 集成自检
  lclone install    = setup + integrate 一键全流程(向后兼容)

边界:
  setup     只碰本机后端(.env / 数据库), 不注册项目、不碰任何 AI 工具前端。
  integrate 只碰 AI 工具前端(skill / hooks / 插件), 不碰模型与数据库配置。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

from . import config, db as db_mod, presets, tui
from .doctor import home_dir

# integrate 可选的目标端
TARGETS = ("skill", "dsh", "claude", "codex", "commit", "all")


def _package_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _detect_git() -> Optional[Path]:
    try:
        p = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                           capture_output=True, text=True, timeout=10)
    except Exception:
        return None
    return Path(p.stdout.strip()) if p.returncode == 0 else None


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
            f"DSH 插件请手动装 (避免改动当前运行时): "
            f"dsh plugin --profile web add {dsh_dir} -w")
    return results


# ---------------------------------------------------------------- 后端: setup
def setup(provider: Optional[str] = None, api_key: Optional[str] = None,
          yes: bool = False, db_path: Optional[str] = None) -> int:
    """部署后端(空项目起步): provider + key → .env → init DB → 后端自检。

    不注册项目(项目用 lclone proj add 显式添加, 或 remember/capture 时按 git 懒注册)、
    不装 skill、不配 hooks/插件(那些归 integrate)。

    provider 选择: 已有 .env 时直接沿用, 不重复问; 否则交互式方向键单选菜单;
    --provider 显式指定时强制写入(覆盖)。
    """
    interactive = sys.stdin.isatty() and not yes
    lines: List[str] = []
    dbp = db_path or str((Path.cwd() / "lclone.db").resolve())
    env_file = Path.cwd() / ".env"

    # 1. provider + key(已有 .env 则沿用, 不覆盖)
    if env_file.exists() and provider is None:
        lines.append(f"已检测到现有 .env ({env_file}), 沿用现有配置, 跳过 provider 选择")
        config._loaded = False
        config._load_dotenv()
    else:
        if provider is None:
            provider = (tui.select_one(list(presets.PROVIDERS.keys()),
                                       title="选择模型服务商 (方向键选择, 回车确认):",
                                       default=0)
                        if interactive else "deepseek")
        if provider not in presets.PROVIDERS:
            print(f"❌ 未知 provider: {provider} (可选: {', '.join(presets.provider_names())})")
            return 1
        lines.append(f"provider={provider}")
        if api_key is None and provider != "dummy":
            api_key = ""
            if interactive:
                api_key = input("API key: ").strip()
        # 2. 写 .env
        envf = _write_env(provider, api_key, dbp)
        lines.append(f".env → {envf}")
        config._loaded = False
        config._load_dotenv()

    # 3. init DB (空库起步, 不注册任何项目)
    db_mod.init(dbp)
    lines.append(f"数据库 → {dbp}")

    # 4. 后端自检(不含项目/skill/hooks/插件)
    from . import doctor
    llm_backend = (config.get("BRAIN_LLM") or "api").strip().lower()
    lines.append("")
    lines.append(doctor.render(doctor.check_backend(db_path=dbp,
                                                    check_llm=llm_backend != "dummy")))

    print("\n".join(lines))
    return 0


# ---------------------------------------------------------------- 前端: integrate
def integrate(home: Optional[Path] = None, target: Optional[str] = None,
              yes: bool = False) -> int:
    """接入 AI 工具前端: 装 skill + 配 hooks/插件(Claude Code / Codex / DSH / commit)。

    不碰 .env、数据库、项目与模型配置(那些归 setup)。
    target 为空时交互式选择; 非交互(无 tty 或 yes=True)时默认 all。
    """
    home = Path(home) if home else home_dir()
    root = _detect_git()
    interactive = sys.stdin.isatty() and not yes

    if target is None:
        if interactive:
            target = tui.select_one(list(TARGETS),
                                    title="选择要接入的目标端 (方向键选择, 回车确认):",
                                    default=TARGETS.index("all"))
        else:
            target = "all"
    if target not in TARGETS:
        print(f"❌ 未知 target: {target} (可选: {', '.join(TARGETS)})")
        return 1

    lines: List[str] = []

    # 1. skill: 通用基座(任何支持 skill 的环境都用; 单独选 skill 时只装这个)
    lines.append(install_skill(home))

    # 2. 触发 hooks / 插件(仅当目标不是纯 skill 时)
    if target != "skill":
        lines.extend(configure_triggers(home, target, root))

    # 3. 集成自检(只查 skill/hooks/插件)
    from . import doctor
    lines.append("")
    lines.append(doctor.render(doctor.check_integration(home=home)))

    print("\n".join(lines))
    return 0


# ---------------------------------------------------------------- 一键全流程(向后兼容)
def run(provider: Optional[str] = None, api_key: Optional[str] = None,
        target: Optional[str] = None, yes: bool = False,
        db_path: Optional[str] = None, home: Optional[Path] = None) -> int:
    """install = setup + integrate。新用户一键走完; 只想部署后端用 setup, 只想接工具用 integrate。"""
    rc = setup(provider=provider, api_key=api_key, yes=yes, db_path=db_path)
    if rc != 0:
        return rc
    print()
    return integrate(home=home, target=target, yes=yes)
