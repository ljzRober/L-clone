"""一次性清理脚本: 按当前规则整理 lclone.db 里的历史记忆。

1. 决策分类: LLM 判断每条 pending/active 决策是「真选型/规则(keep)」还是「代码改动/其他项目(delete)」
2. 记录聚合: LLM 把 note 按主题聚合成 5-8 条 (带 module)
3. 执行: 删 delete、keep 决策转正、note 替换为聚合结果

跑完打印前后计数。可重复跑。
"""

import json
import sqlite3

from lclone import db as db_mod, llm

conn = db_mod.init()


def _ask_json(prompt: str):
    raw = llm.chat([{"role": "user", "content": prompt}], temperature=0.2)
    raw = raw.strip()
    # 容错: 截取第一个 [ 到最后一个 ]
    try:
        s = raw[raw.index("["): raw.rindex("]") + 1]
        return json.loads(s)
    except Exception:
        # 兜底: 逐行找 JSON 数组
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith("["):
                try:
                    return json.loads(line)
                except Exception:
                    continue
        raise SystemExit(f"LLM 输出无法解析: {raw[:500]}")


# ---- 1. 决策分类 ----
decs = conn.execute(
    "SELECT id, content FROM memories WHERE level='decision'"
).fetchall()
print(f"=== 决策 {len(decs)} 条, LLM 分类中... ===")
if decs:
    body = "\n".join(f"#{r['id']}: {r['content'][:80]}" for r in decs)
    prompt = (
        "下面是「lclone 外置大脑」项目的决策。请判断每条:\n"
        "- delete: 不属于本项目(如 Android TextView/EDRichText/MIUI 等其它项目的)、"
        "或属于代码实现细节(该留在 git/spec, 不该进大脑)\n"
        "- keep: 真正属于本项目的选型/架构/规则约定\n"
        "只输出 JSON 数组: [{\"id\": <id>, \"action\": \"keep\"|\"delete\"}]\n\n" + body
    )
    dec_result = _ask_json(prompt)
    dec_map = {item["id"]: item["action"] for item in dec_result}
    keep_ids = [i for i, a in dec_map.items() if a == "keep"]
    del_ids = [i for i, a in dec_map.items() if a == "delete"]
else:
    keep_ids, del_ids = [], []

# ---- 2. 记录聚合 ----
notes = conn.execute(
    "SELECT id, content FROM memories WHERE level='note' AND status='active'"
).fetchall()
print(f"=== note {len(notes)} 条, LLM 聚合中... ===")
if notes:
    body = "\n".join(f"#{r['id']}: {r['content'][:80]}" for r in notes)
    prompt = (
        "下面是「lclone 外置大脑」项目的记录(note)。请按主题聚合成 5~8 条, 每条给:\n"
        "- module: 主题英文短名 (如 web / server / memory-capture / dsh-plugin / cli / deploy)\n"
        "- content: 中文一句话摘要, 保留关键事实\n"
        "不属于 lclone 项目的(如 Android TextView 相关)直接忽略。\n"
        "只输出 JSON 数组: [{\"module\": \"web\", \"content\": \"...\"}]\n\n" + body
    )
    note_result = _ask_json(prompt)
else:
    note_result = []

# ---- 3. 执行 ----
# 删 delete 决策
for mid in del_ids:
    conn.execute("DELETE FROM memories WHERE id=?", (mid,))
# keep 决策转正 (pending -> active)
for mid in keep_ids:
    conn.execute(
        "UPDATE memories SET status='active', confirmed_at=datetime('now') WHERE id=?",
        (mid,),
    )
# 删所有旧 note, 插入聚合结果
note_ids = [r["id"] for r in notes]
for mid in note_ids:
    conn.execute("DELETE FROM memories WHERE id=?", (mid,))
for item in note_result:
    module = (item.get("module") or "").strip()
    content = (item.get("content") or "").strip()
    if not content:
        continue
    emb = llm.embed_one(content)
    conn.execute(
        "INSERT INTO memories(project_id, level, module, content, reason, status,"
        " source_type, source_ref, embedding, confirmed_at)"
        " VALUES (1, 'note', ?, ?, '数据清理聚合', 'active', 'manual', '', ?, datetime('now'))",
        (module, content, db_mod.pack_vec(emb)),
    )
conn.commit()

# ---- 4. 输出结果 ----
print("\n=== 清理后分布 ===")
for r in conn.execute(
    "SELECT level, status, COUNT(*) n FROM memories GROUP BY level, status ORDER BY level, status"
):
    print(f"  {r['level']:10} {r['status']:8} {r['n']} 条")
print("\n=== 决策保留/删除 ===")
print(f"  决策 keep(转正): {len(keep_ids)} 条")
print(f"  决策 delete: {len(del_ids)} 条")
print(f"\n=== note 聚合 ===")
print(f"  旧 note: {len(note_ids)} 条 -> 新 note: {len(note_result)} 条")
for item in note_result:
    print(f"  [{item.get('module','')}] {item.get('content','')[:60]}")
