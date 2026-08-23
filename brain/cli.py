"""CLI 入口: 大脑的命令行操作。"""

from __future__ import annotations

import argparse
import sys

from . import chat as chat_mod
from . import config
from . import db as db_mod
from . import llm
from . import memory as mem_mod
from . import projects as proj_mod
from . import supervise as sup_mod


def _conn(args) -> None:
    return db_mod.init(args.db)


def _resolve_project(conn, ref) -> int | None:
    if ref is None:
        return None
    if ref.isdigit():
        row = proj_mod.get_project(conn, int(ref))
        if row:
            return row["id"]
    row = conn.execute(
        "SELECT id FROM projects WHERE name=?", (ref,)
    ).fetchone()
    if row:
        return row["id"]
    raise SystemExit(f"项目不存在: {ref} (用 brain proj list 查看)")


def cmd_init(args) -> None:
    _conn(args)
    print(f"数据库已初始化: {config.db_path()} | LLM 后端: {llm.backend()}")


def cmd_proj(args) -> None:
    conn = _conn(args)
    ref = args.project or args.name  # sync/rm/show 可用位置参数或 --project
    if args.action == "add":
        pid = proj_mod.add_project(conn, args.name, args.path, args.charter)
        print(f"项目已注册: id={pid} name={args.name}")
    elif args.action == "list":
        rows = proj_mod.list_projects(conn)
        if not rows:
            print("(暂无项目)")
        for r in rows:
            print(f"#{r['id']} {r['name']}  charter={r['charter'] or '-'}  "
                  f"记忆={r['mem_count']} spec索引={r['spec_count']}  path={r['path']}")
    elif args.action == "sync":
        pid = _resolve_project(conn, ref)
        res = proj_mod.sync_project(conn, pid)
        print(f"同步完成: 新增 {res['added']}, 更新 {res['updated']}, 未变 {res['unchanged']}")
    elif args.action == "rm":
        pid = _resolve_project(conn, ref)
        proj_mod.remove_project(conn, pid)
        print(f"已删除项目 #{pid} (其记忆仍在, project 字段清空)")
    elif args.action == "show":
        pid = _resolve_project(conn, ref)
        print(proj_mod.project_context(conn, pid) or "(空)")


def cmd_log(args) -> None:
    conn = _conn(args)
    pid = _resolve_project(conn, args.project)
    sid = mem_mod.log_session(conn, pid, title=args.title, summary=args.summary)
    print(f"会话已记录 #{sid}")


def cmd_remember(args) -> None:
    conn = _conn(args)
    pid = _resolve_project(conn, args.project)
    mid = mem_mod.remember(conn, args.content, level=args.level,
                           project_id=pid, reason=args.reason)
    print(f"已主动记忆 #{mid} [active] (level={args.level})")


def cmd_capture(args) -> None:
    conn = _conn(args)
    pid = _resolve_project(conn, args.project)
    ids = mem_mod.capture(conn, args.text, project_id=pid, title=args.title)
    if not ids:
        print("没有提炼出决策 (可能内容里没有确定的决策)")
    else:
        print(f"已生成 {len(ids)} 条决策草稿待确认: {ids}")
        print("运行: brain review")


def cmd_review(args) -> None:
    conn = _conn(args)
    if args.all:
        pending = mem_mod.pending_memories(conn)
        action = (args.all).lower()
        if action not in ("keep", "delete"):
            raise SystemExit("--all 只支持 keep / delete")
        for m in pending:
            mem_mod.review(conn, m["id"], action)
        print(f"已对 {len(pending)} 条草稿执行 {action}")
        return
    if args.id is not None:
        mid = args.id
        action = (args.action or "keep").lower()
        mem_mod.review(conn, mid, action, new_content=args.edit_new)
        print(f"记忆 #{mid} -> {action}")
        return
    pending = mem_mod.pending_memories(conn)
    if not pending:
        print("没有待确认的记忆")
        return
    print(f"共 {len(pending)} 条待确认:")
    for m in pending:
        print(f"\n--- #{m['id']} [level={m['level']}] {m['created_at']} ---")
        print(m["content"])
        act = input("  [k]eep [e]dit [d]elete [s]kip > ").strip().lower()
        if act == "k" or act == "":
            mem_mod.review(conn, m["id"], "keep")
            print("  已保留")
        elif act == "e":
            new = input("  新的内容: ").strip()
            if new:
                mem_mod.review(conn, m["id"], "edit", new_content=new)
                print("  已编辑并保留")
            else:
                print("  跳过")
        elif act == "d":
            mem_mod.review(conn, m["id"], "delete")
            print("  已删除")
        else:
            print("  跳过")


def cmd_recall(args) -> None:
    conn = _conn(args)
    pid = _resolve_project(conn, args.project)
    items = mem_mod.recall(conn, args.query, k=args.k, project_id=pid)
    if not items:
        print("(没有相关记忆)")
    for it in items:
        print(f"[{it['score']:.2f}] #{it['id']} {it['project']}/{it['level']} "
              f"({it['created_at']})\n   {it['content']}")


