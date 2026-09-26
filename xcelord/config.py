"""User settings persisted to ~/.xcelord/config.json (override with XCELORD_HOME).

API keys never leave this machine except to the provider they belong to.
Environment variables (GROQ_API_KEY, ...) take precedence over stored keys.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from .catalog import ENGINES, PROVIDERS, default_chain

LANGUAGES = {"auto", "en", "hi", "es", "fr", "de", "pt", "it", "ja", "ko", "zh", "bn"}


def home_dir() -> Path:
    path = Path(os.environ.get("XCELORD_HOME", Path.home() / ".xcelord"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _default_settings() -> dict:
    return {
        "keys": {},
        "code_engines": default_chain("code"),
        "voice_engines": default_chain("voice"),
        "fallback": True,
        "self_heal": True,
        "auto_run": True,
        "language": "en",
        "onboarded": False,
    }


def _merge_chain(saved: list[dict] | None, kind: str) -> list[dict]:
    """Keep the user's order/toggles, drop unknown engines, append new catalog engines."""
    result, seen = [], set()
    for item in saved or []:
        engine = ENGINES.get(item.get("id"))
        if engine is None or engine.kind != kind or engine.id in seen:
            continue
        seen.add(engine.id)
        model = item.get("model") or None
        result.append({"id": engine.id, "enabled": bool(item.get("enabled")), "model": model})
    for item in default_chain(kind):
        if item["id"] not in seen:
            result.append(item)
    return result


class SettingsStore:
    def __init__(self, path: Path | None = None):
        self.path = path or home_dir() / "config.json"
        self._lock = threading.Lock()
        self._data = self._load()

    def _load(self) -> dict:
        data = _default_settings()
        if self.path.exists():
            try:
                data.update(json.loads(self.path.read_text()))
            except (OSError, json.JSONDecodeError):
                pass
        data["code_engines"] = _merge_chain(data.get("code_engines"), "code")
        data["voice_engines"] = _merge_chain(data.get("voice_engines"), "voice")
        data["keys"] = {k: v for k, v in (data.get("keys") or {}).items() if k in PROVIDERS and v}
        return data

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2))
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    # --- keys -------------------------------------------------------------

    def key_for(self, provider: str) -> str | None:
        meta = PROVIDERS.get(provider)
        if meta and meta.env_var and os.environ.get(meta.env_var):
            return os.environ[meta.env_var]
        return self._data["keys"].get(provider)

    def key_source(self, provider: str) -> str | None:
        meta = PROVIDERS.get(provider)
        if meta and meta.env_var and os.environ.get(meta.env_var):
            return "env"
        return "saved" if self._data["keys"].get(provider) else None

    # --- access -----------------------------------------------------------

    def get(self, name: str):
        with self._lock:
            return self._data[name]

    def chain(self, kind: str) -> list[dict]:
        with self._lock:
            return [dict(item) for item in self._data[f"{kind}_engines"]]

    def update(self, patch: dict) -> None:
        with self._lock:
            for provider, value in (patch.get("keys") or {}).items():
                if provider not in PROVIDERS or provider == "local":
                    continue
                if value:
                    self._data["keys"][provider] = value.strip()
                else:
                    self._data["keys"].pop(provider, None)
            for kind in ("code", "voice"):
                if f"{kind}_engines" in patch:
                    self._data[f"{kind}_engines"] = _merge_chain(patch[f"{kind}_engines"], kind)
            for flag in ("fallback", "self_heal", "auto_run", "onboarded"):
                if flag in patch:
                    self._data[flag] = bool(patch[flag])
            if patch.get("language") in LANGUAGES:
                self._data["language"] = patch["language"]
            self._save()

    def public(self) -> dict:
        """Settings safe to send to the browser (keys masked)."""
        with self._lock:
            data = {k: v for k, v in self._data.items() if k != "keys"}
            data["code_engines"] = [dict(i) for i in data["code_engines"]]
            data["voice_engines"] = [dict(i) for i in data["voice_engines"]]
        data["keys"] = {}
        for provider in PROVIDERS:
            key = self.key_for(provider)
            data["keys"][provider] = {
                "set": bool(key),
                "hint": f"…{key[-4:]}" if key and len(key) > 8 else None,
                "source": self.key_source(provider),
            }
        return data
