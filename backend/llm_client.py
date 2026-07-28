"""
LLM 统一接口：DeepSeek / 火山方舟(豆包)，带指数退避重试。
"""
import json
import time
import urllib.request
import urllib.error
from backend.config_manager import get_setting


def chat(prompt: str, max_retries: int = 3) -> str:
    provider = get_setting("llm_provider", "deepseek")
    api_key = get_setting("llm_api_key", "")
    model = get_setting("llm_model", "deepseek-v4-pro")

    if not api_key:
        raise ValueError("API Key 未配置")

    url = (
        "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
        if provider == "volcengine"
        else "https://api.deepseek.com/v1/chat/completions"
    )

    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
    }).encode("utf-8")

    last_error = None
    for attempt in range(max_retries + 1):
        try:
            req = urllib.request.Request(
                url, body,
                {"Authorization": f"Bearer {api_key}",
                 "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read())
            return data["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            last_error = e
            if e.code >= 500 and attempt < max_retries:
                time.sleep(2 ** attempt)
                continue
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_error = e
            if attempt < max_retries:
                time.sleep(2 ** attempt)
                continue
            raise
    raise last_error