def cmd_supervise(args) -> None:
    conn = _conn(args)
    pid = _resolve_project(conn, args.project)
    if pid is None:
        raise SystemExit("监督必须指定项目: --proj <id|name>")
    res = sup_mod.supervise(conn, args.proposal, project_id=pid)
    if not res["ok"]:
        raise SystemExit(res["error"])
    print(res["report"])


def cmd_ask(args) -> None:
    conn = _conn(args)
    pid = _resolve_project(conn, args.project)
    res = chat_mod.ask(conn, args.question, project_id=pid,
                       thread_id=args.thread, k=args.k,
                       with_specs=not args.no_specs)
    print(f"[线程 {res['thread_id'][:8]}... | 项目={pid or '个人区'}]")
    if args.verbose and res["recalls"]:
        print("\n-- 召回的记忆 --")
        for r in res["recalls"]:
            print(f"- {r['content']}")
        print()
    print(res["answer"])


def cmd_web(args) -> None:
    from .web import run
    run(host=args.host, port=args.port)


def build_parser() -> argparse.ArgumentParser:
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("--db", default=None,
                        help="数据库路径 (默认 BRAIN_DB_PATH 或 brain.db)")

    p = argparse.ArgumentParser(
        prog="brain",
        description="外置大脑 v0: 分层记忆 + 回顾环 + 规范环",
        parents=[parent],
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", parents=[parent], help="初始化数据库")
    p_init.set_defaults(func=cmd_init)

    sp = sub.add_parser("proj", parents=[parent], help="项目管理")
    sp.add_argument("action", choices=["add", "list", "sync", "rm", "show"])
    sp.add_argument("name", nargs="?", help="项目名 (add/sync/rm/show 用)")
    sp.add_argument("path", nargs="?", default="", help="项目仓库路径 (add 用)")
    sp.add_argument("--charter", default="", help="项目大方向一句话 (add 用)")
    sp.add_argument("--project", default=None, help="项目 id 或名称 (sync/rm/show 用)")
    sp.set_defaults(func=cmd_proj)

    sl = sub.add_parser("log", parents=[parent], help="记录会话流水 (L0)")
    sl.add_argument("summary", help="一句话摘要")
    sl.add_argument("--title", default="")
    sl.add_argument("--project", default=None)
    sl.set_defaults(func=cmd_log)

    sr = sub.add_parser("remember", parents=[parent], help="主动记忆 (C, 直接生效)")
    sr.add_argument("content")
    sr.add_argument("--level", default="decision",
                    choices=["decision", "milestone", "note"])
    sr.add_argument("--reason", default="")
    sr.add_argument("--project", default=None)
    sr.set_defaults(func=cmd_remember)

    sc = sub.add_parser("capture", parents=[parent], help="自动捕获决策 (B, 进草稿待确认)")
    sc.add_argument("text", help="本次工作/讨论内容")
    sc.add_argument("--title", default="")
    sc.add_argument("--project", default=None)
    sc.set_defaults(func=cmd_capture)

    sv = sub.add_parser("review", parents=[parent], help="确认草稿记忆")
    sv.add_argument("--id", type=int, default=None)
    sv.add_argument("--action", choices=["keep", "edit", "delete"], default="keep")
    sv.add_argument("--edit-new", default=None)
    sv.add_argument("--all", choices=["keep", "delete"], default=None,
                    help="对全部草稿批量执行 keep/delete")
    sv.set_defaults(func=cmd_review)

    sr2 = sub.add_parser("recall", parents=[parent], help="回顾检索 (回顾环)")
    sr2.add_argument("query")
    sr2.add_argument("--project", default=None)
    sr2.add_argument("--k", type=int, default=5)
    sr2.set_defaults(func=cmd_recall)

    ss = sub.add_parser("supervise", parents=[parent], help="边界监督 (规范环)")
    ss.add_argument("proposal", help="新提议")
    ss.add_argument("--project", required=True)
    ss.set_defaults(func=cmd_supervise)

    sa = sub.add_parser("ask", parents=[parent], help="带记忆的问答")
    sa.add_argument("question")
    sa.add_argument("--project", default=None)
    sa.add_argument("--thread", default=None)
    sa.add_argument("--k", type=int, default=5)
    sa.add_argument("--no-specs", action="store_true")
    sa.add_argument("--verbose", "-v", action="store_true")
    sa.set_defaults(func=cmd_ask)

    sw = sub.add_parser("web", parents=[parent], help="启动 Web 面板")
    sw.add_argument("--host", default=config.get("BRAIN_HOST"))
    sw.add_argument("--port", type=int, default=config.get_int("BRAIN_PORT", 8000))
    sw.set_defaults(func=cmd_web)

    return p


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
