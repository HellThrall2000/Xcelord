import json

import pytest
from fastapi.testclient import TestClient

from xcelord.providers import http as provider_http
from xcelord.providers import llm, stt


@pytest.fixture
def client():
    from xcelord.server import app

    with TestClient(app) as c:
        yield c


def _enable_only(client, code_ids, voice_ids=()):
    s = client.get("/api/settings").json()
    for item in s["code_engines"]:
        item["enabled"] = item["id"] in code_ids
    for item in s["voice_engines"]:
        item["enabled"] = item["id"] in voice_ids
    client.put("/api/settings", json={"code_engines": s["code_engines"], "voice_engines": s["voice_engines"]})


def test_settings_roundtrip_masks_keys(client):
    r = client.put("/api/settings", json={"keys": {"groq": "gsk_secret_1234"}, "language": "hi"})
    body = r.json()
    assert body["keys"]["groq"] == {"set": True, "hint": "…1234", "source": "saved"}
    assert "gsk_secret" not in json.dumps(body)
    assert body["language"] == "hi"
    # engine order is preserved and new catalog entries are kept
    order = [e["id"] for e in body["code_engines"]]
    assert order[0] == "openrouter-nemotron-ultra"


def test_no_engine_gives_clear_error(client):
    client.post("/api/workbook/sample")
    r = client.post("/api/command", json={"text": "add a column"})
    assert r.status_code == 503 and "No code engine" in r.json()["detail"]


def test_command_preview_accept_undo(client, monkeypatch):
    client.put("/api/settings", json={"keys": {"openrouter": "or-key-abcdef", "groq": "gsk-abcdef12"}})
    _enable_only(client, {"openrouter-nemotron-ultra", "groq-gpt-oss-120b"})
    calls = []

    def fake_chat(provider, key, model, messages, params=None, **kw):
        calls.append(provider)
        if provider == "openrouter":
            raise provider_http.ProviderError("rate limit", status=429)
        return json.dumps({"explanation": "Added a bonus column.",
                           "code": "df['Bonus'] = (df['Sales'] * 0.1).round(2)"})

    monkeypatch.setattr(llm, "chat", fake_chat)
    wb = client.post("/api/workbook/sample").json()
    assert wb["loaded"] and wb["sheet"]["columns"]

    r = client.post("/api/command", json={"text": "add a 10% bonus column"}).json()
    assert r["status"] == "proposal", r
    assert calls == ["openrouter", "groq"]  # fell back after the 429
    assert r["engine"] == "groq-gpt-oss-120b" and r["attempts"][0]["ok"] is False
    assert r["preview"]["data"]["columns"][-1] == "Bonus"
    assert r["preview"]["cells"]

    # Rate-limited engine is now cooling down, so the next call goes straight to Groq.
    calls.clear()
    wb2 = client.post(f"/api/proposals/{r['proposal_id']}/accept").json()
    assert "Bonus" in wb2["sheet"]["columns"] and wb2["can_undo"]
    client.post("/api/command", json={"text": "again"})
    assert calls[0] == "groq"

    undone = client.post("/api/workbook/undo").json()
    assert "Bonus" not in undone["sheet"]["columns"]


def test_question_returns_answer_without_proposal(client, monkeypatch):
    client.put("/api/settings", json={"keys": {"groq": "gsk-abcdef12"}})
    _enable_only(client, {"groq-gpt-oss-120b"})
    monkeypatch.setattr(llm, "chat", lambda *a, **k: json.dumps(
        {"explanation": "Totals by department.", "code": "result = df.groupby('Department')['Sales'].sum()"}))
    client.post("/api/workbook/sample")
    r = client.post("/api/command", json={"text": "total sales by department"}).json()
    assert r["status"] == "answer"
    assert r["result"]["type"] == "table" and r["result"]["columns"] == ["Department", "Sales"]


def test_self_heal_retries_once(client, monkeypatch):
    client.put("/api/settings", json={"keys": {"groq": "gsk-abcdef12"}})
    _enable_only(client, {"groq-gpt-oss-120b"})
    replies = iter([
        json.dumps({"explanation": "x", "code": "df['Nope'].sum()"}),
        json.dumps({"explanation": "Fixed.", "code": "result = df['Sales'].sum()"}),
    ])
    monkeypatch.setattr(llm, "chat", lambda *a, **k: next(replies))
    client.post("/api/workbook/sample")
    r = client.post("/api/command", json={"text": "sum sales"}).json()
    assert r["status"] == "answer" and r["repaired"] is True


def test_transcribe_uses_voice_chain(client, monkeypatch):
    client.put("/api/settings", json={"keys": {"groq": "gsk-abcdef12", "gemini": "AIza-abcdef"}})
    _enable_only(client, set(), {"groq-whisper-turbo", "gemini-flash-lite-stt"})
    seen = {}

    def fake(provider, key, model, audio, language, hints, params=None):
        seen.setdefault("providers", []).append(provider)
        seen["hints"] = hints
        if provider == "groq":
            raise provider_http.ProviderError("down", status=500)
        return "sort by sales"

    monkeypatch.setattr(stt, "transcribe", fake)
    client.post("/api/workbook/sample")
    r = client.post("/api/transcribe", files={"audio": ("a.wav", b"RIFF....", "audio/wav")}).json()
    assert r["text"] == "sort by sales" and r["engine"] == "gemini-flash-lite-stt"
    assert seen["providers"] == ["groq", "gemini"]
    assert "Sales" in seen["hints"]


def test_upload_rejects_other_types(client):
    r = client.post("/api/workbook/upload", files={"file": ("x.txt", b"hi", "text/plain")})
    assert r.status_code == 400


def test_index_served(client):
    assert client.get("/").status_code == 200


@pytest.mark.parametrize("status,body,expected", [
    (400, [{"error": {"message": "Please pass a valid API key"}}], "rejected the API key"),
    (401, {"error": {"message": "Invalid API Key"}}, "rejected the API key"),
    (429, {"error": {"message": "slow down"}}, "rate limit"),
    (500, "oops", "error 500"),
])
def test_provider_error_parsing(status, body, expected):
    import httpx

    kwargs = {"json": body} if not isinstance(body, str) else {"text": body}
    resp = httpx.Response(status, request=httpx.Request("GET", "https://x"), **kwargs)
    with pytest.raises(provider_http.ProviderError) as exc:
        provider_http.raise_for(resp, "gemini")
    assert expected in str(exc.value)
    assert exc.value.rate_limited == (status == 429)


def test_locked_file_gives_clear_error(client, monkeypatch):
    from xcelord.excel import workbook

    client.post("/api/workbook/sample")

    def locked(*a, **k):
        raise PermissionError("in use")

    monkeypatch.setattr(workbook, "write_file", locked)
    r = client.post("/api/workbook/cell", json={"sheet": "Sheet1", "row": 0, "col": 2, "value": "1"})
    assert r.status_code == 423 and "open in Excel" in r.json()["detail"]
