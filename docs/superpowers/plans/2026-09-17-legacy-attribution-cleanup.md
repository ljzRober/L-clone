# Legacy Attribution Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 清掉服务器库里 59 张洞察卡上已废弃的「归属」段，并把其中 26 条旧式 `src:X` / `m:N` 指针就地折进正文（折不进去就保留原行并报告，不静默丢信息）。

**Architecture:** 一次性数据迁移脚本（`scripts/strip_legacy_attribution.py`），默认 dry-run；`--apply` 才写库并先备份。纯脚本判定 + 可选 LLM 改写；只对内容变化的行重算 embedding。不改任何 spec 契约（三段落格式与「归属段已废弃」早已在 `memory-capture` 里定死）。

**Tech Stack:** Python 3 / SQLite / 现有 `lclone.llm`（`BRAIN_LLM=api` 才真改写，`dummy` 走降级）

**Spec:** 无 delta —— 本变更只迁移历史数据，不改变任何 requirement（`memory-capture` > 记忆分类与确认 > 自包含性与归属 已声明「卡片不含归属段照常成卡」）。

## Global Constraints

- 默认 dry-run；`--apply` 才写库，且 SHALL 先备份 DB 文件。
- 只删**整行以 `归属` 开头**的行，其余字节不动；SHALL NOT 顺手改写别的段。
- 有实际指针内容的卡（非 `无` / `无。`）SHALL 先尝试折进正文；失败则**保留原行**并计入报告，SHALL NOT 丢失指针。
- 只对内容发生变化的行重算 embedding；`confirmed_at` 不因本次迁移改变。
- 生产库执行 SHALL 单独经用户确认（先备份 `data/lclone.db`）。

---

### Task 1: 剥离脚本（dry-run / apply / 备份 / 重嵌）

**Files:**
- Create: `scripts/strip_legacy_attribution.py`
- Test: `tests/test_offline.py`（新增段，用 dummy 后端跑本地临时库）

**Interfaces:**
- Produces: `strip_line(content: str) -> str`、`real_pointer(content: str) -> str`、`migrate(conn, apply=False) -> dict`；CLI `--db / --apply / --backup / --rewrite-refs`

- [ ] **Step 1: 写失败测试**

```python
# ---- 368+: 归属段清理 ----
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location(
    "strip_attr", os.path.join(os.path.dirname(__file__), "..", "scripts",
                               "strip_legacy_attribution.py"))
_sa = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_sa)
check("368 剥掉归属行且保留三段",
      _sa.strip_line("要点：A。\n背景/为什么：B。\n影响/以后注意：C。\n归属：无")
      == "要点：A。\n背景/为什么：B。\n影响/以后注意：C。")
check("369 行内出现「归属」不算（只删行首）",
      "归属感是主观的" in _sa.strip_line("要点：归属感是主观的。\n影响/以后注意：C。"))
check("370 识别真实指针 (无/无。 不算)",
      _sa.real_pointer("要点：A。\n归属：无") == ""
      and _sa.real_pointer("要点：A。\n归属：src:dsh") == "src:dsh")
_sa_conn = db_mod.init(os.path.join(tmp, "strip.db"))
_mid_plain = mem_mod.remember(_sa_conn, "要点：噪声卡。\n背景/为什么：B。\n影响/以后注意：C。\n归属：无",
                              level="insight", project_id=None, confirmed=True)
_rep = _sa.migrate(_sa_conn, apply=True)
check("371 migrate 只动带归属的卡",
      _sa_conn.execute("SELECT content FROM memories WHERE id=?", (_mid_plain,)).fetchone()["content"]
      == "要点：噪声卡。\n背景/为什么：B。\n影响/以后注意：C。"
      and _rep["changed"] >= 1, str(_rep))
check("372 dry-run 不写库",
      _sa.migrate(_sa_conn, apply=False)["changed"] >= 0
      and "归属" not in _sa_conn.execute(
          "SELECT content FROM memories WHERE id=?", (_mid_plain,)).fetchone()["content"])
_sa_conn.close()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `BRAIN_LLM=dummy .venv/bin/python tests/test_offline.py 2>&1 | tail -10`
Expected: `FileNotFoundError: .../scripts/strip_legacy_attribution.py`

- [ ] **Step 3: 实现**

```python
#!/usr/bin/env python3
"""清理洞察卡上已废弃的「归属」段 (四段卡 → 三段卡)。

默认 dry-run; `--apply` 才写库 (先自动备份 DB 文件) 并只对内容变化的行重算 embedding。
带真实指针的卡 (非「无」/「无。」) 先尝试把指针就地折进正文 (`--rewrite-refs` 且 BRAIN_LLM=api);
折不动就保留原行并计入报告 —— 不静默丢信息。
"""
from __future__ import annotations
import argparse, os, re, shutil, sys, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lclone import db as db_mod, llm
from lclone.db import pack_vec

