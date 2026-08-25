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
    raise SystemExit(f"项目不存在: {ref} (用 lclone proj list 查看)")


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
        print(f"已移除项目 #{pid} (墓碑式: 记忆保留但不再加载; "
              f"复活用 lclone proj restore {ref}, 清理用 lclone suggest)")
    elif args.action == "restore":
        pid = _resolve_project(conn, ref)
        proj_mod.restore_project(conn, pid)
        print(f"已复活项目 #{pid}, 其记忆恢复加载")
    elif args.action == "show":
        pid = _resolve_project(conn, ref)
        print(proj_mod.project_context(conn, pid) or "(空)")


def cmd_log(args) -> None:
    conn = _conn(args)
    pid = _resolve_project(conn, args.project) if args.project else None
    if pid is None and not args.project:
        pid = proj_mod.detect_project_by_git(conn)
    sid = mem_mod.log_session(conn, pid, title=args.title, summary=args.summary)
    where = f"项目 #{pid}" if pid is not None else "全局层"
    print(f"会话已记录 #{sid} [{where}]")


def cmd_remember(args) -> None:
    conn = _conn(args)
    pid = _resolve_project(conn, args.project) if args.project else None
    auto = False
    if pid is None and not args.project:
        pid = proj_mod.detect_project_by_git(conn)
        auto = pid is not None
    mid = mem_mod.remember(conn, args.content, level=args.level,
                           project_id=pid, reason=args.reason, module=args.module)
    where = f"项目 #{pid}" if pid is not None else "全局层"
    tag = " (git 自动归属)" if auto else ""
    print(f"已主动记忆 #{mid} [{where}]{tag} (level={args.level})")


def cmd_capture(args) -> None:
    conn = _conn(args)
    pid = _resolve_project(conn, args.project) if args.project else None
    auto = False
    if pid is None and not args.project:
        pid = proj_mod.detect_project_by_git(conn)
        auto = pid is not None
    ids = mem_mod.capture(conn, args.text, project_id=pid, title=args.title,
                          module=args.module)
    if not ids:
        print("没有提炼出可记忆的内容 (可能没有决策或值得记的事实, 或与已有记忆重复)")
    else:
        where = f"项目 #{pid}" if pid is not None else "全局层"
        tag = " (git 自动归属)" if auto else ""
        print(f"已生成 {len(ids)} 条记忆 [{where}]{tag}: {ids}")
        print("(记录已直接生效; 决策进「待确认」, 运行 lclone review 确认)")


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
    items = mem_mod.recall(conn, args.query, k=args.k, project_id=pid,
                           follow_links=not args.no_follow)
    if not items:
        print("(没有相关记忆)")
    for it in items:
        tag = " 🔗链接" if it.get("via_link") else ""
        print(f"[{it['score'] if it['score'] is not None else '--':>6}] #{it['id']} "
              f"{it['project']}/{it['level']} ({it['created_at']}){tag}\n   {it['content']}")


def cmd_bootstrap(args) -> None:
    conn = _conn(args)
    pid = _resolve_project(conn, args.project) if args.project else None
    out = mem_mod.bootstrap(conn, query=args.query or "", project_id=pid,
                            k=args.k)
    print(out or "(暂无记忆)")


def cmd_doctor(args) -> None:
    from . import doctor
    print(doctor.render(doctor.check_all(db_path=args.db,
                                         check_llm=args.check_llm)))


def cmd_install(args) -> None:
    from . import install as install_mod
    raise SystemExit(install_mod.run(
        provider=args.provider, api_key=args.api_key,
        project=args.project, charter=args.charter,
        target=args.target, yes=args.yes, db_path=args.db))


def cmd_backup(args) -> None:
    from . import db as db_mod
    dest = db_mod.backup(db_path=args.db, dest_dir=args.dest)
    print(f"已备份到 {dest}")


def cmd_promote(args) -> None:
    conn = _conn(args)
    try:
        mem_mod.promote(conn, args.id)
    except ValueError as e:
        raise SystemExit(str(e))
    print(f"记忆 #{args.id} 已上升至全局层 (个人区, 生命周期无限, 多项目共读)")


def cmd_demote(args) -> None:
    conn = _conn(args)
    pid = _resolve_project(conn, args.project)
    try:
        mem_mod.demote(conn, args.id, pid)
    except ValueError as e:
        raise SystemExit(str(e))
    print(f"记忆 #{args.id} 已下降至项目 #{pid}, 生命周期与其绑定")


def cmd_suggest(args) -> None:
    conn = _conn(args)
    items = mem_mod.suggest(conn, dup_threshold=args.dup_threshold,
                            stale_days=args.stale_days,
                            unused_days=args.unused_days)
    if not items:
        print("没有建议清理的记忆 (删除始终由你决定)")
        return
    print(f"发现 {len(items)} 条建议清理的记忆 (仅提示, 删除由你执行):\n")
    for it in items:
        print(f"#{it['id']} [{it['project']}] {it['created_at'][:10]}")
        print(f"   {it['content'][:80]}")
        print(f"   原因: {it['reason']}")
        print(f"   删除: {it['hint']}\n")


