"""
llm_client.py - LLM 调用封装模块
统一支持任意 OpenAI 兼容接口（DeepSeek / OpenAI / 智谱 / 通义千问 / Moonshot / SiliconFlow 等）
以及 Anthropic Claude（原生 SDK）
根据 .env 中的 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL 自动适配
"""

import os

from dotenv import load_dotenv

load_dotenv()


def _detect_provider() -> dict:
    """
    根据环境变量检测 LLM 配置，返回 {"type": "openai"|"anthropic", "api_key": ..., "base_url": ..., "model": ...}

    优先级：
    1. 统一配置：LLM_API_KEY + LLM_MODEL（+ 可选 LLM_BASE_URL）
    2. 旧版变量兼容：DEEPSEEK_API_KEY / ANTHROPIC_API_KEY
    3. Anthropic Key 自动识别：sk-ant- 前缀自动走 Anthropic SDK
    """
    # ---- 统一配置（推荐） ----
    api_key = os.getenv("LLM_API_KEY", "")
    base_url = os.getenv("LLM_BASE_URL", "")
    model = os.getenv("LLM_MODEL", "")

    if api_key and api_key != "your-api-key-here" and model:
        # 自动识别 Anthropic Key
        if api_key.startswith("sk-ant-"):
            return {
                "type": "anthropic",
                "api_key": api_key,
                "base_url": None,
                "model": model,
            }
        # 其他一律走 OpenAI 兼容接口
        if not base_url:
            raise RuntimeError(
                "使用自定义 LLM 时请在 .env 中设置 LLM_BASE_URL。\n"
                "例如 DeepSeek: LLM_BASE_URL=https://api.deepseek.com"
            )
        return {
            "type": "openai",
            "api_key": api_key,
            "base_url": base_url,
            "model": model,
        }

    # ---- 旧版变量兼容（DeepSeek） ----
    deepseek_key = os.getenv("DEEPSEEK_API_KEY", "")
    if deepseek_key and deepseek_key != "your-api-key-here":
        return {
            "type": "openai",
            "api_key": deepseek_key,
            "base_url": "https://api.deepseek.com",
            "model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        }

    # ---- 旧版变量兼容（Anthropic） ----
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    if anthropic_key and anthropic_key != "your-api-key-here":
        return {
            "type": "anthropic",
            "api_key": anthropic_key,
            "base_url": None,
            "model": os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
        }

    # ---- 未配置 ----
    raise RuntimeError(
        "未检测到有效的 LLM 配置。请在 .env 文件中配置：\n\n"
        "  方式一（推荐，支持任意 OpenAI 兼容接口）：\n"
        "    LLM_API_KEY=sk-xxxxx\n"
        "    LLM_BASE_URL=https://api.deepseek.com\n"
        "    LLM_MODEL=deepseek-chat\n\n"
        "  方式二（旧版兼容）：\n"
        "    DEEPSEEK_API_KEY=sk-xxxxx\n"
        "  或\n"
        "    ANTHROPIC_API_KEY=sk-ant-xxxxx"
    )


def call_llm(system_prompt: str, user_prompt: str, max_tokens: int = 4096) -> str:
    """
    调用 LLM API 生成内容。
    自动检测 .env 配置，支持 OpenAI 兼容接口和 Anthropic Claude。
    """
    cfg = _detect_provider()
    provider_type = cfg["type"]
    model = cfg["model"]
    print(f"  LLM 提供商: {model} ({provider_type})")

    if provider_type == "anthropic":
        return _call_anthropic(cfg, system_prompt, user_prompt, max_tokens)
    else:
        return _call_openai_compatible(cfg, system_prompt, user_prompt, max_tokens)


def _call_openai_compatible(cfg: dict, system_prompt: str, user_prompt: str, max_tokens: int) -> str:
    """
    通过 OpenAI SDK 调用任意兼容接口。
    支持 DeepSeek、OpenAI、智谱、通义千问、Moonshot、SiliconFlow 等。
    """
    from openai import OpenAI

    client = OpenAI(
        api_key=cfg["api_key"],
        base_url=cfg["base_url"],
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    response = client.chat.completions.create(
        model=cfg["model"],
        messages=messages,
        max_tokens=max_tokens,
        temperature=0.7,
    )

    return response.choices[0].message.content


def _call_anthropic(cfg: dict, system_prompt: str, user_prompt: str, max_tokens: int) -> str:
    """通过 Anthropic SDK 调用 Claude API"""
    import anthropic

    client = anthropic.Anthropic(api_key=cfg["api_key"])
    message = client.messages.create(
        model=cfg["model"],
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return message.content[0].text
