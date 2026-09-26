"""Static catalog of providers and engines.

Engines are listed best → worst. The order is the default fallback chain; users
can toggle, reorder and override models from the UI. Code generation and voice
transcription are separate chains so each can use a different provider.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class Provider:
    id: str
    name: str
    env_var: str | None
    key_url: str | None
    base_url: str
    blurb: str


@dataclass(frozen=True)
class Engine:
    id: str
    kind: str  # "code" | "voice"
    provider: str
    name: str
    model: str
    free: bool
    limits: str
    note: str
    daily_cap: int | None = None
    enabled_by_default: bool = True
    params: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


PROVIDERS: dict[str, Provider] = {
    p.id: p
    for p in [
        Provider(
            id="openrouter",
            name="OpenRouter",
            env_var="OPENROUTER_API_KEY",
            key_url="https://openrouter.ai/settings/keys",
            base_url="https://openrouter.ai/api/v1",
            blurb="Free NVIDIA Nemotron models. 50 free requests/day, 1,000/day after a one-time $10 top-up.",
        ),
        Provider(
            id="gemini",
            name="Google Gemini",
            env_var="GEMINI_API_KEY",
            key_url="https://aistudio.google.com/apikey",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai",
            blurb="AI Studio free tier for code and voice. Free-tier prompts may be used by Google to improve products.",
        ),
        Provider(
            id="groq",
            name="Groq",
            env_var="GROQ_API_KEY",
            key_url="https://console.groq.com/keys",
            base_url="https://api.groq.com/openai/v1",
            blurb="Fastest option. Free Whisper (8 h audio/day) and gpt-oss code models.",
        ),
        Provider(
            id="local",
            name="On this computer",
            env_var=None,
            key_url=None,
            base_url="",
            blurb="Offline Whisper via faster-whisper. No key, no limits, slower on CPU.",
        ),
    ]
}


CODE_ENGINES: list[Engine] = [
    Engine(
        id="openrouter-nemotron-ultra",
        kind="code",
        provider="openrouter",
        name="Nemotron 3 Ultra",
        model="nvidia/nemotron-3-ultra-550b-a55b:free",
        free=True,
        limits="20/min · 50/day (1,000 with credits)",
        note="Strongest free coder. Reasoning model, so a few seconds slower.",
        daily_cap=50,
        params={"reasoning": {"effort": "low", "exclude": True}},
    ),
    Engine(
        id="gemini-flash",
        kind="code",
        provider="gemini",
        name="Gemini 3.8 Flash",
        model="gemini-3.8-flash",
        free=True,
        limits="AI Studio free tier",
        note="Strong and quick. Free tier data may be used by Google.",
        params={"reasoning_effort": "low"},
    ),
    Engine(
        id="groq-gpt-oss-120b",
        kind="code",
        provider="groq",
        name="gpt-oss 120B",
        model="openai/gpt-oss-120b",
        free=True,
        limits="30/min · 1,000/day · 8K tokens/min",
        note="Very low latency. Token/minute cap suits small sheets.",
        daily_cap=1000,
        params={"reasoning_effort": "low", "include_reasoning": False},
    ),
    Engine(
        id="openrouter-nemotron-super",
        kind="code",
        provider="openrouter",
        name="Nemotron 3 Super",
        model="nvidia/nemotron-3-super-120b-a12b:free",
        free=True,
        limits="20/min · shares OpenRouter daily cap",
        note="Faster, lighter Nemotron.",
        daily_cap=50,
        params={"reasoning": {"effort": "low", "exclude": True}},
    ),
    Engine(
        id="gemini-flash-lite",
        kind="code",
        provider="gemini",
        name="Gemini 3.5 Flash-Lite",
        model="gemini-3.5-flash-lite",
        free=True,
        limits="AI Studio free tier",
        note="Fastest Gemini, weaker on multi-step edits.",
        params={"reasoning_effort": "low"},
    ),
    Engine(
        id="groq-gpt-oss-20b",
        kind="code",
        provider="groq",
        name="gpt-oss 20B",
        model="openai/gpt-oss-20b",
        free=True,
        limits="30/min · 1,000/day · 8K tokens/min",
        note="Last-resort fallback. Fine for simple edits.",
        daily_cap=1000,
        params={"reasoning_effort": "low", "include_reasoning": False},
    ),
]


VOICE_ENGINES: list[Engine] = [
    Engine(
        id="groq-whisper-turbo",
        kind="voice",
        provider="groq",
        name="Whisper Large v3 Turbo",
        model="whisper-large-v3-turbo",
        free=True,
        limits="20/min · 2,000/day · 8 h audio/day",
        note="Best free option: real Whisper, sub-second.",
        daily_cap=2000,
    ),
    Engine(
        id="groq-whisper-large",
        kind="voice",
        provider="groq",
        name="Whisper Large v3",
        model="whisper-large-v3",
        free=True,
        limits="20/min · 2,000/day · 8 h audio/day",
        note="Slightly more accurate, slightly slower.",
        daily_cap=2000,
    ),
    Engine(
        id="gemini-flash-lite-stt",
        kind="voice",
        provider="gemini",
        name="Gemini 3.5 Flash-Lite",
        model="gemini-3.5-flash-lite",
        free=True,
        limits="AI Studio free tier",
        note="Not Whisper, but accurate. Free tier data may be used by Google.",
        params={"reasoning_effort": "minimal"},
    ),
    Engine(
        id="openrouter-whisper-turbo",
        kind="voice",
        provider="openrouter",
        name="Whisper Large v3 Turbo",
        model="openai/whisper-large-v3-turbo",
        free=False,
        limits="~$0.01 per hour of audio",
        note="Needs OpenRouter credits. Off by default.",
        enabled_by_default=False,
    ),
    Engine(
        id="local-whisper",
        kind="voice",
        provider="local",
        name="Local Whisper (base)",
        model="base",
        free=True,
        limits="Unlimited · offline",
        note="Needs `pip install faster-whisper`. Slower on CPU.",
    ),
]


ENGINES: dict[str, Engine] = {e.id: e for e in CODE_ENGINES + VOICE_ENGINES}


def default_chain(kind: str) -> list[dict]:
    engines = CODE_ENGINES if kind == "code" else VOICE_ENGINES
    return [{"id": e.id, "enabled": e.enabled_by_default, "model": None} for e in engines]
