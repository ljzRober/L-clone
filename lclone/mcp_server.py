#!/usr/bin/env python3
"""L-clone MCP 服务器 (零第三方依赖)。

把外置大脑的记忆能力暴露给任何 MCP 客户端 (Claude Desktop / Cursor /
本 GUI 等), 实现"对话时自动记忆": 会话开始召回、对话中自动沉淀决策。

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


def _resolve_project(conn, ref):
    if not ref:
        return None
    if str(ref).isdigit():
        row = proj_mod.get_project(conn, int(ref))
        if row:
            return row["id"]
    row = conn.execute("SELECT id FROM projects WHERE name=?", (str(ref),)).fetchone()
    if row:
        return row["id"]
    raise ValueError(f"项目不存在: {ref} (用 projects 工具查看)")


# ---------------------------------------------------------------- 工具定义
TOOLS = [
    {
        "name": "remember",
        "description": "主动记忆 (C 类, 直接生效): 用户明确确认的决策/边界/重要信息, 写入记忆库。归属判定: 优先按 git 仓库匹配已注册项目 (传 cwd 或当前目录), 匹配不到则落全局层; 是否该升全局由你判断, 拿不准问用户",
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "要记住的内容 (一句话)"},
                "project": {"type": "string",
                            "description": "项目名或 id; 不传则按 cwd 的 git 仓库自动判定, 判定不到 = 全局层(个人区)"},
                "cwd": {"type": "string",
                        "description": "工作目录 (git 归属判定用); 不传则用服务器当前目录"},
                "level": {"type": "string", "enum": ["decision", "milestone", "note"],
                          "description": "默认 decision"},
            },
            "required": ["content"],
        },
    },
    {
        "name": "capture",
        "description": "自动捕获 (B 类, 进草稿待确认): 把一段对话/工作内容提炼成决策草稿, 用户 review 后生效。归属判定: 优先按 git 仓库匹配已注册项目 (传 cwd 或当前目录), 匹配不到则落全局层; 是否该升全局由你判断, 拿不准问用户",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "本次对话/工作内容原文"},
                "project": {"type": "string",
                            "description": "项目名或 id; 不传则按 cwd 的 git 仓库自动判定, 判定不到 = 全局层"},
                "cwd": {"type": "string",
                        "description": "工作目录 (git 归属判定用); 不传则用服务器当前目录"},
                "title": {"type": "string", "description": "会话标题 (可选)"},
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
]


def call_tool(name: str, args: dict) -> str:
    conn = db_mod.init(_db_path())
    try:
        if name == "remember":
            pid = _resolve_project(conn, args.get("project"))
            auto = False
            if pid is None and not args.get("project"):
                pid = proj_mod.detect_project_by_git(conn, cwd=args.get("cwd"))
                auto = pid is not None
            mid = mem_mod.remember(conn, args["content"],
                                   level=args.get("level", "decision"),
                                   project_id=pid)
            if pid is None:
                where = "全局层(个人区)"
            elif auto:
                where = f"项目 #{pid} (git 自动归属)"
            else:
                where = f"项目 #{pid}"
            return f"已主动记忆 #{mid} [{where}] (C 类, 直接生效)"
        if name == "capture":
            pid = _resolve_project(conn, args.get("project"))
            auto = False
            if pid is None and not args.get("project"):
                pid = proj_mod.detect_project_by_git(conn, cwd=args.get("cwd"))
                auto = pid is not None
            ids = mem_mod.capture(conn, args["text"], project_id=pid,
                                  title=args.get("title", ""))
            if not ids:
                return "未提炼出确定的决策 (内容里可能没有结论)"
            if pid is None:
                where = "全局层(个人区)"
            elif auto:
                where = f"项目 #{pid} (git 自动归属)"
            else:
                where = f"项目 #{pid}"
            return (f"已生成 {len(ids)} 条决策草稿待确认 [{where}]: {ids}\n"
                    f"请提醒用户: lclone review 确认 (或告诉我 review keep/delete)")
        if name == "recall":
            pid = _resolve_project(conn, args.get("project"))
            items = mem_mod.recall(conn, args["query"], k=int(args.get("k", 5)),
                                   project_id=pid)
            if not items:
                return "(没有相关记忆)"
            lines = []
            for i in items:
                tag = " 🔗链接" if i.get("via_link") else ""
                lines.append(
                    f"#{i['id']} [{i['project']}/{i['level']}]"
                    f" ({i['created_at']}){tag}\n  {i['content']}"
                )
            return "\n\n".join(lines)
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
                f"  记忆={r['mem_count']} spec索引={r['spec_count']}"
                f"  path={r['path']}"
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


# ---------------------------------------------------------------- JSON-RPC 循环
def _send(rid, result=None, error=None) -> None:
    msg = {"jsonrpc": "2.0", "id": rid}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


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
        rid = msg["id"]
        method = msg.get("method")
        params = msg.get("params") or {}
        if method == "initialize":
            _send(rid, {
                "protocolVersion": params.get("protocolVersion", "2024-11-05"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "lclone", "version": "0.1.0"},
            })
        elif method == "tools/list":
            _send(rid, {"tools": TOOLS})
        elif method == "tools/call":
            name = params.get("name", "")
            args = params.get("arguments") or {}
            text = call_tool(name, args)
            _send(rid, {
                "content": [{"type": "text", "text": text}],
                "isError": text.startswith("错误:"),
            })
        elif method == "ping":
            _send(rid, {})
        else:
            _send(rid, error={"code": -32601,
                              "message": f"Method not found: {method}"})


if __name__ == "__main__":
    main()
