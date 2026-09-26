#!/usr/bin/env bash
# Start Xcelord on Linux/macOS:  ./run.sh   (first run sets everything up)
# Options: --local-whisper  --reinstall  --port 9000  --no-browser
#
# Uses Python 3.10+ if one is installed. Otherwise downloads uv and a private
# Python into ./.tools (nothing is installed system-wide, PATH is untouched).
set -euo pipefail
cd "$(dirname "$0")"

TOOLS="$PWD/.tools"
export UV_PYTHON_INSTALL_DIR="$TOOLS/python"

find_python() {
  for candidate in python3.14 python3.13 python3.12 python3.11 python3.10 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 &&
       "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
      command -v "$candidate"
      return 0
    fi
  done
  return 1
}

private_python() {
  if [ ! -x "$TOOLS/uv" ]; then
    echo "[xcelord] Python 3.10+ not found. Downloading a private copy into .tools (one time)..." >&2
    mkdir -p "$TOOLS"
    if command -v curl >/dev/null 2>&1; then
      curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR="$TOOLS" UV_NO_MODIFY_PATH=1 sh >&2
    elif command -v wget >/dev/null 2>&1; then
      wget -qO- https://astral.sh/uv/install.sh | env UV_INSTALL_DIR="$TOOLS" UV_NO_MODIFY_PATH=1 sh >&2
    else
      echo "[xcelord] Need curl or wget to download Python. Install one of them, or install Python 3.10+." >&2
      exit 1
    fi
  fi
  "$TOOLS/uv" python install 3.12 --quiet >&2
  "$TOOLS/uv" python find 3.12
}

PY="$(find_python || private_python)"
exec "$PY" scripts/launch.py "$@"
