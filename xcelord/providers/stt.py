"""Speech-to-text, one function per provider. All accept 16 kHz mono WAV bytes."""

from __future__ import annotations

import base64
import io
import threading

from . import http

_TRANSCRIBE_PROMPT = (
    "Transcribe this spoken spreadsheet command exactly as said. "
    "Output only the transcript, no quotes or commentary."
)


def _hint_text(hints: list[str]) -> str:
    return ", ".join(hints)[:600]


def transcribe(provider: str, key: str | None, model: str, audio: bytes, language: str | None,
               hints: list[str], params: dict | None = None) -> str:
    if provider == "groq":
        return _groq(key, model, audio, language, hints)
    if provider == "openrouter":
        return _openrouter(key, model, audio, language)
    if provider == "gemini":
        return _gemini(key, model, audio, language, hints, params or {})
    if provider == "local":
        return _local(model, audio, language, hints)
    raise http.ProviderError(f"Unknown voice provider {provider}")


def _groq(key, model, audio, language, hints) -> str:
    data = {"model": model, "response_format": "json", "temperature": "0"}
    if language:
        data["language"] = language
    if hints:
        # Whisper's prompt biases recognition towards these words (column names).
        data["prompt"] = f"Spreadsheet columns: {_hint_text(hints)}."
    resp = http.request(
        "POST", f"{http.base_url('groq')}/audio/transcriptions", "groq",
        headers=http.headers("groq", key), data=data,
        files={"file": ("command.wav", audio, "audio/wav")}, timeout=30,
    )
    return resp.json().get("text", "").strip()


def _openrouter(key, model, audio, language) -> str:
    body = {
        "model": model,
        "input_audio": {"data": base64.b64encode(audio).decode(), "format": "wav"},
        "temperature": 0,
    }
    if language:
        body["language"] = language
    resp = http.request(
        "POST", f"{http.base_url('openrouter')}/audio/transcriptions", "openrouter",
        headers=http.headers("openrouter", key), json=body, timeout=30,
    )
    return resp.json().get("text", "").strip()


def _gemini(key, model, audio, language, hints, params) -> str:
    instructions = _TRANSCRIBE_PROMPT
    if language:
        instructions += f" The speaker is using language code '{language}'."
    if hints:
        instructions += f" Words likely to appear: {_hint_text(hints)}."
    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": instructions},
            {"type": "input_audio",
             "input_audio": {"data": base64.b64encode(audio).decode(), "format": "wav"}},
        ],
    }]
    body = {"model": model, "messages": messages, "temperature": 0, **params}
    resp = http.request(
        "POST", f"{http.base_url('gemini')}/chat/completions", "gemini",
        headers=http.headers("gemini", key), json=body, timeout=30,
    )
    try:
        return (resp.json()["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError) as exc:
        raise http.ProviderError("Gemini returned no transcript") from exc


# --- local faster-whisper -----------------------------------------------------

_local_models: dict[str, object] = {}
_local_lock = threading.Lock()


def local_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True


def _local(model_size, audio, language, hints) -> str:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise http.ProviderError(
            "Local Whisper isn't installed. Run: pip install faster-whisper"
        ) from exc
    with _local_lock:
        model = _local_models.get(model_size)
        if model is None:
            model = WhisperModel(model_size, device="cpu", compute_type="int8")
            _local_models[model_size] = model
        segments, _ = model.transcribe(
            io.BytesIO(audio),
            language=language,
            initial_prompt=f"Spreadsheet columns: {_hint_text(hints)}." if hints else None,
            beam_size=1,
            vad_filter=True,
        )
        return " ".join(s.text.strip() for s in segments).strip()
