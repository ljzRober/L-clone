#!/usr/bin/env python3
"""清理洞察卡上已废弃的「归属」段 (四段卡 → 三段卡)。

背景: 三段卡变更 (commit 03f45bb / spec change insight-three-section-card) 只改了提炼提示词、
校验与前端渲染, 没有对既有库做数据迁移 —— 线上仍有大量卡片带 `归属：无` 噪声行与旧式
`src:X` / `m:N` 指针 (旧语法已不被前端渲染成芯片, 属死文本)。

默认 dry-run; `--apply` 才写库 (先自动备份 DB 文件) 并只对内容变化的行重算 embedding。
带真实指针的卡 (非「无」/「无。」) 加 `--rewrite-refs` 时用 LLM 把指针就地折进正文;
折不动就保留原行并计入报告 —— 不静默丢信息。
"""

from __future__ import annotations

import argparse
import datetime
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lclone import db as db_mod  # noqa: E402
from lclone import llm  # noqa: E402
from lclone.db import pack_vec  # noqa: E402

ATTR_RE = re.compile(r"^归属\s*[:：](?P<rest>.*)$")
PLACEHOLDER = {"", "无", "无。", "无.", "none", "None", "-", "——"}


def strip_line(content: str) -> str:
    """删掉整行以「归属」开头的行, 其余字节不动。"""
    lines = [ln for ln in (content or "").splitlines() if not ATTR_RE.match(ln)]
    return "\n".join(lines).rstrip("\n")


def real_pointer(content: str) -> str:
    """取该卡「归属」段里的实际指针内容; 无 / 无。 → 空串。"""
    for ln in (content or "").splitlines():
        m = ATTR_RE.match(ln)
        if m:
            v = m.group("rest").strip()
            return "" if v in PLACEHOLDER else v
    return ""


def fold_refs(content: str, pointer: str):
    """把旧式 src:X / m:N 指针就地折进正文; 返回新正文, 失败返回 None。"""
    refs = re.findall(r"src:([^;,、（(]+)|m:(\d+)", pointer)
    if not refs:
        return None
    tags = ["[[src:%s]]" % a.strip() if a else "[[m:%s]]" % b for a, b in refs]
    prompt = ("把下面这段洞察改写成三段卡(要点 / 背景/为什么 / 影响/以后注意)。"
              "把源文件/记忆引用就地写进提到它的那句话里, 用 " + " ".join(tags) +
              " 这些标记, 不要另起一行做引用列表。只输出改写后的卡片。\n\n" + content)
    try:
        out = llm.chat([{"role": "user", "content": prompt}], temperature=0.2).strip()
    except Exception:
        return None
    return out if (len(out) > 20 and "要点" in out) else None


def migrate(conn, apply: bool = False, rewrite_refs: bool = False) -> dict:
    rows = conn.execute(
        "SELECT id, content FROM memories WHERE level='insight' AND content LIKE '%归属%'"
    ).fetchall()
    rep = {"scanned": len(rows), "changed": 0, "kept_pointer": 0, "rewritten": 0}
    for r in rows:
        pointer = real_pointer(r["content"])
        new = strip_line(r["content"])
        if pointer:
            fixed = fold_refs(r["content"], pointer) if rewrite_refs else None
            if fixed:
                new = strip_line(fixed)
                rep["rewritten"] += 1
            else:
                rep["kept_pointer"] += 1
                print(f"  ! #{r['id']} 保留归属行 (指针: {pointer[:60]})")
                continue
        if new == r["content"]:
            continue
        rep["changed"] += 1
        print(f"  ✓ #{r['id']} {r['content'][:40]} → {new[:40]}")
        if apply:
            conn.execute("UPDATE memories SET content=?, embedding=? WHERE id=?",
                         (new, pack_vec(llm.embed_one(new)), r["id"]))
            conn.commit()
    return rep


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=None)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--rewrite-refs", action="store_true",
                    help="用 LLM 把旧式 src:/m: 指针就地折进正文 (需 BRAIN_LLM=api)")
    ap.add_argument("--backup", default="")
    args = ap.parse_args()
    dbp = args.db or db_mod.config.db_path()
    if args.apply:
        bkp = args.backup or f"{dbp}.bak.{datetime.datetime.now():%Y%m%d%H%M%S}"
        shutil.copy2(dbp, bkp)
        print(f"已备份: {bkp}")
    conn = db_mod.init(dbp)
    rep = migrate(conn, apply=args.apply, rewrite_refs=args.rewrite_refs)
    print(f"\n扫描 {rep['scanned']} 张, 改写 {rep['rewritten']} 张, "
          f"保留指针 {rep['kept_pointer']} 张, 剥段 {rep['changed']} 张")
    print("(dry-run, 未写库)" if not args.apply else "已执行")
    conn.close()


if __name__ == "__main__":
    main()
