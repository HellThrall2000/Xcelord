"""A warm child process that executes generated pandas code.

pandas is imported once at startup so commands don't pay the import cost.
If code hangs past the timeout the process is killed and respawned.
"""

from __future__ import annotations

import multiprocessing as mp
import threading
from dataclasses import dataclass

from .validator import ALLOWED_MODULES, validate

DEFAULT_TIMEOUT = 20.0
MAX_OUTPUT = 20_000


@dataclass
class ExecResult:
    ok: bool
    sheets: dict | None
    active: str | None
    output: str
    result: object
    error: str | None


def _child(conn) -> None:  # pragma: no cover - runs in subprocess
    import builtins
    import contextlib
    import io
    import os
    import tempfile
    import traceback

    import numpy as np
    import pandas as pd

    os.chdir(tempfile.mkdtemp(prefix="xcelord-sandbox-"))

    real_import = builtins.__import__

    def safe_import(name, globals=None, locals=None, fromlist=(), level=0):
        if level or name.split(".")[0] not in ALLOWED_MODULES:
            raise ImportError(f"import of '{name}' is not allowed")
        return real_import(name, globals, locals, fromlist, level)

    blocked = {"open", "exec", "eval", "compile", "input", "breakpoint", "exit", "quit", "help",
               "globals", "locals", "vars", "getattr", "setattr", "delattr", "memoryview"}
    safe_builtins = {k: v for k, v in vars(builtins).items() if k not in blocked}
    safe_builtins["__import__"] = safe_import

    conn.send(("ready",))
    while True:
        try:
            msg = conn.recv()
        except EOFError:
            return
        if msg is None:
            return
        code, sheets, active = msg
        sheets = dict(sheets)
        ns = {
            "__builtins__": safe_builtins,
            "pd": pd,
            "np": np,
            "df": sheets[active],
            "sheets": sheets,
            "result": None,
        }
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                exec(compile(code, "<generated>", "exec"), ns)
            df = ns.get("df")
            if not isinstance(df, pd.DataFrame):
                raise TypeError("`df` must still be a DataFrame after the code runs")
            new_active = active
            if sheets.get(active) is not df:
                sheets[active] = df
            for name, frame in list(sheets.items()):
                if not isinstance(frame, pd.DataFrame):
                    if isinstance(frame, pd.Series):
                        sheets[name] = frame.to_frame()
                    else:
                        raise TypeError(f"sheets[{name!r}] must be a DataFrame")
                if not isinstance(name, str) or not name or len(name) > 31:
                    raise ValueError(f"Invalid sheet name {name!r} (1-31 characters)")
            for name in sheets:
                sheets[name].columns = [str(c) for c in sheets[name].columns]
            if not sheets:
                raise ValueError("The workbook must keep at least one sheet")
            if new_active not in sheets:
                new_active = next(iter(sheets))
            result = ns.get("result")
            if isinstance(result, pd.Index):
                result = result.to_series()
            conn.send(("ok", sheets, new_active, out.getvalue()[:MAX_OUTPUT], result))
        except BaseException as exc:  # noqa: BLE001 - report every failure to the model
            tb = traceback.format_exception_only(type(exc), exc)
            line = ""
            for frame in traceback.extract_tb(exc.__traceback__):
                if frame.filename == "<generated>":
                    line = f" (line {frame.lineno})"
            conn.send(("error", "".join(tb).strip() + line, out.getvalue()[:MAX_OUTPUT]))


class Sandbox:
    def __init__(self, timeout: float = DEFAULT_TIMEOUT):
        self.timeout = timeout
        self._ctx = mp.get_context("spawn")
        self._lock = threading.Lock()
        self._proc = None
        self._conn = None

    def start(self) -> None:
        with self._lock:
            self._spawn()

    def _spawn(self) -> None:
        parent, child = self._ctx.Pipe()
        proc = self._ctx.Process(target=_child, args=(child,), daemon=True, name="xcelord-sandbox")
        proc.start()
        child.close()
        self._proc, self._conn = proc, parent
        try:
            if parent.poll(60):
                parent.recv()  # "ready"
        except (EOFError, OSError):
            # Worker died on startup; run() will retry and report the failure.
            self._kill()

    def _kill(self) -> None:
        if self._proc is not None:
            self._proc.kill()
            self._proc.join(timeout=2)
        self._proc = self._conn = None

    def stop(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.send(None)
                except (BrokenPipeError, OSError):
                    pass
            self._kill()

    def run(self, code: str, sheets: dict, active: str) -> ExecResult:
        try:
            validate(code)
        except ValueError as exc:
            return ExecResult(False, None, None, "", None, str(exc))
        with self._lock:
            if self._proc is None or not self._proc.is_alive():
                self._spawn()
            if self._proc is None:
                return ExecResult(False, None, None, "", None, "The code sandbox failed to start")
            try:
                self._conn.send((code, sheets, active))
                if not self._conn.poll(self.timeout):
                    self._kill()
                    self._spawn()
                    return ExecResult(False, None, None, "", None,
                                      f"Code took longer than {self.timeout:.0f}s and was stopped")
                reply = self._conn.recv()
            except (EOFError, BrokenPipeError, OSError) as exc:
                self._kill()
                return ExecResult(False, None, None, "", None, f"Sandbox crashed: {exc}")
        if reply[0] == "ok":
            _, new_sheets, new_active, output, result = reply
            return ExecResult(True, new_sheets, new_active, output, result, None)
        _, error, output = reply
        return ExecResult(False, None, None, output, None, error)
