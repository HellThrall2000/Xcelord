"""HTTP API + static frontend.

Voice and code inference are separate endpoints on purpose: the transcript comes
back as soon as speech-to-text finishes, and either side can use a different
provider (or fail over) without affecting the other.
"""

from __future__ import annotations

import re
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from . import __version__
from .catalog import CODE_ENGINES, PROVIDERS, VOICE_ENGINES
from .config import SettingsStore, home_dir
from .engine.codegen import CommandRunner
from .engine.router import NoEngineError, Router
from .excel import context
from .excel.workbook import Workspace, sheet_payload
from .providers import http, llm, stt
from .providers.http import ProviderError
from .sandbox.worker import Sandbox

STATIC = Path(__file__).parent / "static"
SAMPLE = Path(__file__).parent / "samples" / "sample_sales.xlsx"
MAX_AUDIO_BYTES = 10 * 1024 * 1024
MAX_UPLOAD_BYTES = 50 * 1024 * 1024


class State:
    def __init__(self):
        self.settings = SettingsStore()
        self.router = Router(self.settings)
        self.workspace = Workspace(home_dir() / "workspace")
        self.sandbox = Sandbox()
        self.runner = CommandRunner(self.router, self.sandbox, self.workspace)


state: State | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global state
    state = State()
    state.sandbox.start()
    yield
    state.sandbox.stop()
    http.close()


app = FastAPI(title="Xcelord", version=__version__, lifespan=lifespan)


@app.exception_handler(NoEngineError)
async def _no_engine(_, exc: NoEngineError):
    return JSONResponse(status_code=503, content={
        "detail": str(exc), "attempts": [a.__dict__ for a in exc.attempts]})


@app.exception_handler(PermissionError)
async def _locked(_, exc: PermissionError):
    # Windows refuses to overwrite a workbook that is open in Excel.
    return JSONResponse(status_code=423, content={
        "detail": "Couldn't save: the file is locked, probably open in Excel. Close it there and try again."})


def _require_workbook() -> Workspace:
    if not state.workspace.loaded:
        raise HTTPException(409, "Open a workbook first")
    return state.workspace


def _workbook_response(include_sheet: bool = True) -> dict:
    ws = state.workspace
    with ws.lock:
        data = ws.state()
        if include_sheet and ws.loaded:
            data["sheet"] = sheet_payload(ws.sheets[ws.active])
    return data


# --- settings & providers -----------------------------------------------------

@app.get("/api/meta")
def meta():
    return {
        "version": __version__,
        "providers": [p.__dict__ for p in PROVIDERS.values()],
        "code_engines": [e.to_dict() for e in CODE_ENGINES],
        "voice_engines": [e.to_dict() for e in VOICE_ENGINES],
        "local_whisper": stt.local_available(),
    }


@app.get("/api/settings")
def get_settings():
    data = state.settings.public()
    data["usage"] = state.router.usage.today()
    data["cooldowns"] = {e: round(state.router.cooling(e)) for e in
                         [i["id"] for i in data["code_engines"] + data["voice_engines"]]
                         if state.router.cooling(e)}
    return data


@app.put("/api/settings")
def put_settings(patch: dict):
    state.settings.update(patch)
    return get_settings()


class KeyTest(BaseModel):
    key: str | None = None


@app.post("/api/providers/{provider}/test")
def test_provider(provider: str, body: KeyTest):
    if provider not in PROVIDERS:
        raise HTTPException(404, "Unknown provider")
    if provider == "local":
        ok = stt.local_available()
        return {"ok": ok, "message": "faster-whisper is installed" if ok else
                "Not installed. Run: pip install faster-whisper"}
    key = (body.key or "").strip() or state.settings.key_for(provider)
    if not key:
        return {"ok": False, "message": "Enter a key first"}
    start = time.perf_counter()
    try:
        message = llm.test_key(provider, key)
    except ProviderError as exc:
        return {"ok": False, "message": str(exc)}
    return {"ok": True, "message": message, "ms": int((time.perf_counter() - start) * 1000)}


# --- voice --------------------------------------------------------------------

