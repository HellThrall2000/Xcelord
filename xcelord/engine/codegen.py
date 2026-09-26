"""Request → generated code → sandbox run → proposal (not yet applied)."""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field

import pandas as pd

from ..excel import context
from ..excel.workbook import Sheets, Workspace, diff_workbook, sheet_payload, to_json_value
from ..providers import llm
from ..sandbox.worker import Sandbox
from . import prompts
from .router import ChainResult, ResolvedEngine, Router

_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)
_FENCE = re.compile(r"```(?:python|py|json)?\s*(.*?)```", re.S | re.I)


def parse_reply(text: str) -> tuple[str, str]:
    """Return (explanation, code) from a model reply, tolerating messy formats."""
    text = _THINK.sub("", text).strip()
    candidates = [text]
    candidates += [m.group(1).strip() for m in _FENCE.finditer(text)]
    decoder = json.JSONDecoder()
    for candidate in candidates:
        for start in [i for i, ch in enumerate(candidate) if ch == "{"][:20]:
            try:
                obj, _ = decoder.raw_decode(candidate[start:])
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and ("code" in obj or "explanation" in obj):
                return str(obj.get("explanation") or "").strip(), str(obj.get("code") or "").strip()
    fences = [m.group(1).strip() for m in _FENCE.finditer(text)]
    if fences:
        return "", fences[0]
    return "", text


def result_payload(result) -> dict | None:
    if result is None:
        return None
    if isinstance(result, pd.Series):
        name = str(result.name) if result.name is not None else "value"
        frame = result.reset_index()
        frame.columns = [str(c) if c != 0 else name for c in frame.columns]
        result = frame
    if isinstance(result, pd.DataFrame):
        if not isinstance(result.index, pd.RangeIndex):
            result = result.reset_index()
        payload = sheet_payload(result.head(200))
        payload["total_rows"] = len(result)
        return {"type": "table", **payload}
    return {"type": "value", "value": to_json_value(result) if not isinstance(result, (list, dict, tuple)) else str(result)}


@dataclass
class Proposal:
    id: str
    request: str
    explanation: str
    code: str
    sheets: Sheets | None
    active: str | None
    base_version: int
    diff: dict = field(default_factory=dict)


class CommandRunner:
    def __init__(self, router: Router, sandbox: Sandbox, workspace: Workspace):
        self.router = router
        self.sandbox = sandbox
        self.workspace = workspace
        self.pending: dict[str, Proposal] = {}
        self.history: list[dict] = []
        self.version = 0  # bumps on every workbook change, invalidating stale proposals

    def run(self, request: str) -> dict:
        ws = self.workspace
        with ws.lock:
            sheets = ws.snapshot()
            active = ws.active
            base_version = self.version
        ctx = context.describe(sheets, active)
        messages = [
            {"role": "system", "content": prompts.SYSTEM_PROMPT},
            {"role": "user", "content": prompts.user_message(ctx, request, self.history)},
        ]

        started = time.perf_counter()
        chain: ChainResult = self.router.run(
            "code", lambda e: self._ask(e, messages))
        reply = chain.value
        explanation, code = parse_reply(reply)
        repaired = False
        run = self.sandbox.run(code, sheets, active) if code else None

        if run is not None and not run.ok and self.router.settings.get("self_heal"):
            messages += [
                {"role": "assistant", "content": reply},
                {"role": "user", "content": prompts.repair_message(code, run.error)},
            ]
            try:
                fix = self.router.run("code", lambda e: self._ask(e, messages))
            except Exception:  # noqa: BLE001 - keep the original error for the user
                fix = None
            if fix is not None:
                chain.attempts.extend(fix.attempts)
                chain.engine = fix.engine
                new_expl, new_code = parse_reply(fix.value)
                if new_code:
                    retry = self.sandbox.run(new_code, sheets, active)
                    explanation, code, run, repaired = new_expl or explanation, new_code, retry, True

        total_ms = int((time.perf_counter() - started) * 1000)
        response = {
            "request": request,
            "explanation": explanation,
            "code": code,
            "repaired": repaired,
            "ms": total_ms,
            **chain.meta(),
        }
        self.history.append({"request": request, "explanation": explanation})
        del self.history[:-8]

        if run is None:
            response.update(status="clarify", output="", result=None)
            return response
        if not run.ok:
            response.update(status="error", error=run.error, output=run.output, result=None)
            return response

        diff = diff_workbook(sheets, run.sheets)
        changed = any(d["status"] != "unchanged" for d in diff.values()) or list(sheets) != list(run.sheets)
        response.update(output=run.output.strip(), result=result_payload(run.result))
        if not changed:
            response["status"] = "answer"
            return response

        proposal = Proposal(uuid.uuid4().hex[:12], request, explanation, code, run.sheets,
                            run.active, base_version, diff)
        self.pending.clear()  # only the latest proposal is actionable
        self.pending[proposal.id] = proposal
        preview_sheet = run.active if diff.get(run.active, {}).get("status") != "unchanged" else next(
            (n for n, d in diff.items() if d["status"] in ("modified", "added")), run.active)
        response.update(
            status="proposal",
            proposal_id=proposal.id,
            diff={n: {k: v for k, v in d.items() if k != "cells"} for n, d in diff.items()},
            preview={"sheet": preview_sheet, "cells": diff.get(preview_sheet, {}).get("cells", []),
                     "data": sheet_payload(run.sheets[preview_sheet])} if preview_sheet in run.sheets else None,
        )
        return response

    def _ask(self, engine: ResolvedEngine, messages: list[dict]) -> str:
        return llm.chat(engine.engine.provider, engine.key, engine.model, messages, engine.engine.params)

    def accept(self, proposal_id: str) -> None:
        proposal = self.pending.pop(proposal_id, None)
        if proposal is None:
            raise KeyError("This preview has expired. Run the command again.")
        if proposal.base_version != self.version:
            raise RuntimeError("The workbook changed since this preview was made. Run the command again.")
        self.workspace.commit(proposal.sheets, proposal.active)
        self.version += 1

    def reject(self, proposal_id: str) -> None:
        self.pending.pop(proposal_id, None)

    def workbook_changed(self) -> None:
        self.version += 1
        self.pending.clear()
