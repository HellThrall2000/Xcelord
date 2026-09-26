"""Shared HTTP client and provider error type.

One pooled keep-alive client per process means TLS handshakes are paid once,
which noticeably cuts per-command latency.
"""

from __future__ import annotations

import httpx

from ..catalog import PROVIDERS

_client: httpx.Client | None = None


def client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(
            timeout=httpx.Timeout(90.0, connect=10.0),
            limits=httpx.Limits(max_keepalive_connections=10, keepalive_expiry=120),
            http2=False,
        )
    return _client


def close() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None


class ProviderError(Exception):
    def __init__(self, message: str, status: int | None = None, retry_after: float | None = None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after

    @property
    def rate_limited(self) -> bool:
        return self.status == 429


def headers(provider: str, key: str) -> dict:
    h = {"Authorization": f"Bearer {key}"}
    if provider == "openrouter":
        h["HTTP-Referer"] = "https://github.com/HellThrall2000/Xcelord"
        h["X-Title"] = "Xcelord"
    return h


def base_url(provider: str) -> str:
    return PROVIDERS[provider].base_url


def raise_for(resp: httpx.Response, provider: str) -> None:
    if resp.is_success:
        return
    try:
        body = resp.json()
        if isinstance(body, list):  # Gemini wraps errors in a list
            body = body[0] if body else {}
        err = body.get("error", body) if isinstance(body, dict) else body
        message = err.get("message") if isinstance(err, dict) else str(err)
    except ValueError:
        message = resp.text[:300]
    message = message or resp.reason_phrase
    retry_after = None
    if resp.headers.get("retry-after"):
        try:
            retry_after = float(resp.headers["retry-after"])
        except ValueError:
            pass
    name = PROVIDERS[provider].name
    bad_key = resp.status_code in (401, 403) or (
        resp.status_code == 400 and "api key" in str(message).lower())
    if bad_key:
        message = f"{name} rejected the API key ({message})"
    elif resp.status_code == 429:
        message = f"{name} rate limit reached ({message})"
    else:
        message = f"{name} error {resp.status_code}: {message}"
    raise ProviderError(message, status=resp.status_code, retry_after=retry_after)


def request(method: str, url: str, provider: str, **kwargs) -> httpx.Response:
    try:
        resp = client().request(method, url, **kwargs)
    except httpx.TimeoutException as exc:
        raise ProviderError(f"{PROVIDERS[provider].name} timed out") from exc
    except httpx.HTTPError as exc:
        raise ProviderError(f"Could not reach {PROVIDERS[provider].name}: {exc}") from exc
    raise_for(resp, provider)
    return resp
