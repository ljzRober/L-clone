#!/usr/bin/env python3
"""清理洞察卡上已废弃的「归属」段 (四段卡 → 三段卡)。

背景: 三段卡变更 (commit 03f45bb / spec change insight-three-section-card) 只改了提炼提示词、
校验与前端渲染, 没有对既有库做数据迁移 —— 线上仍有大量卡片带 `归属：无` 噪声行与旧式
`src:X` / `m:N` 指针 (旧语法已不被前端渲染成芯片, 属死文本)。

默认 dry-run (不写库、不调 LLM); `--apply` 才写库 (先按 WAL 安全方式备份) 并只对内容变化的行
重算 embedding。带真实指针的卡 (非「无」/「无。」) 加 `--rewrite-refs` 时用 LLM 把指针就地
折进正文; 折不动就保留原行并计入报告 —— 不静默丢信息。
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
_PLACEHOLDER_RE = re.compile(r"^[\s（(【\[]*(无|暂无|没有|n/?a|na|null|none|nil|-|—|/)[\s）)】\]。.,，]*$",
                             re.IGNORECASE)
_REF_RE = re.compile(r"src:([^;,、（(]+)|m:(\d+)")


def is_placeholder(value: str) -> bool:
    """「归属」段是空话 (无 / 无。 / 暂无 / N/A …) 还是真指针。"""
    v = (value or "").strip()
    if not v:
        return True
    return bool(_PLACEHOLDER_RE.match(v.casefold().replace(" ", "")))


def strip_line(content: str) -> str:
    """删掉整行以「归属」开头的行, 其余字节不动 (含 U+2028 等原样保留)。"""
    lines = [ln for ln in (content or "").split("\n")
             if not ATTR_RE.match(ln.rstrip("\r"))]
    return "\n".join(lines)


def real_pointer(content: str) -> str:
    """取该卡所有「归属」段里的实际指针内容 (拼接); 全是空话 → 空串。

    注意: 必须看**全部** 归属 行 —— 只看首行会让「归属：无」+「归属：src:x」这种卡
    在 strip 时把真实指针一起删掉。
    """
    ptrs = []
    for ln in (content or "").split("\n"):
        m = ATTR_RE.match(ln.rstrip("\r"))
        if m:
            v = m.group("rest").strip()
            if not is_placeholder(v):
                ptrs.append(v)
    return "; ".join(ptrs)


def fold_refs(content: str, pointer: str):
    """把旧式 src:X / m:N 指针就地折进正文; 返回新正文, 失败/不成形返回 None。"""
    refs = _REF_RE.findall(pointer)
    if not refs:
        return None
    tags = ["[[src:%s]]" % a.strip() for a, _b in refs if a.strip()]
    tags += ["[[m:%s]]" % b for _a, b in refs if b]
    if not tags:
        return None
    prompt = ("把下面这段洞察改写成三段卡(要点 / 背景/为什么 / 影响/以后注意)。"
              "把源文件/记忆引用就地写进提到它的那句话里, 用 " + " ".join(tags) +
              " 这些标记, 不要另起一行做引用列表。只输出改写后的卡片。\n\n" + content)
    try:
        out = llm.chat([{"role": "user", "content": prompt}], temperature=0.2).strip()
    except Exception:
        return None
    if not (len(out) > 20 and "要点" in out and ("背景" in out or "影响" in out)):
        return None
    if ATTR_RE.match(out.split("\n", 1)[0]):     # 模型把归属段又写回来了
        return None
    if not any(t in out for t in tags):           # 指针必须真的落在正文里, 否则视为改写失败
        return None
    return out


def is_project_name(conn, pointer: str) -> bool:
    """「归属：<项目名>」是冗余的 —— 项目归属已由 project_id 表达, 不是引用。"""
    parts = [x.strip() for x in re.split(r"[;；,，、]", pointer or "") if x.strip()]
    if not parts:
        return False
    for name in parts:
        if conn.execute("SELECT 1 FROM projects WHERE name=?", (name,)).fetchone() is None:
            return False
    return True


def migrate(conn, apply: bool = False, rewrite_refs: bool = False) -> dict:
    """扫 level=insight 且含「归属」的卡; 返回报告 (不改库除非 apply=True)。"""
    rows = conn.execute(
        "SELECT id, content FROM memories WHERE level='insight' AND content LIKE '%归属%'"
    ).fetchall()
    rep = {"scanned": len(rows), "changed": 0, "kept_pointer": 0, "rewritten": 0}
    for r in rows:
        pointer = real_pointer(r["content"])
        if pointer and not _REF_RE.search(pointer) and is_project_name(conn, pointer):
            rep["project_name_only"] = rep.get("project_name_only", 0) + 1
            pointer = ""          # 纯项目名 → 当空话剥掉 (归属由 project_id 表达)
        new = strip_line(r["content"])
        if pointer:
            # dry-run 不调 LLM (省钱且无副作用); 只有真要写库时才尝试改写
            fixed = fold_refs(r["content"], pointer) if (rewrite_refs and apply) else None
            if fixed:
                new = strip_line(fixed)
                rep["rewritten"] += 1
            else:
                rep["kept_pointer"] += 1
                why = "将改写" if (rewrite_refs and not apply) else "保留归属行"
                print(f"  ! #{r['id']} {why} (指针: {pointer[:60]})")
                if not rewrite_refs or not apply:
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
                    help="用 LLM 把旧式 src:/m: 指针就地折进正文 (需 BRAIN_LLM=api; 仅 --apply 时生效)")
    ap.add_argument("--backup", default="", help="显式指定备份文件路径 (默认走 WAL 安全在线备份)")
    args = ap.parse_args()
    dbp = args.db or db_mod.config.db_path()
    if args.apply:
        if args.backup:
            shutil.copy2(dbp, args.backup)
            print(f"已备份: {args.backup}")
        else:
            print(f"已备份(WAL 安全): {db_mod.backup(dbp, str(Path(dbp).resolve().parent / 'backups'))}")
    conn = db_mod.init(dbp)
    rep = migrate(conn, apply=args.apply, rewrite_refs=args.rewrite_refs)
    print(f"\n扫描 {rep['scanned']} 张, 改写 {rep['rewritten']} 张, "
          f"保留指针 {rep['kept_pointer']} 张, "
          f"纯项目名 {rep.get('project_name_only', 0)} 张, 剥段 {rep['changed']} 张")
    print("(dry-run, 未写库)" if not args.apply else "已执行")
    conn.close()


if __name__ == "__main__":
    main()