def cmd_memories(args) -> None:
    conn = _conn(args)
    pid = _resolve_project(conn, args.project) if args.project else None
    rows = mem_mod.list_memories(conn, project_id=pid, level=args.level,
                                 status=args.status, limit=args.limit)
    if not rows:
        print(f"(暂无 {args.status} 记忆" +
              (f", 项目={args.project}" if args.project else "") + ")")
        return
    for r in rows:
        proj = r["project_name"] or "个人区"
        print(f"#{r['id']} [{proj}/{r['level']}] {r['created_at'][:16]} "
              f"({r['source_type']})")
        print(f"   {r['content']}")
        if r["source_ref"]:
            print(f"   来源: {r['source_ref']}")


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
                        help="数据库路径 (默认 BRAIN_DB_PATH 或 lclone.db)")

    p = argparse.ArgumentParser(
        prog="lclone",
        description="外置大脑 v0: 分层记忆 + 回顾环 + 规范环",
        parents=[parent],
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", parents=[parent], help="初始化数据库")
    p_init.set_defaults(func=cmd_init)

    sp = sub.add_parser("proj", parents=[parent], help="项目管理")
    sp.add_argument("action", choices=["add", "list", "sync", "rm", "restore", "show"])
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
                    choices=["decision", "note"])
    sr.add_argument("--reason", default="")
    sr.add_argument("--module", default="", help="项目内模块名(可选)")
    sr.add_argument("--project", default=None)
    sr.set_defaults(func=cmd_remember)

    sc = sub.add_parser("capture", parents=[parent], help="自动捕获决策/记录 (B, 进草稿待确认)")
    sc.add_argument("text", help="本次工作/讨论内容")
    sc.add_argument("--title", default="")
    sc.add_argument("--module", default="", help="项目内模块名(可选)")
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
    sr2.add_argument("--no-follow", action="store_true",
                     help="不跟随 [[m:N]] 链接 (默认自动带出被链接记忆)")
    sr2.set_defaults(func=cmd_recall)

    sb = sub.add_parser("bootstrap", parents=[parent],
                        help="会话启动引导 (charter+全局记忆+按话题召回)")
    sb.add_argument("query", nargs="?", default="", help="本次话题/首条消息 (可为空)")
    sb.add_argument("--project", default=None)
    sb.add_argument("--k", type=int, default=5)
    sb.set_defaults(func=cmd_bootstrap)

    sd = sub.add_parser("doctor", parents=[parent],
                        help="自检接入是否完整 (✅/❌ 清单)")
    sd.add_argument("--check-llm", action="store_true",
                    help="真调 LLM 验证连通 (默认只查配置)")
    sd.set_defaults(func=cmd_doctor)

    si = sub.add_parser("install", parents=[parent], help="一键接入向导")
    si.add_argument("--provider",
                    choices=["deepseek", "openai", "siliconflow", "zhipu", "dummy"],
                    default=None, help="模型服务商 (默认交互选择)")
    si.add_argument("--api-key", default=None)
    si.add_argument("--project", default=None, help="项目名 (默认取 git 仓库名)")
    si.add_argument("--charter", default=None, help="项目大方向一句话 (默认从 README 猜)")
    si.add_argument("--target", choices=["dsh", "claude", "codex", "commit", "all"],
                    default=None, help="配置哪些触发 (默认 all)")
    si.add_argument("--yes", action="store_true", help="非交互, 用默认值")
    si.set_defaults(func=cmd_install)

    sbk = sub.add_parser("backup", parents=[parent],
                         help="SQLite 在线备份到 backups/")
    sbk.add_argument("--dest", default="backups", help="备份目录 (默认 backups/)")
    sbk.set_defaults(func=cmd_backup)

    spm = sub.add_parser("promote", parents=[parent],
                         help="记忆上升: 项目记忆 -> 全局层 (生命周期无限)")
    spm.add_argument("id", type=int)
    spm.set_defaults(func=cmd_promote)

    sdm = sub.add_parser("demote", parents=[parent],
                         help="记忆下降: 挂到指定项目 (生命周期与之绑定)")
    sdm.add_argument("id", type=int)
    sdm.add_argument("--project", required=True, help="目标项目 id 或名称")
    sdm.set_defaults(func=cmd_demote)

    sgg = sub.add_parser("suggest", parents=[parent],
                         help="删除提示: 算法扫描疑似重复/长期未确认/未召回/已移除项目记忆")
    sgg.add_argument("--dup-threshold", type=float, default=0.92,
                     help="疑似重复的向量相似度阈值")
    sgg.add_argument("--stale-days", type=int, default=7,
                     help="草稿超过 N 天未确认")
    sgg.add_argument("--unused-days", type=int, default=30,
                     help="active 记忆超过 N 天未被召回")
    sgg.set_defaults(func=cmd_suggest)

    sm = sub.add_parser("memories", parents=[parent], help="列出记忆")
    sm.add_argument("--project", default=None, help="只看某项目")
    sm.add_argument("--level", choices=["decision", "note"],
                    default=None, help="只看某等级")
    sm.add_argument("--status", choices=["active", "pending", "archived"],
                    default="active", help="默认只看正式记忆, 草稿用 pending")
    sm.add_argument("--limit", type=int, default=20)
    sm.set_defaults(func=cmd_memories)

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