@app.post("/api/transcribe")
async def transcribe(audio: UploadFile = File(...)):
    data = await audio.read()
    if not data:
        raise HTTPException(400, "Empty recording")
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "Recording is too long")
    ws = state.workspace
    hints = context.vocabulary(ws.sheets, ws.active) if ws.loaded else []
    language = state.settings.get("language")
    language = None if language == "auto" else language

    def call(engine):
        return stt.transcribe(engine.engine.provider, engine.key, engine.model, data,
                              language, hints, engine.engine.params)

    start = time.perf_counter()
    result = await run_in_threadpool(state.router.run, "voice", call)
    return {"text": result.value, "ms": int((time.perf_counter() - start) * 1000), **result.meta()}


# --- commands -----------------------------------------------------------------

class Command(BaseModel):
    text: str


@app.post("/api/command")
def command(body: Command):
    _require_workbook()
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "Say or type a command")
    return state.runner.run(text[:2000])


@app.post("/api/proposals/{proposal_id}/accept")
def accept(proposal_id: str):
    try:
        state.runner.accept(proposal_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc.args[0])) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return _workbook_response()


@app.post("/api/proposals/{proposal_id}/reject")
def reject(proposal_id: str):
    state.runner.reject(proposal_id)
    return {"ok": True}


# --- workbook -----------------------------------------------------------------

@app.get("/api/workbook")
def workbook():
    return _workbook_response()


@app.post("/api/workbook/sample")
def open_sample():
    state.workspace.open(SAMPLE, copy_into_workspace=True)
    state.runner.workbook_changed()
    return _workbook_response()


class OpenPath(BaseModel):
    path: str


@app.post("/api/workbook/open")
def open_path(body: OpenPath):
    """Open a file in place. Accepted changes are written straight back to it."""
    try:
        state.workspace.open(Path(body.path), copy_into_workspace=False)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - unreadable workbook
        raise HTTPException(400, f"Could not read that file: {exc}") from exc
    state.runner.workbook_changed()
    return _workbook_response()


@app.post("/api/workbook/upload")
async def upload(file: UploadFile = File(...)):
    name = re.sub(r"[^\w.\- ]", "_", Path(file.filename or "workbook.xlsx").name)
    if Path(name).suffix.lower() not in {".xlsx", ".xlsm", ".csv"}:
        raise HTTPException(400, "Upload an .xlsx, .xlsm or .csv file")
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File is larger than 50 MB")
    target = state.workspace.workdir / name
    target.write_bytes(data)
    try:
        state.workspace.open(target, copy_into_workspace=False)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Could not read that file: {exc}") from exc
    state.runner.workbook_changed()
    return _workbook_response()


class ActiveSheet(BaseModel):
    sheet: str


@app.put("/api/workbook/active")
def set_active(body: ActiveSheet):
    try:
        _require_workbook().set_active(body.sheet)
    except KeyError as exc:
        raise HTTPException(404, "No such sheet") from exc
    return _workbook_response()


class CellEdit(BaseModel):
    sheet: str
    row: int
    col: int
    value: str | float | int | bool | None = None


@app.post("/api/workbook/cell")
def edit_cell(body: CellEdit):
    ws = _require_workbook()
    try:
        ws.edit_cell(body.sheet, body.row, body.col, body.value)
    except (KeyError, IndexError) as exc:
        raise HTTPException(400, str(exc)) from exc
    state.runner.workbook_changed()
    return _workbook_response(include_sheet=False)


@app.post("/api/workbook/undo")
def undo():
    if not _require_workbook().undo():
        raise HTTPException(409, "Nothing to undo")
    state.runner.workbook_changed()
    return _workbook_response()


@app.post("/api/workbook/redo")
def redo():
    if not _require_workbook().redo():
        raise HTTPException(409, "Nothing to redo")
    state.runner.workbook_changed()
    return _workbook_response()


@app.get("/api/workbook/download")
def download():
    ws = _require_workbook()
    return FileResponse(ws.path, filename=ws.path.name)


# --- frontend -----------------------------------------------------------------

@app.get("/")
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


app.mount("/static", StaticFiles(directory=STATIC), name="static")