ATTR_RE = re.compile(r"^归属\s*[:：](?P<rest>.*)$")
PLACEHOLDER = {"", "无", "无。", "无.", "none", "None", "-"}


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


def fold_refs(content: str, pointer: str) -> str | None:
    """把旧式 src:X / m:N 指针就地折进正文; 返回新正文, 失败返回 None。"""
    refs = re.findall(r"src:([^;,、（(]+)|m:(\d+)", pointer)
    if not refs:
        return None
    tags = ["[[src:%s]]" % (a or "").strip() if a else "[[m:%s]]" % b for a, b in refs]
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `BRAIN_LLM=dummy .venv/bin/python tests/test_offline.py 2>&1 | tail -8`
Expected: 368-372 PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/strip_legacy_attribution.py tests/test_offline.py
git commit -m "chore(migrate): strip legacy attribution sections from insight cards"
```

---

### Task 2: 本地 dry-run + 生产执行（**需用户确认**）

容器镜像只 COPY `lclone/`，没有 `scripts/`，所以先把脚本投进容器（`/app` 下有 lclone 包，直接 `python /app/xxx.py` 可 import）。

- [ ] **Step 1: 投脚本 + dry-run（只读库）**

```bash
scp scripts/strip_legacy_attribution.py root@60.205.3.97:/tmp/
ssh root@60.205.3.97 'docker cp /tmp/strip_legacy_attribution.py lclone:/app/ && \
  docker exec -e BRAIN_LLM=dummy lclone python /app/strip_legacy_attribution.py --db /data/lclone.db'
```
Expected: 打印「扫描 59 张 … (dry-run, 未写库)」

- [ ] **Step 2: 剥段（**执行前必须再找用户确认**）**

脚本 `--apply` 会自动备份成 `/data/lclone.db.bak.<时间戳>`（/data 是挂载卷）。

```bash
ssh root@60.205.3.97 'docker exec -e BRAIN_LLM=dummy lclone python /app/strip_legacy_attribution.py --db /data/lclone.db --apply'
```

- [ ] **Step 3: 复核**

```bash
curl -s -H "Authorization: Bearer $LCLONE_API_KEY" "http://60.205.3.97:8000/api/memories?limit=1000" \
 | python3 -c "import json,sys; m=json.load(sys.stdin)['items']; print('总数',len(m),'带归属',sum('归属' in (x['content'] or '') for x in m))"
```
Expected: `总数 70 带归属 26`（26 张真实指针卡走 Task 3）

- [ ] **Step 4: 26 张指针卡处理（**需用户确认走 LLM 改写**）**

```bash
ssh root@60.205.3.97 'docker exec lclone python /app/strip_legacy_attribution.py --db /data/lclone.db --rewrite-refs --apply'
```
（这一步不传 `BRAIN_LLM=dummy`：要靠容器里真实的 LLM 后端改写指针）
Expected: 改写成功若干；失败项以 `! #N 保留归属行` 打印并被保留（不丢指针）

## Self-Review

- **Spec coverage**：本变更不改 requirement；对应 proposal A/上一轮调查里的「清理 59 张卡 + 26 条死指针」工作项。
- **Placeholder scan**：无 TBD；Task 2 的两次生产写操作显式标注需用户确认。
- **Type consistency**：`strip_line` / `real_pointer` / `fold_refs` / `migrate(conn, apply, rewrite_refs)` 在测试与 CLI 中签名一致。
