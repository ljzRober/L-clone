"""Provider 预设: 把一堆 env 变量收敛成「选一个 provider + 一个 key」。

目的: 新人不用再手工填 8 个 env 变量、也不用知道 DeepSeek 无 embedding 接口
这个坑——预设把每个服务商的 base_url/chat_model/embed 配置固化下来。
"""

from __future__ import annotations

from typing import Dict, List

# 每个 provider 的固定项 (不含 key / db 路径, 那两个在 env_for 里补)
PROVIDERS: Dict[str, Dict[str, str]] = {
    "deepseek": {
        "BRAIN_LLM": "api",
        "BRAIN_BASE_URL": "https://api.deepseek.com/v1",
        "BRAIN_CHAT_MODEL": "deepseek-chat",
        # DeepSeek 不提供 embedding 接口, 用本地确定性哈希向量 (零依赖)
        "BRAIN_EMBED_BACKEND": "local",
        "BRAIN_EMBED_MODEL": "",
    },
    "openai": {
        "BRAIN_LLM": "api",
        "BRAIN_BASE_URL": "https://api.openai.com/v1",
        "BRAIN_CHAT_MODEL": "gpt-4o-mini",
        "BRAIN_EMBED_BACKEND": "api",
        "BRAIN_EMBED_MODEL": "text-embedding-3-small",
    },
    "siliconflow": {
        "BRAIN_LLM": "api",
        "BRAIN_BASE_URL": "https://api.siliconflow.cn/v1",
        "BRAIN_CHAT_MODEL": "Qwen/Qwen2.5-7B-Instruct",
        "BRAIN_EMBED_BACKEND": "api",
        "BRAIN_EMBED_MODEL": "BAAI/bge-m3",
    },
    "zhipu": {
        "BRAIN_LLM": "api",
        "BRAIN_BASE_URL": "https://open.bigmodel.cn/api/paas/v4",
        "BRAIN_CHAT_MODEL": "glm-4-flash",
        "BRAIN_EMBED_BACKEND": "api",
        "BRAIN_EMBED_MODEL": "embedding-3",
    },
    "dummy": {
        "BRAIN_LLM": "dummy",
        "BRAIN_BASE_URL": "",
        "BRAIN_CHAT_MODEL": "",
        "BRAIN_EMBED_BACKEND": "local",
        "BRAIN_EMBED_MODEL": "",
    },
}


def provider_names() -> List[str]:
    return list(PROVIDERS.keys())


def recognize_provider(base_url: str, llm: str) -> str:
    """根据现有配置反推 provider 名 (doctor 用); 认不出返回 ''。"""
    if llm == "dummy":
        return "dummy"
    for name, p in PROVIDERS.items():
        if name == "dummy":
            continue
        if p["BRAIN_BASE_URL"] and base_url == p["BRAIN_BASE_URL"]:
            return name
    return ""


def env_for(provider: str, api_key: str = "", db_path: str = "lclone.db") -> Dict[str, str]:
    """返回该 provider 的 .env 键值 (含 key 与 db 路径)。"""
    if provider not in PROVIDERS:
        raise ValueError(f"未知 provider: {provider} (可选: {', '.join(PROVIDERS)})")
    env = dict(PROVIDERS[provider])
    env["BRAIN_DB_PATH"] = db_path
    if provider == "dummy":
        env["OPENAI_API_KEY"] = ""
    else:
        env["OPENAI_API_KEY"] = api_key
    return env


def render_env(env: Dict[str, str]) -> str:
    """把 env 字典渲染成 .env 文本。"""
    lines = ["# 外置大脑配置 (由 lclone install 生成)", ""]
    for k, v in env.items():
        lines.append(f"{k}={v}")
    return "\n".join(lines) + "\n"
