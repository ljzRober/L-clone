"""首次种子内容: 给刚装好的人一份「通用洞察 + 通用进化资产」。

为什么需要: 空库状态下用户看不到「一条洞察长什么样、进化资产怎么用」, 冷启动体验为零。
种入的是**通用**内容 (格式约定 / 记忆与 spec 分工 / 归属判定 / 删除纪律), 不绑定任何项目,
也不依赖具体 provider。

幂等设计:
  - `seed_state` 表记录已种过的 key (insight:<标题> / evolution:<文件名>);
    **种过即记, 即使用户事后删掉也不回灌** —— 尊重用户的删除。
  - 进化文件「已存在则不覆盖」, 只有 `--force` 才覆盖 (避免冲掉用户改过的版本)。
  - 洞察落全局层 (project_id IS NULL)、status='active'、source_type='seed'; 不进 pending,
    因为它不是你捕获来的草稿, 是预置内容。
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Tuple

from . import llm
from .db import pack_vec

# 只用于 source_ref 的溯源标记 (seed:v1:<标题>)。注意: **state key 不带版本** ——
# 「删掉不回灌」是硬承诺, 所以加新种子内容要新增 key, 不要靠 bump 版本号。
SEED_VERSION = 1


def starter_dir() -> Path:
    """种子内容目录 (随包分发)。"""
    return Path(__file__).resolve().parent / "data" / "starter"


def _parse_insights(path: Path) -> List[Tuple[str, str]]:
    """解析 insights.md: 每个 `## 标题` 块一条, 标题作稳定 key, 其余为四段卡正文。"""
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    out: List[Tuple[str, str]] = []
    for block in re.split(r"^##\s+", text, flags=re.M)[1:]:
        lines = block.splitlines()
        if not lines:
            continue
        key = lines[0].strip()
        content = "\n".join(lines[1:]).strip()
        if key and content:
            out.append((key, content))
    return out


def _evolution_files() -> List[Path]:
    """种子里的进化文件 (evolutions/ + scripts/, 忽略隐藏文件, 同名只取第一个)。"""
    base = starter_dir()
    seen: set = set()
    files: List[Path] = []
    for sub in ("evolutions", "scripts"):
        d = base / sub
        if not d.is_dir():
            continue
        for p in sorted(d.iterdir()):
            if not p.is_file() or p.name.startswith(".") or p.name in seen:
                continue
            seen.add(p.name)
            files.append(p)
    return files


def available() -> bool:
    """种子包是否随包分发到位 (打包漏了 data/ 时用来显式报错, 而不是静默"已是最新")。"""
    return (starter_dir() / "insights.md").exists()


def _seeded(conn: sqlite3.Connection, key: str) -> bool:
    return conn.execute("SELECT 1 FROM seed_state WHERE key=?", (key,)).fetchone() is not None


def _mark(conn: sqlite3.Connection, key: str) -> None:
    conn.execute("INSERT OR IGNORE INTO seed_state(key) VALUES (?)", (key,))


def apply(conn: sqlite3.Connection, force: bool = False,
          dry_run: bool = False) -> Dict[str, Any]:
    """种入通用洞察与进化文件; 幂等, 重复调用不会重复写。

    force=True:  进化文件覆盖已存在的; 洞察在对应 source_ref 缺失时重新补一条。
    dry_run=True: 只报告会做什么, 不写库、不写文件、不建目录。
    返回 {"insights_added","insights_skipped","evolutions_added",
          "evolutions_skipped","starter_missing"}。
    """
    from . import memory as mem_mod  # 延迟导入, 避免模块级循环

    report: Dict[str, Any] = {
        "insights_added": [], "insights_skipped": [],
        "evolutions_added": [], "evolutions_skipped": [],
        "starter_missing": not available(),
    }
    if report["starter_missing"]:
        return report

    # ---- 通用洞察 (全局层, 直接 active) ----
    for key, content in _parse_insights(starter_dir() / "insights.md"):
        state_key = f"insight:{key}"
        ref = f"seed:v{SEED_VERSION}:{key}"
        exists = conn.execute(
            "SELECT 1 FROM memories WHERE source_ref=?", (ref,)
        ).fetchone() is not None
        if exists or (_seeded(conn, state_key) and not force):
            report["insights_skipped"].append(key)
            continue
        # 库里已有语义/文本近乎相同的记忆 → 不种, 免得制造重复
        if mem_mod._is_text_duplicate(conn, content, None):
            report["insights_skipped"].append(key)
            if not dry_run:
                _mark(conn, state_key)
            continue
        report["insights_added"].append(key)
        if dry_run:
            continue
        emb = llm.embed_one(content)
        conn.execute(
            "INSERT INTO memories(project_id, level, content, reason, status,"
            " source_type, source_ref, embedding, confirmed_at)"
            " VALUES (NULL, 'insight', ?, ?, 'active', 'seed', ?, ?, datetime('now'))",
            (content, "首次安装预置的通用洞察", ref, pack_vec(emb)),
        )
        _mark(conn, state_key)

    # ---- 进化文件 (已存在则不覆盖) ----
    if not dry_run:
        mem_mod.evo_dir()  # 真正要写时才建目录
    evo_root = Path(mem_mod.evo_dir(create=False))
    for src in _evolution_files():
        name = src.name
        state_key = f"evolution:{name}"
        target = evo_root / name
        if _seeded(conn, state_key) and not force:
            report["evolutions_skipped"].append(name)
            continue
        if target.exists() and not force:
            report["evolutions_skipped"].append(name)
            if not dry_run:
                _mark(conn, state_key)
            continue
        report["evolutions_added"].append(name)
        if dry_run:
            continue
        target.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        if src.suffix == ".sh":
            target.chmod(0o755)
        _mark(conn, state_key)

    if not dry_run:
        conn.commit()
    return report


def render(report: Dict[str, Any], force: bool = False,
           dry_run: bool = False) -> str:
    """把 apply 的结果渲染成人话 (setup / CLI 输出用)。"""
    if report.get("starter_missing"):
        return ("⚠️ 种子内容缺失: 找不到 lclone/data/starter/ (安装包不完整), "
                "本次未种入任何内容")
    ins, evo = report["insights_added"], report["evolutions_added"]
    head = "将要种入" if dry_run else "已种入"
    if not ins and not evo:
        return "种子内容: 已是最新 (无需补种)"
    lines = [f"种子内容 ({head}, force={force}):"]
    if ins:
        lines.append(f"  通用洞察 {len(ins)} 条 → 全局层: " + "、".join(ins))
    if evo:
        lines.append(f"  进化文件 {len(evo)} 个 → 进化目录: " + "、".join(evo))
    if report["insights_skipped"] or report["evolutions_skipped"]:
        skip = len(report["insights_skipped"]) + len(report["evolutions_skipped"])
        lines.append(f"  (跳过 {skip} 项: 已存在或已删除)")
    if dry_run:
        lines.append("  (dry-run: 未写入任何内容)")
    return "\n".join(lines)
