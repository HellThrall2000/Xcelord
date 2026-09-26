"""Runs a ranked engine chain with fallback, rate-limit cooldowns and usage counts."""

from __future__ import annotations

import datetime as dt
import json
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from ..catalog import ENGINES, PROVIDERS, Engine
from ..config import SettingsStore, home_dir
from ..providers import stt
from ..providers.http import ProviderError

DEFAULT_COOLDOWN = 30.0


@dataclass
class ResolvedEngine:
    engine: Engine
    model: str
    key: str | None


@dataclass
class Attempt:
    engine_id: str
    name: str
    ok: bool
    ms: int
    error: str | None = None


@dataclass
class ChainResult:
    value: object
    engine: ResolvedEngine
    attempts: list[Attempt] = field(default_factory=list)

    def meta(self) -> dict:
        return {
            "engine": self.engine.engine.id,
            "engine_name": self.engine.engine.name,
            "provider": PROVIDERS[self.engine.engine.provider].name,
            "model": self.engine.model,
            "attempts": [a.__dict__ for a in self.attempts],
        }


class NoEngineError(Exception):
    def __init__(self, message: str, attempts: list[Attempt]):
        super().__init__(message)
        self.attempts = attempts


class UsageLog:
    """Per-engine request counts for the current UTC day, persisted to disk."""

    def __init__(self):
        self.path = home_dir() / "usage.json"
        self._lock = threading.Lock()
        try:
            self._data = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            self._data = {}

    @staticmethod
    def _today() -> str:
        return dt.datetime.now(dt.timezone.utc).date().isoformat()

    def bump(self, engine_id: str) -> None:
        with self._lock:
            if self._data.get("day") != self._today():
                self._data = {"day": self._today(), "counts": {}}
            counts = self._data.setdefault("counts", {})
            counts[engine_id] = counts.get(engine_id, 0) + 1
            try:
                self.path.write_text(json.dumps(self._data))
            except OSError:
                pass

    def today(self) -> dict[str, int]:
        with self._lock:
            if self._data.get("day") != self._today():
                return {}
            return dict(self._data.get("counts", {}))


class Router:
    def __init__(self, settings: SettingsStore):
        self.settings = settings
        self.usage = UsageLog()
        self._cooldown: dict[str, float] = {}

    def available(self, kind: str) -> list[ResolvedEngine]:
        """Enabled engines in rank order whose provider is usable."""
        out = []
        for item in self.settings.chain(kind):
            engine = ENGINES[item["id"]]
            if not item["enabled"]:
                continue
            if engine.provider == "local":
                if not stt.local_available():
                    continue
                key = None
            else:
                key = self.settings.key_for(engine.provider)
                if not key:
                    continue
            out.append(ResolvedEngine(engine, item.get("model") or engine.model, key))
        return out

    def cooling(self, engine_id: str) -> float:
        remaining = self._cooldown.get(engine_id, 0) - time.monotonic()
        return max(0.0, remaining)

    def run(self, kind: str, call: Callable[[ResolvedEngine], object]) -> ChainResult:
        engines = self.available(kind)
        label = "code" if kind == "code" else "voice"
        if not engines:
            raise NoEngineError(
                f"No {label} engine is ready. Add an API key or enable an engine in Settings.", [])

        # Engines on cooldown go last rather than being skipped entirely.
        ready = [e for e in engines if not self.cooling(e.engine.id)]
        cooling = [e for e in engines if self.cooling(e.engine.id)]
        ordered = ready + cooling
        if not self.settings.get("fallback"):
            ordered = ordered[:1]

        attempts: list[Attempt] = []
        for resolved in ordered:
            start = time.perf_counter()
            try:
                value = call(resolved)
            except ProviderError as exc:
                ms = int((time.perf_counter() - start) * 1000)
                if resolved.engine.provider != "local":
                    self.usage.bump(resolved.engine.id)
                if exc.rate_limited:
                    self._cooldown[resolved.engine.id] = time.monotonic() + (exc.retry_after or DEFAULT_COOLDOWN)
                attempts.append(Attempt(resolved.engine.id, resolved.engine.name, False, ms, str(exc)))
                continue
            ms = int((time.perf_counter() - start) * 1000)
            if resolved.engine.provider != "local":
                self.usage.bump(resolved.engine.id)
            self._cooldown.pop(resolved.engine.id, None)
            attempts.append(Attempt(resolved.engine.id, resolved.engine.name, True, ms))
            return ChainResult(value, resolved, attempts)

        last = attempts[-1].error if attempts else "unknown error"
        raise NoEngineError(f"All {label} engines failed. Last error: {last}", attempts)
