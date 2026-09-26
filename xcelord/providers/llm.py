"""Chat completions for code generation.

OpenRouter, Groq and Gemini all expose the OpenAI chat-completions shape, so a
single function covers every code engine.
"""

from __future__ import annotations

from . import http


def chat(provider: str, key: str, model: str, messages: list[dict], params: dict | None = None,
         max_tokens: int = 8192, timeout: float = 90.0) -> str:
    body = {
        "model": model,
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": max_tokens,
        **(params or {}),
    }
    resp = http.request(
        "POST",
        f"{http.base_url(provider)}/chat/completions",
        provider,
        json=body,
        headers=http.headers(provider, key),
        timeout=timeout,
    )
    data = resp.json()
    if "error" in data:
        raise http.ProviderError(f"{provider}: {data['error'].get('message', data['error'])}")
    try:
        message = data["choices"][0]["message"]
    except (KeyError, IndexError) as exc:
        raise http.ProviderError(f"{provider} returned no choices") from exc
    content = message.get("content")
    if isinstance(content, list):  # some providers return content parts
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    if not content:
        raise http.ProviderError(f"{provider} returned an empty reply (model may have run out of tokens)")
    return content


def test_key(provider: str, key: str) -> str:
    """Cheap authenticated call that doesn't consume model quota."""
    if provider == "openrouter":
        resp = http.request("GET", f"{http.base_url(provider)}/key", provider,
                            headers=http.headers(provider, key), timeout=15)
        info = resp.json().get("data", {})
        used = info.get("free_model_daily_requests") if isinstance(info, dict) else None
        label = info.get("label") if isinstance(info, dict) else None
        detail = f" · {used} free requests used today" if used is not None else ""
        return f"Key OK{f' ({label})' if label else ''}{detail}"
    resp = http.request("GET", f"{http.base_url(provider)}/models", provider,
                        headers=http.headers(provider, key), timeout=15)
    count = len(resp.json().get("data", []))
    return f"Key OK · {count} models available"
