"""LLM 与 embedding 后端。

两个后端:
  api   -> OpenAI 兼容接口 (OpenAI / DeepSeek / 硅基流动 / 智谱 等, 通过 BRAIN_BASE_URL 切换)
  dummy -> 确定性哈希 embedding + 回显 chat, 用于离线自测

设计原则: 大脑永远只依赖抽象接口 (embed_texts / chat), 不绑定任何厂商。
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Iterable, List

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


def chat_json(prompt: str, temperature: float = 0.2):
    """让 LLM 返回 JSON (数组), 容错解析。失败返回 None。"""
    raw = chat([{"role": "user", "content": prompt}], temperature=temperature).strip()
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
        return None


def extract_memories(text: str) -> List[dict]:
    """从一段工作内容中提炼记忆条目 (L1 层, 自动捕获用), 只产出 insight。

    返回 [{"level": "insight", "content": str, "confidence": float}]。

    insight = 一条原子化、自包含、内容丰富的知识/见解/教训——一个决定 / 一条经验 /
    一个观察 / 一条复盘, 每条自带精简背景/推理/后果 (约 2-4 句), 不是逐字记录, 也不是一行。

    自筛: 代码层级的改变/特定逻辑行为变化/需求场景边界变化/重构/修 bug/接口变化 一律不输出
    (归 sp-spec 和 git); 能改写成带 WHEN/THEN requirement 的「系统必须满足的契约」也归 spec。
    只提炼无法写成契约的「为什么这么选 / 观察到什么 / 个人经验与推理」。

    归属: 若某 insight 明确对应仓库内某具体 spec/文件, 项目级记忆可标注 [[spec:id]]/[[src:path]];
    全局级记忆无仓库上下文, 一律不标注此类链接 (只有 [[m:N]] 跨记忆链接)。

    dummy 后端: 整段视为一条 insight, 保证离线流程可跑通。
    """
    if backend() == "dummy":
        t = text.strip()
        return [{"level": "insight", "content": t[:300],
                 "confidence": 1.0}] if t else []
    prompt = (
        "你是一个记忆提炼器。把输入里的「洞察/知识」提炼成一条条 insight 卡片, 而不是流水账。\n"
        "insight = 一条原子化、自包含的知识/见解/教训: 每一个条目是一件事\n"
        "(一个决定 / 一条经验 / 一个观察 / 一条复盘), 每条约 2-4 句, 自带「背景/是什么/影响」\n"
        "(为什么这么定、影响是什么、以后注意什么), 让人能独立读懂。\n"
        "不要逐字转录对话/代码 (那是 git/spec 的事), 也不要压成一行的干巴巴结论。\n"
        "只提炼真正值得跨会话记住的; 宁可少提甚至不提; 没有就输出空。\n"
        "输出格式: 每条一行 `insight: <内容>`。\n"
        "示例: insight: 无 git 仓库时不静默落全局, 要先问用户归属, 因为这会影响后续召回范围\n"
        "边界: 描述「做了什么」(代码改动/接口变化/重构/修 bug/新增端点) 一律不提炼 (归 git/spec);\n"
        "能写成带 WHEN/THEN 的 requirement 的契约也不提炼 (那是 spec)。\n"
        "若某条 insight 明确对应仓库内某具体 spec/文件, 可在末尾标 [[spec:名字]] 或 [[src:路径]];\n"
        "全局/跨项目无关仓库的内容不要标这类链接。\n"
        "输入以「用户：」/「助手：」标注; 仅用户提出、助手确认/落地/持续推进的选择才提炼为 insight。\n"
        "记录:\n" + text[:12000]
    )
    raw = chat([{"role": "user", "content": prompt}])
    out = []
    for line in raw.splitlines():
        line = line.strip().strip("-•*").strip()
        if not line or len(line) <= 3:
            continue
        body = line
        m = re.match(r"^(insight|note)\s*[:：]\s*(.+)$",
                     line, re.IGNORECASE)
        if m:
            body = m.group(2).strip()
        else:
            m2 = re.match(r"^(insight|note)\b\s*(.*)$", line, re.IGNORECASE)
            if m2:
                body = m2.group(2).strip(" :：").strip()
        if body:
            # 过滤 LLM 的「无内容」元响应 (如「无值得提炼…」「没有值得记…」)
            if any(mk in body for mk in
                   ("无值得提炼", "没有值得记", "无值得记", "无可提炼", "无需提炼",
                    "没有可提炼", "无内容", "无相关", "暂无")):
                continue
            out.append({"level": "insight", "content": body, "confidence": 0.9})
    return out


def extract_insights(text: str) -> List[str]:
    """兼容别名: 只返回 insight 档的内容 (旧调用点)。"""
    return [it["content"] for it in extract_memories(text) if it["level"] == "insight"]


def summarize(text: str, max_chars: int = 400) -> str:
    """把长文本压缩成有界摘要 (用于 note 超长时的滚动压缩)。

    保留关键事实/洞察/结论, 去掉重复与啰嗦。
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
        "下面是一段工作记录, 请压缩成一段简洁摘要, 保留关键事实、洞察、结论,"
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
        "你是项目边界监督器。下面给出项目的方向、洞察和规格内容, 以及一个新的提议。\n"
        "请逐条对照规格中的边界条件/约束, 输出检查报告, 格式:\n"
        "1. ✅通过 | ⚠️警告 | ❌违反 —— 边界条件原文 (说明)\n"
        "2. ...\n"
        "最后给一行结论和建议。只对照事实, 不要自行添加未给出的约束。\n\n"
        "=== 项目上下文 ===\n" + project_ctx[:14000] + "\n\n"
        "=== 新提议 ===\n" + proposal[:4000]
    )
    return chat([{"role": "user", "content": prompt}], temperature=0.2)
