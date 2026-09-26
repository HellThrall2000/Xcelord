import os

import pytest


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XCELORD_HOME", str(tmp_path / "home"))
    for var in ("GROQ_API_KEY", "OPENROUTER_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    yield tmp_path


@pytest.fixture(scope="session")
def sandbox():
    from xcelord.sandbox.worker import Sandbox

    box = Sandbox(timeout=5)
    box.start()
    yield box
    box.stop()


os.environ.setdefault("PYTHONHASHSEED", "0")
