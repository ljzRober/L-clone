#!/usr/bin/env python3
"""批量把 insight 重排成四段卡(要点|背景|影响|归属)。行式 `id || 四段卡` 输出+解析, 稳定且快。

默认 dry-run; `--apply` 才写库并重新 embed。备份请先做。
"""

from __future__ import annotations

import argparse
import os
import sys
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("BRAIN_LLM", "api")

from lclone import db as db_mod
from lclone import llm
from lclone.db import pack_vec


def extract_lines(raw: str):
    """把模型输出按行切, 每行解析出 (id, 四段卡)。容错: 去掉 json/代码块围栏。"""
    text = raw.strip()
    text = re.sub(r"^\s*```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```\s*$", "", text)
    out = []
    for line in text.splitlines():
        line = line.strip().strip("-•* ").strip()
        if not line:
            continue
        m = re.match(r"^(\d+)\s*\|\|\s*(.+)$", line)
        if m:
            out.append((int(m.group(1)), m.group(2).strip()))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=None)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--batch", type=int, default=12)
    args = ap.parse_args()
    conn = db_mod.init(args.db)
    ins = conn.execute("SELECT id, content FROM memories WHERE level='insight' ORDER BY id").fetchall()
    done = fail = 0
    for start in range(0, len(ins), args.batch):
        chunk = ins[start:start + args.batch]
        head = "以下每条一行 `id || 内容`。请把每条改写为统一四段卡(保持原意只补结构):\n" \
               "「要点(结论)｜背景/为什么｜影响/以后注意｜归属(项目级可写 src:xx 或 m:NN)」, 自然一段(2-4 句), 中文。\n" \
               "归属若需指向仓库文件/记忆链接, 用纯文本 src:xx 或 m:NN, 不要用 [[ ]] 方括号。\n" \
               "输出格式: 每条一行 `id || 四段卡`, 不要 JSON。\n\n"
        body = "\n".join(f"{r['id']} || {r['content']}" for r in chunk)
        print(f"· 批次 {start}-{start+len(chunk)}", flush=True)
        raw = llm.chat([{"role": "user", "content": head + body}], temperature=0.2).strip()
        parsed = {iid: card for iid, card in extract_lines(raw)}
        for r in chunk:
            card = parsed.get(r["id"])
            if not card or len(card) < 20:
                # 该条没被模型改到 -> 降级单条重试一次
                p2 = ("把下面 insight 改写成统一四段卡(要点|背景|影响|归属), 2-4句, 只输出一行 `id || 四段卡`, 中文, 不要 JSON。\n\n"
                      f"{r['id']} || {r['content']}")
                raw2 = llm.chat([{"role": "user", "content": p2}], temperature=0.2).strip()
                card = extract_lines(raw2)[0][1] if extract_lines(raw2) else ""
            if not card or len(card) < 20:
                fail += 1
                print(f"  ✗ #{r['id']} 失败(跳过)", flush=True)
                continue
            if args.apply:
                conn.execute(
                    "UPDATE memories SET content=?, embedding=?,"
                    " confirmed_at=COALESCE(confirmed_at, datetime('now')) WHERE id=?",
                    (card, pack_vec(llm.embed_one(card)), r["id"]),
                )
                conn.commit()
            done += 1
            print(f"  ✓ #{r['id']} {card[:70]}", flush=True)
    print(f"\n完成 {done} 条, 失败/跳过 {fail} 条", flush=True)
    print("(dry-run, 未写库)" if not args.apply else "已执行", flush=True)


if __name__ == "__main__":
    main()
