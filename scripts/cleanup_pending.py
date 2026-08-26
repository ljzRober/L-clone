"""一次性清理脚本: 整理 lclone.db 里的「待确认(pending)决策」。

按当前分工边界分类每条 pending 决策:
  - keep   : 真正属于本项目的、仍然有效的选型/架构/规则约定 -> 转正(active)
  - delete : 代码实现细节(该留 git/spec)、被取代的旧规则、重复项、
             其它项目的(如 Android TextView/EDRichText/MIUI)、过程性 meta -> 删除

用法:
  python scripts/cleanup_pending.py          # 干跑, 只打印分类, 不落库
  python scripts/cleanup_pending.py --apply  # 执行: keep 转正, delete 删除

跑完打印前后计数。可重复跑。
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

# 保证从任意 cwd 运行都能 import 到 lclone 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lclone import db as db_mod, llm


def _ask_json(prompt: str):
    raw = llm.chat([{"role": "user", "content": prompt}], temperature=0.2)
    raw = raw.strip()
    try:
        s = raw[raw.index("["): raw.rindex("]") + 1]
        return json.loads(s)
    except Exception:
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith("["):
                try:
                    return json.loads(line)
                except Exception:
                    continue
        raise SystemExit(f"LLM 输出无法解析: {raw[:500]}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="执行 (默认干跑)")
    ap.add_argument("--db", default=None)
    args = ap.parse_args()

    conn = db_mod.init(args.db)
    rows = conn.execute(
        "SELECT m.id, m.content, p.name AS proj"
        " FROM memories m LEFT JOIN projects p ON p.id=m.project_id"
        " WHERE m.status='pending' ORDER BY m.id"
    ).fetchall()

    print(f"=== 待确认决策 {len(rows)} 条, LLM 分类中... ===")
    if not rows:
        print("(无待确认决策)")
        return

    body = "\n".join(f"#{r['id']} [{r['proj'] or '全局'}]: {r['content'][:100]}" for r in rows)
    prompt = (
        "下面是「lclone 外置大脑」项目的待确认决策。请判断每条该保留还是删除:\n"
        "- delete: 代码实现细节(该留 git/spec, 不该进大脑)、被取代的旧规则(有更新版本)、\n"
        "  重复项、其它项目的(Android TextView/EDRichText/MIUI/StaticLayout 等)、过程性 meta\n"
        "- keep: 真正属于本项目、且仍然有效的选型/架构/规则/约定\n"
        "规则: 同一件事若有多条, 只 keep 最新那条, 旧的标 delete。\n"
        "只输出 JSON 数组: [{\"id\": <id>, \"action\": \"keep\"|\"delete\"}]\n\n" + body
    )
    result = _ask_json(prompt)
    action_map = {item["id"]: item["action"] for item in result}
    keep = [r for r in rows if action_map.get(r["id"]) == "keep"]
    delete = [r for r in rows if action_map.get(r["id"]) == "delete"]
    unknown = [r for r in rows if r["id"] not in action_map]

    print(f"\n=== 分类结果: keep {len(keep)} / delete {len(delete)}"
          + (f" / 未分类 {len(unknown)}" if unknown else "") + " ===\n")
    print("--- 保留 (转正 active) ---")
    for r in keep:
        print(f"  #{r['id']} [{r['proj'] or '全局'}] {r['content'][:64]}")
    print("\n--- 删除 ---")
    for r in delete:
        print(f"  #{r['id']} [{r['proj'] or '全局'}] {r['content'][:64]}")
    if unknown:
        print("\n--- 未分类 (默认保留, 请人工复核) ---")
        for r in unknown:
            print(f"  #{r['id']} [{r['proj'] or '全局'}] {r['content'][:64]}")

    if not args.apply:
        print("\n(干跑模式: 未落库。确认无误后加 --apply 执行)")
        return

    for r in keep:
        conn.execute(
            "UPDATE memories SET status='active', confirmed_at=datetime('now') WHERE id=?",
            (r["id"],),
        )
    for r in delete:
        conn.execute("DELETE FROM memories WHERE id=?", (r["id"],))
    conn.commit()

    print(f"\n=== 已执行: 保留转正 {len(keep)} 条, 删除 {len(delete)} 条 ===")
    for r in conn.execute(
        "SELECT status, COUNT(*) n FROM memories WHERE level='decision'"
        " GROUP BY status ORDER BY status"
    ):
        print(f"  决策 {r['status']:8} {r['n']} 条")


if __name__ == "__main__":
    main()
