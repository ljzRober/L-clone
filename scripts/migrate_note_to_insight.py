#!/usr/bin/env python3
"""一次性迁移: 旧 note 通道数据 -> insight (确定性, 无需 LLM)。

- 有价值的 note(知识/gotcha) -> 转 insight(保留原内容, 重新 embed)。
- 噪声 note(原始回合转储/系统提示/排错流水账/空壳) -> 删除。
- 全部 insight 重新 embed (一致性)。
- 默认 dry-run 打报告; `--apply` 才写库。备份请先做。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lclone import db as db_mod
from lclone import llm
from lclone.db import pack_vec

# 人工复核后的"值得留"note (知识/gotcha) 与"噪声"note (转储/提示/流水账)。
# 备份在 lclone.db.bak.*; 若分类有误可回滚后调整此处。
PROMOTE = {213, 223, 236, 263, 269, 272, 284, 288, 294, 296, 306, 307, 317, 336, 339, 347, 402, 410}
NOISE = {278, 280, 285, 316, 319, 388, 389}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=None)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    conn = db_mod.init(args.db)

    notes = conn.execute("SELECT id, project_id, content, source_ref FROM memories"
                         " WHERE level='note' ORDER BY id").fetchall()
    promoted = deleted = 0
    for n in notes:
        if n["id"] in PROMOTE:
            if args.apply:
                emb = llm.embed_one(n["content"])
                conn.execute(
                    "INSERT INTO memories(project_id, level, content, reason, status,"
                    " source_type, source_ref, embedding, confirmed_at)"
                    " VALUES (?, 'insight', ?, 'note→insight 迁移', 'active','manual', ?, ?, datetime('now'))",
                    (n["project_id"], n["content"], n["source_ref"], pack_vec(emb)),
                )
                conn.execute("DELETE FROM memories WHERE id=?", (n["id"],))
            promoted += 1
        else:
            if args.apply:
                # 非 PROMOTE 一律删 (未列入的按噪声处理)
                conn.execute("DELETE FROM memories WHERE id=?", (n["id"],))
            deleted += 1
    # 一致性: 全部 insight 重新 embed
    if args.apply:
        for r in conn.execute("SELECT id, content FROM memories WHERE level='insight'").fetchall():
            conn.execute("UPDATE memories SET embedding=? WHERE id=?",
                         (pack_vec(llm.embed_one(r["content"])), r["id"]))
        conn.commit()
    print(f"note 总数 {len(notes)}; 转 insight {promoted}; 删除 {deleted}", flush=True)
    print("转 insight 的 id:", sorted(PROMOTE), flush=True)
    print("删除的 id:", sorted(NOISE), flush=True)
    print(("\n(dry-run, 未写库; 加 --apply 真执行)" if not args.apply else "\n已执行"), flush=True)


if __name__ == "__main__":
    main()
