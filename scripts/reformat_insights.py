#!/usr/bin/env python3
"""把全部 insight 重排成四段卡(要点|背景|影响|归属)。小批(2)+降批重试, 可靠。

默认 dry-run 打报告; --apply 才写库并重新 embed。备份请先做。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("BRAIN_LLM", "api")

from lclone import db as db_mod
from lclone import llm
from lclone.db import pack_vec


def chat_json_retry(prompt, start_batch):
    for batch in (start_batch, max(start_batch // 2, 1), 1):
        try:
            arr = llm.chat_json(prompt, temperature=0.2)
        except Exception as e:
            print(f"    chat_json err: {e}", flush=True)
            return []
        if arr:
            return arr
    return []


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=None)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--batch", type=int, default=2)
    args = ap.parse_args()
    conn = db_mod.init(args.db)
    ins = conn.execute("SELECT id, content FROM memories WHERE level='insight' ORDER BY id").fetchall()
    done = fail = 0
    for start in range(0, len(ins), args.batch):
        chunk = ins[start:start + args.batch]
        body = "\n".join(f"#{r['id']}: {r['content']}" for r in chunk)
        prompt = (
            "把下面 insight 改写成统一四段卡(尽量保持原意, 只补结构):\n"
            "「要点(结论)｜背景/为什么｜影响/以后注意｜归属(项目级可标 [[spec:id]]/[[src:path]])」, 自然一段(2-4 句), 中文。\n"
            "不改变原意、不添加未提及事实。只输出 JSON 数组 [{\"id\":<id>,\"insight\":\"<四段卡>\"}], 中文。\n\n" + body
        )
        print(f"· 批次 {start}-{start+len(chunk)}", flush=True)
        verdicts = chat_json_retry(prompt, args.batch)
        was = {v.get("id"): v for v in verdicts}
        for r in chunk:
            v = was.get(r["id"])
            if not v or not str(v.get("insight") or "").strip():
                fail += 1
                print(f"  ✗ #{r['id']} 解析失败(跳过)", flush=True)
                continue
            new = str(v["insight"]).strip()
            if args.apply:
                conn.execute(
                    "UPDATE memories SET content=?, embedding=?,"
                    " confirmed_at=COALESCE(confirmed_at, datetime('now')) WHERE id=?",
                    (new, pack_vec(llm.embed_one(new)), r["id"]),
                )
            done += 1
    if args.apply:
        conn.commit()
    print(f"\n完成 {done} 条, 失败/跳过 {fail} 条", flush=True)
    print("(dry-run, 未写库)" if not args.apply else "已执行", flush=True)


if __name__ == "__main__":
    main()
