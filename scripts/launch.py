"""Cross-platform launcher used by run.sh / run.bat. Standard library only.

First run: creates .venv, installs Xcelord into it, then starts the app.
Later runs: reinstalls only if pyproject.toml (or the chosen extras) changed.

Launcher flags (everything else is passed to `xcelord`):
  --local-whisper   also install offline Whisper (faster-whisper)
  --reinstall       force a dependency reinstall
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / ".venv"
STAMP = VENV / ".xcelord-install"
GET_PIP = "https://bootstrap.pypa.io/get-pip.py"


def say(msg: str) -> None:
    print(f"[xcelord] {msg}", flush=True)


def fail(msg: str) -> None:
    say(f"ERROR: {msg}")
    sys.exit(1)


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def run(cmd: list, **kwargs) -> None:
    subprocess.run([str(c) for c in cmd], check=True, **kwargs)


def has_pip(python: Path) -> bool:
    return subprocess.run([str(python), "-m", "pip", "--version"],
                          capture_output=True).returncode == 0


def bootstrap_pip(python: Path) -> None:
    say("pip is missing in the environment; downloading it (one time)...")
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "get-pip.py"
        try:
            urllib.request.urlretrieve(GET_PIP, target)
        except OSError as exc:
            fail(f"could not download pip ({exc}). Check your internet connection.")
        run([python, target, "--quiet"])


def ensure_venv() -> Path:
    python = venv_python()
    if python.exists() and has_pip(python):
        return python
    if VENV.exists() and not python.exists():
        shutil.rmtree(VENV)  # half-created environment from an earlier failure
    if not python.exists():
        say("Creating a private Python environment in .venv (one time)...")
        # Debian/Ubuntu ship Python without ensurepip unless python3-venv is installed.
        with_pip = importlib.util.find_spec("ensurepip") is not None
        cmd = [sys.executable, "-m", "venv", VENV] + ([] if with_pip else ["--without-pip"])
        try:
            run(cmd)
        except subprocess.CalledProcessError:
            shutil.rmtree(VENV, ignore_errors=True)
            run([sys.executable, "-m", "venv", "--without-pip", VENV])
    if not has_pip(python):
        bootstrap_pip(python)
    return python


def ensure_installed(python: Path, local_whisper: bool, force: bool) -> None:
    extras = "[local]" if local_whisper else ""
    digest = hashlib.sha256((ROOT / "pyproject.toml").read_bytes() + extras.encode()).hexdigest()
    if not force and STAMP.exists() and STAMP.read_text().strip() == digest:
        return
    say("Installing dependencies (first run takes a minute)...")
    try:
        run([python, "-m", "pip", "install", "--disable-pip-version-check", "--quiet",
             "--editable", f".{extras}"], cwd=ROOT)
    except subprocess.CalledProcessError:
        fail("dependency install failed. See the messages above; rerun with --reinstall after fixing.")
    STAMP.write_text(digest)


def main() -> int:
    if sys.version_info < (3, 10):
        fail(f"Python 3.10 or newer is required (found {sys.version.split()[0]}).")
    args = sys.argv[1:]
    local_whisper = "--local-whisper" in args
    force = "--reinstall" in args
    args = [a for a in args if a not in ("--local-whisper", "--reinstall")]

    python = ensure_venv()
    ensure_installed(python, local_whisper, force)
    say("Starting... press Ctrl+C to stop.")
    try:
        return subprocess.call([str(python), "-m", "xcelord", *args], cwd=ROOT)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
