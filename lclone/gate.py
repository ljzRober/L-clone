"""确定性准入闸门: 脚本优先判定, LLM 只在判不准时兜底。

把一次 capture 的文本判成三类之一:

  skip       明确不值得记 → 直接丢弃, **0 次 LLM 调用** (预期覆盖绝大多数轮次)
  candidate  命中「决策/约定/规则/教训」强信号 → 交 LLM 成卡, 跳过判定
  uncertain  不明确 → 交 llm.judge_insight 做一次极便宜的 yes/no 判定

设计约束:
  - **本模块是「记什么」的唯一标准源 (SSOT)**, 只依赖标准库, 不 import llm/db/config,
    因此可离线单测, 也可被任何宿主复用。词表只在这里维护, 别处一律引用 (见 memory.DID_MARKERS)。
  - 判定只在**用户轮**上做 (按 `用户：`/`助手：` 切分): 助手输出多为「做了什么」, 是最大的噪声源。
  - 保守档白名单: 只收**决定性**的「决策/约定/规则」与「教训/经验」说法。高频泛词
    (下次 / 原来 / 避免 / 标准 / 不要) 一律不收 —— 它们会把日常闲聊判成候选。
  - 否定作用域: 信号词前 3 字内出现 不/没/无需/不用/取消 → 该命中不计;
    但「不错 / 不但 / 不仅 / 不如 / 不少」里的「不」不算否定。
  - 疑问句优先于强信号: 「为什么必须这样？」是提问, 不是决策。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Tuple

# ---------------------------------------------------------------- 判定结果
SKIP = "skip"
CANDIDATE = "candidate"
UNCERTAIN = "uncertain"

# ---------------------------------------------------------------- 标准常量 (调参改这里)
# 批量捕获的会话里, 角色标记由各宿主统一成这两个前缀
USER_MARKER = "用户："
ASSISTANT_MARKER = "助手："

# 有效文本下限: 低于此长度视为无信息量 (显式「记住」旁路不受此限)
MIN_CHARS = 12

# 强信号的独立下限: 命中信号时放宽到 6 字, 以免「决定统一口径」这类短而 decisive
# 的句子被长度闸门误杀
MIN_SIGNAL_CHARS = 6

# 单次 capture 最多成卡几条 (确定性护栏, 防"一轮塞一堆")
MAX_PER_CAPTURE = 2

# 用户显式要求记忆 → 旁路闸门 (长度/噪声/负信号都不拦)
EXPLICIT_MARKERS = ("记住", "记一下", "记下来", "记下", "remember")

# 强信号 1 (最高优先): 政策/规则语气 —— 明确"定下规则", 压过「做了什么」。
# 「回滚策略定为保留三个版本」是规则, 不是工作日志, 不能被 DID 吃掉。
POLICY_MARKERS = (
    "决定", "定了", "定为", "规定", "统一", "一律", "以后都",
    "规范", "口径", "原则", "必须", "禁止", "默认", "方案是", "策略是", "采用",
)
# 强信号 1b (次优先): 这些词在工作日志叙述里也常出现 ("确定是网络抖动导致的"),
# 因此**让位给「做了什么」** —— 只有全文没有 DID 证据时才算决策。
SOFT_DECISION_MARKERS = ("确定", "约定")

# 强信号 2: 教训/经验 (只收决定性说法, 不收「下次」「原来」「避免」这类高频词)
STRONG_LESSON_MARKERS = (
    "教训", "踩坑", "坑在", "原因在于", "问题在于", "经验是",
)
# 弱教训信号: 单独出现算信号, 但**与寒暄词同现时不算** ——
# 「嗯嗯明白了, 那下次注意」是客套, 不是教训; 「下次注意: 迁移前先备份」才算
WEAK_LESSON_MARKERS = ("下次注意", "下次要", "以后注意")
LESSON_MARKERS = STRONG_LESSON_MARKERS + WEAK_LESSON_MARKERS

# 负信号: 「做了什么」归 git / spec (拉丁词按词边界匹配, 见 hits())
DID_MARKERS = (
    "修复", "重构", "迁移", "回滚", "commit", "fix", "bug", "hotfix",
    "refactor", "新增端点", "改接口", "实现了一个",
)

# 负信号: 寒暄/确认 (仅在短句时生效)
CHAT_MARKERS = (
    "你好", "谢谢", "多谢", "好的", "嗯", "收到", "继续", "可以了", "没问题",
)

# 负信号: 疑问句结尾
ASK_SUFFIXES = ("？", "?")

# 否定作用域
NEGATIONS = ("无需", "不用", "取消", "不", "没")
NEG_WINDOW = 3
# 这些字跟在「不」后面时, 不构成否定 (不错 / 不但 / 不仅 / 不如 / 不少)
NEG_EXEMPT_AFTER = ("错", "但", "仅", "如", "少", "过")


@dataclass(frozen=True)
class Verdict:
    """一次判定的结果 (可 JSON 序列化, 供 CLI/HTTP 诊断展示)。"""

    kind: str                       # skip | candidate | uncertain
    hits: Tuple[str, ...] = ()      # 命中的信号词
    reason: str = ""                # 判定理由 (人话)

    def to_dict(self) -> Dict:
        return {"kind": self.kind, "hits": list(self.hits), "reason": self.reason}


# ---------------------------------------------------------------- 内部工具
_CODE_FENCE_RE = re.compile(r"```.*?```", re.S)
# 角色标记只在**行首**生效 (由 USER_MARKER / ASSISTANT_MARKER 派生, 保持单一来源)
_USER_LINE_RE = re.compile("^" + re.escape(USER_MARKER), re.M)
_ROLE_LINE_RE = re.compile(
    "^(?:" + re.escape(USER_MARKER) + "|" + re.escape(ASSISTANT_MARKER) + ")")
# 只剥「明显不是自然语言」的行; 不剥 "# " (Markdown 标题也是正常用户输入)
_LINE_NOISE_PREFIX = ("$ ", ">>> ", "Traceback", '  File "', "  at ")
_ASCII_RE_CACHE: Dict[str, re.Pattern] = {}


def user_turns(text: str) -> str:
    """只取文本里的**用户轮**内容; 没有角色标记时原样返回。

    宿主统一用 `用户：` / `助手：` 标注 (见 DSH 插件的 buildCaptureText)。助手轮
    多为「做了什么」, 是噪声主源, 剔除后闸门判定显著更准。

    **只在行首认角色标记**: 正文里引用「用户：/助手：」(讨论标记格式本身时很常见)
    不算角色切换, 否则一段正常内容会被切碎。切不出用户轮时退回原文,
    避免把畸形输入判成"无内容"而静默丢弃。
    """
    t = text or ""
    if not _USER_LINE_RE.search(t):
        return t
    out: List[str] = []
    role: str = ""
    for line in t.splitlines():
        m = _ROLE_LINE_RE.match(line)
        if m:
            role = USER_MARKER if line.startswith(USER_MARKER) else ASSISTANT_MARKER
            line = line[m.end():]
        if role == USER_MARKER:
            out.append(line)
    joined = "\n".join(out).strip()
    return joined if joined else t


def strip_noise(text: str) -> str:
    """剥掉代码块/堆栈/命令行回显, 只留自然语言 (用于长度与信号判定)。"""
    t = _CODE_FENCE_RE.sub(" ", text or "")
    kept = []
    for line in t.splitlines():
        s = line.strip()
        if any(s.startswith(p) for p in _LINE_NOISE_PREFIX):
            continue
        kept.append(line)
    return "\n".join(kept).strip()


def hits(text: str, markers) -> Tuple[str, ...]:
    """命中的标记词。纯 ASCII 标记按词边界 + 忽略大小写匹配。

    词边界是必须的: 否则 `prefix` 会命中 `fix`、`debug` 会命中 `bug`,
    一个英文命名约定就被误判成「做了什么」。
    """
    out = []
    for m in markers:
        if m.isascii():
            pat = _ASCII_RE_CACHE.get(m)
            if pat is None:
                pat = re.compile(
                    rf"(?<![A-Za-z0-9]){re.escape(m)}(?![A-Za-z0-9])", re.I)
                _ASCII_RE_CACHE[m] = pat
            if pat.search(text or ""):
                out.append(m)
        elif m in text:
            out.append(m)
    return tuple(out)


def _negated_head(head: str) -> bool:
    """前文片段里是否有真正的否定 (排除「不错/不但/不仅/不如/不少/不过」)。"""
    for n in NEGATIONS:
        j = head.find(n)
        while j >= 0:
            after = head[j + len(n): j + len(n) + 1]
            if after not in NEG_EXEMPT_AFTER:
                return True
            j = head.find(n, j + len(n))
    return False


def _signal_live(text: str, marker: str) -> bool:
    """该信号词是否存在**未被否定**的出现。"""
    start = 0
    while True:
        i = text.find(marker, start)
        if i < 0:
            return False
        if not _negated_head(text[max(0, i - NEG_WINDOW): i]):
            return True
        start = i + len(marker)


def _live(text: str, markers) -> Tuple[str, ...]:
    return tuple(m for m in markers if m in text and _signal_live(text, m))


def _policy_signals(text: str) -> Tuple[str, ...]:
    """政策/规则语气 (未被否定)。压过「做了什么」。"""
    return _live(text, POLICY_MARKERS)


def _lesson_signals(text: str) -> Tuple[str, ...]:
    """教训/经验。也压过「做了什么」—— 工作日志很少主动写「踩坑/下次注意」。

    弱教训信号 (下次注意/下次要/以后注意) 在寒暄污染的短句里不作数。
    """
    strong = _live(text, STRONG_LESSON_MARKERS)
    if strong:
        return strong
    if hits(text, CHAT_MARKERS):
        return ()
    return _live(text, WEAK_LESSON_MARKERS)


# ---------------------------------------------------------------- 主入口
def classify(text: str) -> Verdict:
    """把一段 capture 文本判成 skip / candidate / uncertain (纯函数, 无副作用)。

    优先级: 显式要求 > 疑问句 > 政策/规则/教训 > 文本长度 > 「做了什么」 > 含糊措辞 > 寒暄。
    「做了什么」压在**含糊**决策词 (确定/约定) 之上, 是为了让工作日志稳定落在 skip;
    但压不过政策语气与教训语气 —— 「回滚策略定为…」「踩坑的原因在于…」是知识, 不是流水账。
    """
    u = user_turns(text)
    if not u.strip():
        return Verdict(SKIP, (), "无用户轮内容")

    # 用户显式要求记忆 → 旁路 (长度/噪声/负信号都不拦)
    explicit = hits(u, EXPLICIT_MARKERS)
    if explicit:
        return Verdict(CANDIDATE, explicit, "用户显式要求记忆")

    clean = strip_noise(u)
    # 疑问句优先于强信号: 「为什么必须这样？」是提问不是决策
    if clean.rstrip().endswith(ASK_SUFFIXES):
        return Verdict(SKIP, (), "疑问句")

    did = hits(clean, DID_MARKERS)
    decisive = _policy_signals(clean) + _lesson_signals(clean)
    # 决定性语气优先于长度与「做了什么」: 「决定统一口径」只有 6 字但必须收
    if decisive and len(clean) >= MIN_SIGNAL_CHARS:
        return Verdict(CANDIDATE, decisive, "命中政策/规则/教训强信号")

    if len(clean) < MIN_CHARS:
        # 短句: 有「做了什么」证据算工作日志; 含糊决策词也放行 (如「确定用 SQLite」)
        soft = _live(clean, SOFT_DECISION_MARKERS)
        if not did and soft and len(clean) >= MIN_SIGNAL_CHARS:
            return Verdict(CANDIDATE, soft, "短句命中决策/约定信号")
        return Verdict(SKIP, (), f"有效文本过短 (<{MIN_CHARS} 字)")

    if did:
        return Verdict(SKIP, did, "「做了什么」归 git/spec")

    soft = _live(clean, SOFT_DECISION_MARKERS)
    if soft:
        return Verdict(CANDIDATE, soft, "命中决策/约定信号")

    if len(clean) < 30:
        chat = hits(clean, CHAT_MARKERS)
        if chat:
            return Verdict(SKIP, chat, "寒暄/确认")

    return Verdict(UNCERTAIN, (), "无强信号, 交 LLM 判定")


def explain(text: str) -> str:
    """给 CLI 用的人话诊断。"""
    v = classify(text)
    label = {SKIP: "跳过 (不调 LLM)", CANDIDATE: "候选 (交 LLM 成卡)",
             UNCERTAIN: "不确定 (先 LLM 判定)"}[v.kind]
    lines = [f"判定: {v.kind} — {label}", f"理由: {v.reason}"]
    if v.hits:
        lines.append("命中: " + ", ".join(v.hits))
    u = user_turns(text)
    clean = strip_noise(u)
    lines.append(f"用户轮有效长度: {len(clean)} 字 / 原文 {len(text or '')} 字")
    return "\n".join(lines)
