"""LLM 与 embedding 后端。

两个后端:
  api   -> OpenAI 兼容接口 (OpenAI / DeepSeek / 硅基流动 / 智谱 等, 通过 BRAIN_BASE_URL 切换)
  dummy -> 确定性哈希 embedding + 回显 chat, 用于离线自测

设计原则: 大脑永远只依赖抽象接口 (embed_texts / chat), 不绑定任何厂商。
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Iterable, List, Optional

from . import config

DIM = 384  # dummy 后端维度


def backend() -> str:
    return (config.get("BRAIN_LLM") or "api").strip().lower()


# ---------------------------------------------------------------- dummy 后端
def _dummy_embed(text: str, dim: int = DIM) -> List[float]:
    vec = [0.0] * dim
    for token in text.lower().split():
        h = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        idx = int.from_bytes(h[:4], "little") % dim
        sign = 1.0 if h[4] % 2 == 0 else -1.0
        vec[idx] += sign
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _dummy_chat(messages: List[dict]) -> str:
    last = messages[-1]["content"] if messages else ""
    return f"[dummy] 回显: {last[:500]}"


# ---------------------------------------------------------------- api 后端
_client = None


def _get_client():
    global _client
    if _client is None:
        try:
            from openai import OpenAI
        except ImportError as e:
            raise RuntimeError(
                "使用 api 后端需要安装 openai 库: pip install openai\n"
                "(离线自测请设 BRAIN_LLM=dummy)"
            ) from e
        key = config.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("未设置 OPENAI_API_KEY (或用 BRAIN_LLM=dummy 离线自测)")
        _client = OpenAI(api_key=key, base_url=config.get("BRAIN_BASE_URL") or None)
    return _client


# ---------------------------------------------------------------- 公共接口
def embed_texts(texts: Iterable[str]) -> List[List[float]]:
    texts = list(texts)
    if backend() == "dummy":
        return [_dummy_embed(t) for t in texts]
    # 部分服务商 (如 DeepSeek) 不提供 embedding 接口:
    # BRAIN_EMBED_BACKEND=local 时聊天用真实模型, 向量用本地确定性哈希 (零依赖)
    if (config.get("BRAIN_EMBED_BACKEND") or "api").strip().lower() == "local":
        return [_dummy_embed(t) for t in texts]
    client = _get_client()
    resp = client.embeddings.create(
        model=config.get("BRAIN_EMBED_MODEL"), input=texts
    )
    data = sorted(resp.data, key=lambda d: d.index)
    return [d.embedding for d in data]


def embed_one(text: str) -> List[float]:
    return embed_texts([text])[0]


def chat(messages: List[dict], temperature: float | None = None) -> str:
    if backend() == "dummy":
        return _dummy_chat(messages)
    client = _get_client()
    resp = client.chat.completions.create(
        model=config.get("BRAIN_CHAT_MODEL"),
        messages=messages,
        temperature=config.get_float("BRAIN_TEMPERATURE", 0.3)
        if temperature is None else temperature,
    )
    return resp.choices[0].message.content or ""


def extract_memories(text: str,
                     existing_modules: Optional[List[str]] = None) -> List[dict]:
    """从一段工作内容中提炼记忆条目 (L1 层, 自动捕获用), 分类为 decision / note,
    并给出模块 (关注点)。

    返回 [{"level": "decision"|"note", "module": str, "content": str, "confidence": float}]。
    module 由 LLM 从 existing_modules 里复用, 或给出一个粗粒度新关注点;
    词表强制 (归一化/去重/防泛名) 由 memory._resolve_module 在代码侧完成。

    decision = 选了什么方案 / 定了什么规则 / 约定什么边界 (只提炼"选择/约定", 不提炼"做了什么");
    note = 值得记的过程性事实、观察、TODO、灵感。

    自筛: 提示词要求 LLM 先判断内容归「项目 spec/代码」还是「决策/事实」——
    代码层级的改变/特定逻辑行为变化/需求场景边界变化/重构/修 bug/接口变化 一律不输出
    (归 sp-spec 和 git), 只提炼 decision(选型/约定/边界) 与 note(值得记的过程事实),
    宁可少提甚至不提, 减少对用户的打扰。

    dummy 后端: 整段视为一条 note, module 为空, 保证离线流程可跑通。
    """
    if backend() == "dummy":
        t = text.strip()
        return [{"level": "note", "module": "", "content": t[:300],
                 "confidence": 1.0}] if t else []
    mod_hint = (", ".join(existing_modules) if existing_modules
                else "(暂无, 请给一个粗粒度关注点)")
    prompt = (
        "你是一个记忆筛选器。核心判断: 这段内容是在「定下选择/规则」, 还是在「描述做了什么改变」?\n"
        "只提炼「定下选择/规则」的内容:\n"
        "- decision: 决定/采用/选择/约定/定为 X (如「决定用网格布局」「约定: 无 git 时问用户」)\n"
        "- note: 值得跨会话保留的过程性事实/观察\n"
        "凡是「描述做了什么改变」的, 一律不要提炼——包括: 代码层级的改变、特定逻辑/行为的变化\n"
        "(如「把 X 从 A 改成 B」)、重构/实现/修复/新增端点/接口变化。\n"
        "这些归 git 和 sp-spec, 即使某句话里隐含了某个参数值(如「每行改成 4 个」),\n"
        "只要它是在描述「改变了什么」而非「定下了什么规则」, 就不要提炼。\n"
        "过程性琐碎/一次性/显而易见/临时性也不要输出。宁可少提甚至不提; 没有值得记的就输出空。\n"
        "每条一行, 格式: 类型[模块]: 内容\n"
        f"- 模块: 英文短名, 优先复用已有模块 ({mod_hint}); 新关注点才起粗粒度名。\n"
        "示例: decision[web]: Web 记忆图用网格布局分页\n"
        "记录:\n" + text[:12000]
    )
    raw = chat([{"role": "user", "content": prompt}])
    out = []
    for line in raw.splitlines():
        line = line.strip().strip("-•*").strip()
        if not line or len(line) <= 3:
            continue
        level = "note"
        module = ""
        body = line
        m = re.match(r"^(decision|note)\s*\[([^\]]*)\]\s*[:：]\s*(.+)$",
                     line, re.IGNORECASE)
        if m:
            level = m.group(1).lower()
            module = (m.group(2) or "").strip().lower()
            body = m.group(3).strip()
        else:
            m2 = re.match(r"^(decision|note)\s*[:：]\s*(.+)$", line, re.IGNORECASE)
            if m2:
                level = m2.group(1).lower()
                body = m2.group(2).strip()
            else:
                m3 = re.match(r"^(decision|note)\b\s*(.*)$", line, re.IGNORECASE)
                if m3:
                    level = m3.group(1).lower()
                    body = m3.group(2).strip(" :：").strip()
        if body:
            out.append({"level": level, "module": module, "content": body,
                        "confidence": 0.9})
    return out


def extract_decisions(text: str) -> List[str]:
    """兼容别名: 只返回 decision 档的内容 (旧调用点)。"""
    return [it["content"] for it in extract_memories(text) if it["level"] == "decision"]


def summarize(text: str, max_chars: int = 400) -> str:
    """把长文本压缩成有界摘要 (用于 note 超长时的滚动压缩)。

    保留关键事实/决策/结论, 去掉重复与啰嗦。
    dummy 后端: 直接截断。
    """
    t = (text or "").strip()
    if not t:
        return ""
    if len(t) <= max_chars:
        return t
    if backend() == "dummy":
        return t[:max_chars]
    prompt = (
        "下面是一段工作记录, 请压缩成一段简洁摘要, 保留关键事实、决策、结论,"
        "去掉重复和啰嗦。直接输出摘要, 不要客套。\n\n"
        "记录:\n" + t[:16000]
    )
    raw = chat([{"role": "user", "content": prompt}], temperature=0.2)
    out = (raw or "").strip()
    return out[:max_chars] if out else t[:max_chars]


def check_boundaries(project_ctx: str, proposal: str) -> str:
    """规范环: 让 LLM 对照项目上下文逐条检查提议的边界条件。"""
    if backend() == "dummy":
        return (
            "[dummy] 监督报告\n"
            "项目上下文:\n" + project_ctx[:500] + "\n"
            "新提议: " + proposal[:200] + "\n"
            "检查结果: 通过(占位)"
        )
    prompt = (
        "你是项目边界监督器。下面给出项目的方向、决策和规格内容, 以及一个新的提议。\n"
        "请逐条对照规格中的边界条件/约束, 输出检查报告, 格式:\n"
        "1. ✅通过 | ⚠️警告 | ❌违反 —— 边界条件原文 (说明)\n"
        "2. ...\n"
        "最后给一行结论和建议。只对照事实, 不要自行添加未给出的约束。\n\n"
        "=== 项目上下文 ===\n" + project_ctx[:14000] + "\n\n"
        "=== 新提议 ===\n" + proposal[:4000]
    )
    return chat([{"role": "user", "content": prompt}], temperature=0.2)
