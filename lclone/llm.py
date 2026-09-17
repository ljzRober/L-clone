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


def judge_insight(text: str) -> bool:
    """闸门 uncertain 档的一次极便宜判定: 这段内容值得跨会话记住吗?

    只要求回 1/0, 比整段提炼便宜得多 (闸门已用脚本挡掉绝大多数轮次, 这里是"判不准
    才问 LLM"的兜底)。dummy 后端离线恒 True, 保证离线流程可跑通; LLM 不可用或
    解析失败一律 False —— 宁可不记, 也不打扰用户。
    """
    if backend() == "dummy":
        return True
    prompt = (
        "判断下面这段工作记录里有没有值得跨会话长期记住的「决策/约定/规则/教训」。\n"
        "只回答 1 (有) 或 0 (没有), 不要输出任何其它字符。\n"
        "注意: 描述「做了什么」(代码改动/修复/重构/新增/迁移) 一律算 0。\n\n"
        "记录:\n" + (text or "")[:6000]
    )
    try:
        raw = chat([{"role": "user", "content": prompt}], temperature=0.0)
    except Exception:
        return False
    # 只认开头的 1 (允许 "1." / "1 有" 之类), 不把 "10" / "12" 当肯定
    return re.match(r"^\s*1(?!\d)", raw or "") is not None


# ---------------------------------------------------------------- 提炼结果的元响应/形状校验
# 提炼提示词明确要求「宁可少提甚至不提; 没有就输出空」, 所以模型回一个「空」字是**正常且
# 预期**的结果, 必须在落库前认出来。事故 #761: 模型回的是「空 + 一段解释」(把整段输入
# 当成元报告复述), 而旧词表只认固定短语、下游 _filter_item 只拦 <4 字, 于是这段没有任何
# 知识内容的元响应被存成了一条待确认洞察。
EMPTY_RESPONSES = (
    "空", "无", "没有", "无内容", "暂无", "n/a", "na", "none", "null", "nil", "nothing",
)
# 正文里出现这些短语同样说明"没提炼出东西", 无论它落在哪个位置
NO_CONTENT_MARKERS = (
    "无值得提炼", "没有值得记", "无值得记", "无可提炼", "无需提炼",
    "没有可提炼", "无内容", "无相关", "暂无", "未提炼", "没有值得记忆", "无需记忆",
)
# 卡片形状: 提示词强制三段分行 (要点/背景·为什么/影响·以后注意), 一段标题都没有
# 就不是卡 —— 多半是模型的元报告或对输入的回声, 不能当知识收下
CARD_SECTIONS = ("要点", "背景", "影响")
# 自包含性 (Letta: "Store self-contained facts or summaries, not conversational fragments"):
# 只有一句"要点"的卡离开原始对话就读不懂, 必须同时还带背景或影响中的至少一段。
CARD_REQUIRED = "要点"
CARD_SUPPORTING = ("背景", "影响")


def _meta_key(text: str) -> str:
    """归一化比对键: 去空白/标点/大小写 (「空。」与「空」等价)。"""
    return re.sub(r"[\s\W_]+", "", text or "").lower()


def _first_line(text: str) -> str:
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


def is_empty_response(text: str) -> bool:
    """整段是否是「没有可提炼内容」的元响应。

    只看**首个非空行**: 这样既拦得住「空 + 一段解释」这种真实形态, 又不会误伤正文里
    出现「空」字的正常卡片 (卡片首行按格式是「要点：…」)。
    """
    key = _meta_key(_first_line(text))
    return key == "" or key in {_meta_key(x) for x in EMPTY_RESPONSES}


