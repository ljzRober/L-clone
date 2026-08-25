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


def extract_memories(text: str) -> List[dict]:
    """从一段工作内容中提炼记忆条目 (L1 层, 自动捕获用), 分类为 decision / note。

    返回 [{"level": "decision"|"note", "content": str, "confidence": float}]。
    decision = 确定的决策/选型/边界/时间点; note = 值得记的过程性事实/观察/TODO/灵感。

    dummy 后端: 整段视为一条 note, 保证离线流程可跑通。
    """
    if backend() == "dummy":
        t = text.strip()
        return [{"level": "note", "content": t[:300], "confidence": 1.0}] if t else []
    prompt = (
        "下面是一段工作/讨论记录。请提炼其中值得长期记住的内容, 每条一行, 用前缀标注类型:\n"
        "- decision: 确定了什么 (确定的决策/选型/边界/时间点)\n"
        "- note: 值得记的过程性事实、观察、TODO、灵感\n"
        "格式: decision: 内容  或  note: 内容。没有值得记的就输出空。不要总结, 不要客套。\n\n"
        "记录:\n" + text[:12000]
    )
    raw = chat([{"role": "user", "content": prompt}])
    out = []
    for line in raw.splitlines():
        line = line.strip().strip("-•*").strip()
        if not line or len(line) <= 3:
            continue
        level = "note"
        body = line
        m = re.match(r"^(decision|note)\s*[:：]\s*(.+)$", line, re.IGNORECASE)
        if m:
            level = m.group(1).lower()
            body = m.group(2).strip()
        else:
            m2 = re.match(r"^(decision|note)\b\s*(.*)$", line, re.IGNORECASE)
            if m2:
                level = m2.group(1).lower()
                body = m2.group(2).strip(" :：").strip()
        if body:
            out.append({"level": level, "content": body, "confidence": 0.9})
    return out


def extract_decisions(text: str) -> List[str]:
    """兼容别名: 只返回 decision 档的内容 (旧调用点)。"""
    return [it["content"] for it in extract_memories(text) if it["level"] == "decision"]


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
