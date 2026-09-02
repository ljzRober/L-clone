#!/usr/bin/env python3
"""L-clone MCP 服务器 (零第三方依赖)。

把外置大脑的记忆能力暴露给任何 MCP 客户端 (Claude Desktop / Cursor /
本 GUI 等), 实现"对话时自动记忆": 会话开始召回、对话中自动沉淀洞察。

协议: MCP (Model Context Protocol) over stdio, 纯 JSON-RPC 2.0 实现,
不依赖 mcp SDK, 与 lclone 本身一样零第三方依赖。

用法:
  python3 lclone/mcp_server.py          # 以 stdio 方式等待 MCP 客户端
  BRAIN_DB_PATH=xx BRAIN_LLM=api ...    # 环境变量同 CLI

工具清单 (对齐 lclone CLI 语义):
  remember  主动记忆 (C, 直接生效)   capture  自动捕获 (B, 进草稿待确认)
  recall    回顾检索 (含链接跟随)    promote  记忆上升 -> 全局层
  demote    记忆下降 -> 指定项目     suggest  删除提示 (仅提示, 不删除)
  projects  列出项目                 review   确认草稿 (keep/delete)
  ask       带记忆的问答 (需真实 LLM 后端)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# 让 lclone 包可被导入 (无论从哪个 cwd 启动)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lclone import chat as chat_mod
from lclone import config
from lclone import db as db_mod
from lclone import memory as mem_mod
from lclone import projects as proj_mod

DEFAULT_DB = str(Path(__file__).resolve().parent.parent / "lclone.db")


def _db_path() -> str:
    return os.environ.get("BRAIN_DB_PATH") or config.get("BRAIN_DB_PATH") or DEFAULT_DB


# project 参数里可用来显式指定「全局层」的哨兵值
_GLOBAL_REFS = {"global", "个人区", "个人", "personal", "none"}


def _resolve_project(conn, ref):
    if not ref:
        return None
    if str(ref).strip().lower() in _GLOBAL_REFS:
        return None  # 显式选择全局层 (个人区)
    if str(ref).isdigit():
        row = proj_mod.get_project(conn, int(ref))
        if row:
            return row["id"]
    row = conn.execute("SELECT id FROM projects WHERE name=?", (str(ref),)).fetchone()
    if row:
        return row["id"]
    raise ValueError(f"项目不存在: {ref} (用 projects 工具查看)")


def _unattributed_msg() -> str:
    """未归属 (无 git) 时的 fail-closed 信号: 客户端据此向用户确认, 不静默落全局。"""
    return ("⚠️未归属|无 git 仓库, 未写入任何记忆。请向用户确认归属后重试:\n"
            "- 新建项目: 先记下项目名, 再传 project=<名>\n"
            "- 全局层: 传 project=global")


# ---------------------------------------------------------------- 工具定义
TOOLS = [
    {
        "name": "remember",
        "description": "主动记忆: 写入一条已确认的洞察/边界/事实。归属判定(代码强制): 优先按 cwd 的 git 仓库匹配已注册项目; 检测到仓库但未注册则自动注册(名=仓库basename); 无 git 仓库时返回「⚠️未归属」信号, 需先问用户(新建项目 or project=global)。level 恒为 insight, 默认进待确认(pending), 除非用户当场已确认该洞察(此时传 confirmed=true)。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "要记住的内容 (一句话)"},
                "project": {"type": "string",
                            "description": "项目名/id/global; 不传则按 cwd 的 git 仓库自动判定(匹配或自动注册), 无 git 返回未归属信号"},
                "cwd": {"type": "string",
                        "description": "工作目录 (git 归属判定用); 不传则用服务器当前目录"},
                "level": {"type": "string", "enum": ["insight"],
                          "description": "恒为 insight"},
                "confirmed": {"type": "boolean",
                              "description": "insight 是否已当场经用户确认 (true=直接生效, false/缺省=进待确认)"},
            },
            "required": ["content"],
        },
    },
    {
        "name": "capture",
        "description": "自动捕获: 把一段对话/工作内容提炼成洞察。归属判定(代码强制): 优先按 cwd 的 git 仓库匹配已注册项目; 检测到仓库但未注册则自动注册; 无 git 仓库时返回「⚠️未归属」信号, 需先问用户。洞察(insight)进待确认, 需立刻向用户逐条确认。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "本次对话/工作内容原文"},
                "project": {"type": "string",
                            "description": "项目名/id/global; 不传则按 cwd 的 git 仓库自动判定(匹配或自动注册), 无 git 返回未归属信号"},
                "cwd": {"type": "string",
                        "description": "工作目录 (git 归属判定用); 不传则用服务器当前目录"},
                "title": {"type": "string", "description": "会话标题 (可选)"},
                "session_key": {"type": "string", "description": "外部会话 id (记录聚合会话流水用)"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "recall",
        "description": "回顾检索: 用关键词召回相关记忆 (自动跟随 [[m:N]] 链接); 会话开始时用来注入上次的上下文",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索词/话题"},
                "project": {"type": "string", "description": "限定项目名或 id; 不传 = 全局层+所有活跃项目"},
                "k": {"type": "integer", "description": "返回条数, 默认 5"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "bootstrap",
        "description": "会话启动引导: 一次性返回 charter + 全局层记忆(无条件注入) + 按话题召回的相关记忆, 供每次会话开始时调用",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "本次会话话题/首条消息, 用于召回相关记忆 (可为空)"},
                "project": {"type": "string", "description": "限定项目名或 id; 不传 = 全局层"},
                "k": {"type": "integer", "description": "召回条数, 默认 5"},
            },
            "required": [],
        },
    },
    {
        "name": "promote",
        "description": "记忆上升: 把项目记忆升到全局层 (多个项目需要共读时); 全局层生命周期无限",
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "integer", "description": "记忆 id"}},
            "required": ["id"],
        },
    },
    {
        "name": "demote",
        "description": "记忆下降: 把记忆挂到指定项目 (不需要全局保持时); 也用于项目 A -> 项目 B 横搬",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "integer", "description": "记忆 id"},
                "project": {"type": "string", "description": "目标项目名或 id"},
            },
            "required": ["id", "project"],
        },
    },
    {
        "name": "suggest",
        "description": "删除提示: 算法扫描清理候选 (疑似重复/长期未确认/长期未召回/已移除项目记忆); 只提示, 删除由用户决定",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "projects",
        "description": "列出所有项目 (含记忆数/spec 数/charter)",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "review",
        "description": "确认草稿 (B 类确认关卡): keep 保留生效 / delete 删除",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "integer", "description": "记忆 id"},
                "action": {"type": "string", "enum": ["keep", "delete"], "description": "默认 keep"},
            },
            "required": ["id"],
        },
    },
    {
        "name": "ask",
        "description": "带记忆的问答: 基于召回的记忆回答 (需真实 LLM 后端; 离线 dummy 后端只回显)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "project": {"type": "string", "description": "限定项目名或 id"},
            },
            "required": ["question"],
        },
    },
    {
        "name": "organize",
        "description": "整理: LLM 把语义相近的记忆合并成一条综合描述 (不能跨项目/等级), 一键执行",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "evolution_add",
        "description": "沉淀一个进化资产 (可复用脚本/工具, 实践中生成, 改脚本时用 evolution_update 同步)。content=项目无关的脚本/工具内容(存记忆库); ref=项目内脚本路径(内容留仓库, 只留引用)。可传 insight 列表建立 insight→evolution 链接。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "脚本/工具名"},
                "kind": {"type": "string", "enum": ["script", "tool", "command", "other"],
                         "description": "默认 script"},
                "content": {"type": "string", "description": "项目无关的脚本/工具内容 (存记忆库本体)"},
                "ref": {"type": "string", "description": "项目内脚本路径 (内容留仓库, 只留引用)"},
                "reason": {"type": "string", "description": "为什么沉淀"},
                "insight": {"type": "array", "items": {"type": "integer"},
                            "description": "支撑此资产的 insight id 列表 (可多个)"},
                "project": {"type": "string", "description": "项目名/id/global; 不传按 cwd git 自动判定"},
                "cwd": {"type": "string", "description": "工作目录 (git 归属判定用)"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "evolution_list",
        "description": "列出进化资产 (可复用脚本/工具), 支持按项目/状态过滤",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "项目名/id/global"},
                "status": {"type": "string", "description": "active | stable"},
            },
        },
    },
    {
        "name": "evolution_update",
        "description": "同步一个进化资产到最新版本 (脚本被改时调用, 只更新给到的字段)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "integer", "description": "evolution id"},
                "content": {"type": "string", "description": "最新脚本/工具内容"},
                "ref": {"type": "string", "description": "最新路径"},
                "status": {"type": "string", "description": "active(在用) | stable(暂不再修改)"},
            },
            "required": ["id"],
        },
    },
    {
        "name": "conflicts",
        "description": "矛盾检测: 扫描疑似互相矛盾/规则改版的洞察对, 用 LLM 判定是否真矛盾; 只提示, 是否处理由用户定 (需真实 LLM 后端; dummy 后端不判矛盾)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "限定项目名或 id"},
            },
        },
    },
]


def call_tool(name: str, args: dict) -> str:
    conn = db_mod.init(_db_path())
    try:
        if name == "remember":
            pid = _resolve_project(conn, args.get("project"))
            where = ""
            if pid is None and not args.get("project"):
                status, pid = proj_mod.resolve_project(conn, cwd=args.get("cwd"))
                if status == "no_git":
                    return _unattributed_msg()
                where = f"项目 #{pid} (git 自动{'归属' if status == 'matched' else '注册'})"
            elif pid is None:
                where = "全局层(个人区)"
            else:
                where = f"项目 #{pid}"
            confirmed = bool(args.get("confirmed", False))
            mid = mem_mod.remember(conn, args["content"],
                                   level=args.get("level", "insight"),
                                   project_id=pid,
                                   confirmed=confirmed)
            tail = ""
            if args.get("level", "insight") == "insight" and not confirmed:
                tail = " (洞察进待确认: 请向用户逐条确认保留/删除)"
            return f"已主动记忆 #{mid} [{where}]{tail}"
        if name == "capture":
            pid = _resolve_project(conn, args.get("project"))
            where = ""
            if pid is None and not args.get("project"):
                status, pid = proj_mod.resolve_project(conn, cwd=args.get("cwd"))
                if status == "no_git":
                    return _unattributed_msg()
                where = f"项目 #{pid} (git 自动{'归属' if status == 'matched' else '注册'})"
            elif pid is None:
                where = "全局层(个人区)"
            else:
                where = f"项目 #{pid}"
            ids = mem_mod.capture(conn, args["text"], project_id=pid,
                                  title=args.get("title", ""),
                                  session_key=args.get("session_key", ""))
            if not ids:
                return "未提炼出可记忆的内容 (内容里可能没有洞察或值得记的事实)"
            rows = conn.execute(
                "SELECT id, level, content FROM memories WHERE id IN (%s)"
                % ",".join("?" * len(ids)), ids
            ).fetchall()
            decisions = [r for r in rows if r["level"] == "insight"]
            lines = [f"已捕获 {len(ids)} 条记忆 [{where}]:"]
            if decisions:
                lines.append("洞察(待确认): " + ", ".join(
                    f"#{r['id']} {r['content'][:40]}" for r in decisions))
                lines.append("⚠️ 请立刻向用户逐条确认这些洞察保留/删除 (ask_user_question)")
            return "\n".join(lines)
        if name == "recall":
            pid = _resolve_project(conn, args.get("project"))
            items = mem_mod.recall(conn, args["query"], k=int(args.get("k", 5)),
                                   project_id=pid)
            if not items:
                return "(没有相关记忆)"
            return mem_mod._format_grouped(items, show_id=True)
        if name == "bootstrap":
            pid = _resolve_project(conn, args.get("project"))
            out = mem_mod.bootstrap(conn, query=args.get("query", ""),
                                    project_id=pid, k=int(args.get("k", 5)))
            return out or "(暂无记忆)"
        if name == "organize":
            res = mem_mod.organize(conn)
            return (f"整理完成: 合并 {res['merged']} 组, "
                    f"删除 {res['removed']} 条冗余记忆")
        if name == "evolution_add":
            pid = _resolve_project(conn, args.get("project"))
            if pid is None and not args.get("project"):
                status, pid = proj_mod.resolve_project(conn, cwd=args.get("cwd"))
                if status == "no_git":
                    return _unattributed_msg()
            if not (args.get("content") or args.get("ref")):
                return "错误: evolution 需要有 --content (项目无关内容) 或 --ref (项目内路径)"
            eid = mem_mod.create_evolution(
                conn, name=args.get("name", ""), kind=args.get("kind", "script"),
                content=args.get("content", ""), ref=args.get("ref", ""),
                reason=args.get("reason", ""), project_id=pid)
            for iid in (args.get("insight") or []):
                mem_mod.link_insight_to_evolution(conn, int(iid), eid)
            return f"已沉淀进化资产 #{eid} [{'全局层' if pid is None else f'项目 #{pid}'}] {args.get('name')}"
        if name == "evolution_list":
            pid = _resolve_project(conn, args.get("project"))
            items = mem_mod.list_evolutions(conn, project_id=pid, status=args.get("status"))
            if not items:
                return "(暂无进化资产)"
            return "\n".join(
                f"#{e['id']} [{e.get('project_name') or '全局层'}] [{e['kind']}{('/'+e['status']) if e['status']!='active' else ''}] "
                f"{e['name']}  {((e['content'] or e['ref']) or '')[:60]}"
                for e in items
            )
        if name == "evolution_update":
            eid = int(args["id"])
            mem_mod.update_evolution(
                conn, eid, content=args.get("content"), ref=args.get("ref"),
                status=args.get("status"))
            return f"进化资产 #{eid} 已同步"
        if name == "conflicts":
            pid = _resolve_project(conn, args.get("project"))
            items = mem_mod.find_conflicts(conn, project_id=pid)
            if not items:
                return "(没有发现疑似矛盾的洞察; 矛盾检测需真实 LLM 后端, dummy 后端不判矛盾)"
            return "\n\n".join(
                f"#{i['a']} ↔ #{i['b']} [{i['project']}]\n"
                f"  A: {i['content_a'][:80]}\n"
                f"  B: {i['content_b'][:80]}\n"
                f"  矛盾: {i['reason']}"
                for i in items
            )
        if name == "promote":
            mem_mod.promote(conn, int(args["id"]))
            return f"记忆 #{args['id']} 已上升至全局层 (生命周期无限, 多项目共读)"
        if name == "demote":
            pid = _resolve_project(conn, args.get("project"))
            mem_mod.demote(conn, int(args["id"]), pid)
            return f"记忆 #{args['id']} 已下降至项目 #{pid} (生命周期与之绑定)"
        if name == "suggest":
            items = mem_mod.suggest(conn)
            if not items:
                return "(没有建议清理的记忆; 删除始终由用户决定)"
            return "\n\n".join(
                f"#{i['id']} [{i['project']}] {i['created_at'][:10]}\n"
                f"  {i['content'][:80]}\n  原因: {i['reason']}"
                for i in items
            )
        if name == "projects":
            rows = proj_mod.list_projects(conn)
            if not rows:
                return "(暂无项目)"
            return "\n".join(
                f"#{r['id']} {r['name']}  charter={r['charter'] or '-'}"
                f"  记忆={r['mem_count']}"
                + (f" 待确认={r['pending_count']}" if r["pending_count"] else "")
                + f" spec索引={r['spec_count']} path={r['path']}"
                for r in rows
            )
        if name == "review":
            mem_mod.review(conn, int(args["id"]), args.get("action", "keep"))
            return f"记忆 #{args['id']} -> {args.get('action', 'keep')}"
        if name == "ask":
            pid = _resolve_project(conn, args.get("project"))
            res = chat_mod.ask(conn, args["question"], project_id=pid)
            return res["answer"]
        raise ValueError(f"未知工具: {name}")
    except Exception as e:  # 错误以文本返回, 便于用户看到原因
        return f"错误: {e}"
    finally:
        conn.close()


# ---------------------------------------------------------------- JSON-RPC 分发
def handle_message(msg: dict):
    """处理单条 JSON-RPC 消息, 返回响应 dict (通知类/无 id 返回 None)。

    stdio 循环与 HTTP 传输共用此函数, 不绑 stdin/stdout。
    """
    rid = msg.get("id")
    method = msg.get("method")
    params = msg.get("params") or {}
    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": rid,
            "result": {
                "protocolVersion": params.get("protocolVersion", "2024-11-05"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "lclone", "version": "0.1.0"},
            },
        }
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments") or {}
        text = call_tool(name, args)
        return {
            "jsonrpc": "2.0", "id": rid,
            "result": {"content": [{"type": "text", "text": text}],
                       "isError": text.startswith("错误:")},
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": rid, "result": {}}
    return {
        "jsonrpc": "2.0", "id": rid,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "id" not in msg:
            continue  # 通知类消息, 忽略
        resp = handle_message(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