def extract_memories(text: str) -> List[dict]:
    """从一段工作内容中提炼记忆条目 (L1 层, 自动捕获用), 只产出 insight。
    返回 [{"level": "insight", "content": str, "confidence": float}]。

    insight = 一条原子化、自包含、内容丰富的知识/见解/教训——一个决定 / 一条经验 /
    一个观察 / 一条复盘, 每条自带精简背景/推理/后果 (约 2-4 句), 不是逐字记录, 也不是一行。

    自筛: 代码层级的改变/特定逻辑行为变化/需求场景边界变化/重构/修 bug/接口变化 一律不输出
    (归 sp-spec 和 git); 能改写成带 WHEN/THEN requirement 的「系统必须满足的契约」也归 spec。
    只提炼无法写成契约的「为什么这么选 / 观察到什么 / 个人经验与推理」。

    引用: 若某 insight 明确对应仓库内某具体 spec/文件/进化资产, **就地**在正文里写
    `[[spec:id]]`/`[[src:path]]`/`[[evo:名字]]`（link, not copy）; 全局级记忆无仓库上下文时
    不标此类链接（只有 `[[m:N]]` 跨记忆链接）。

    dummy 后端: 整段视为一条 insight, 保证离线流程可跑通。
    """
    if backend() == "dummy":
        t = text.strip()
        return [{"level": "insight", "content": t[:300],
                 "confidence": 1.0}] if t else []
    prompt = (
        "你是一个记忆提炼器。把输入里的「洞察/知识」提炼成一条条 insight 卡片, 而不是流水账。\n"
        "insight = 一条原子化、自包含、内容丰富的知识/见解/教训: 每一个条目是一件事\n"
        "(一个决定 / 一条经验 / 一个观察 / 一条复盘)。\n"
        "每条 insight SHALL 按「三段分行」写, 自带背景与后果, 让人独立读懂 (共 2-4 句):\n"
        "  要点：<一句话结论>\n"
        "  背景/为什么：<为什么这么定/背景/推理>\n"
        "  影响/以后注意：<带来什么/以后注意什么>\n"
        "若这条洞察指向某个进化资产 / 契约 / 源文件, 就在**提到它的那句话里**写 [[evo:名字]] / "
        "[[spec:标识]] / [[src:路径]]; 不要单独起一行做引用列表。\n"
        "多条之间用一行 `====` 分隔。只输出这些块, 不要其它解释。\n"
        "不要逐字转录对话/代码 (那是 git/spec 的事), 也不要压成一行的干巴巴结论。\n"
        "准入只收四类: 决策 / 约定 / 规则 / 教训。一般事实、过程描述、进度汇报一律不提炼。\n"
        "以下同样一律不提炼:\n"
        "  - 助手自己排查出来的环境近况: 工具/skill 装在哪、目录有没有 .git、容器里跑的是代码\n"
        "    还是卷、某个开关的当前值 —— 一次 ls / git status / docker inspect 就能重新得到;\n"
        "  - 通用设计/编程常识 (跟本项目具体决策无关的普适做法);\n"
        "  - 用户轮里找不到出处的助手单方面结论: 卡片主张必须在用户轮里有对应说法。\n"
        "默认一条都不提炼; 最多 1 条; 没有就只输出「空」一个字 (不要再写任何解释)。\n"
        "边界: 描述「做了什么」(代码改动/接口变化/重构/修 bug/新增端点) 一律不提炼 (归 git/spec);\n"
        "能写成带 WHEN/THEN 的 requirement 的契约也不提炼 (那是 spec)。\n"
        "分类判据 (按「它是干什么的」): 说明性内容——规范/准则/理由/观察/经验/模板/示例——一律是 insight,\n"
        "**不要建议放进 evolution**; evolution 只承载数据与可执行文件 (脚本/工具/配置/密钥表),\n"
        "它们独立存在说明不了任何内容。规范太长时写成一条内容完整的长卡 (同类规范合并为一条, 不要拆成多条卡), 也不要靠“外置正文”省注入体积。\n"
        "输入以「用户：」/「助手：」标注; 仅用户提出、助手确认/落地/持续推进的选择才提炼为 insight。\n"
        "记录:\n" + text[:12000]
    )
    raw = chat([{"role": "user", "content": prompt}])
    out = []
    # 按 `====` 分隔成块, 每块 = 一条 insight (内容为多行三段卡)
    blocks = re.split(r"^\s*={2,}\s*$", (raw or "").strip(), flags=re.M)
    for block in blocks:
        block = block.strip().strip("-•*").strip()
        if not block:
            continue
        body = block
        m = re.match(r"^(insight|note)\s*[:：]?\s*(.*)$", block, re.IGNORECASE | re.S)
        if m:
            body = m.group(2).strip()
        if not body or len(body) < 4:
            continue
        # 过滤「无内容」元响应: 整块就是空哨兵 (「空」/「无」/「none」…), 或正文里
        # 自报没提炼出东西 (「无值得提炼…」「未提炼…」)
        if is_empty_response(body) or any(mk in body for mk in NO_CONTENT_MARKERS):
            continue
        # 形状校验: 连一段标题都没有的多半是元报告/回声, 不是三段卡, 不收
        if not any(sec in body for sec in CARD_SECTIONS):
            continue
        # 自包含性: 必须有点要 + (背景 或 影响); 只有一句结论的残卡不收
        if CARD_REQUIRED not in body or not any(s in body for s in CARD_SUPPORTING):
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
