"""Compact workbook description for the model prompt.

Kept small on purpose: Groq's free tier allows 8K tokens/minute, and fewer
input tokens also means faster replies.
"""

from __future__ import annotations

import pandas as pd

from .workbook import Sheets, to_json_value

SAMPLE_ROWS = 5
MAX_COLS = 60
MAX_CELL = 40


def _cell(value) -> str:
    text = "" if value is None else str(to_json_value(value))
    return text if len(text) <= MAX_CELL else text[: MAX_CELL - 1] + "…"


def _dtype(s: pd.Series) -> str:
    if pd.api.types.is_bool_dtype(s):
        return "bool"
    if pd.api.types.is_integer_dtype(s):
        return "int"
    if pd.api.types.is_float_dtype(s):
        return "float"
    if pd.api.types.is_datetime64_any_dtype(s):
        return "datetime"
    return "text"


def describe(sheets: Sheets, active: str) -> str:
    lines = []
    others = [n for n in sheets if n != active]
    lines.append(f"Active sheet: {active!r} (available as `df`).")
    if others:
        lines.append("Other sheets (in `sheets` dict): " + ", ".join(
            f"{n!r} {len(sheets[n])}x{len(sheets[n].columns)}" for n in others))

    df = sheets[active]
    lines.append(f"`df` has {len(df)} rows and {len(df.columns)} columns.")
    lines.append("Columns (name: type, nulls, example values):")
    for col in list(df.columns)[:MAX_COLS]:
        s = df[col]
        kind = _dtype(s)
        info = f"- {col!r}: {kind}"
        nulls = int(s.isna().sum())
        if nulls:
            info += f", {nulls} empty"
        if kind == "text":
            uniques = s.dropna().unique()
            if 0 < len(uniques) <= 12:
                info += ", values: " + ", ".join(_cell(v) for v in uniques)
        elif kind in {"int", "float", "datetime"} and s.notna().any():
            info += f", range {_cell(s.min())} → {_cell(s.max())}"
        lines.append(info)
    if len(df.columns) > MAX_COLS:
        lines.append(f"- … and {len(df.columns) - MAX_COLS} more columns")

    if len(df):
        head = df.head(SAMPLE_ROWS)
        cols = list(head.columns)[:MAX_COLS]
        lines.append("First rows:")
        lines.append(" | ".join(str(c) for c in cols))
        for row in head[cols].itertuples(index=False, name=None):
            lines.append(" | ".join(_cell(v) for v in row))
    return "\n".join(lines)


def vocabulary(sheets: Sheets, active: str | None) -> list[str]:
    """Words to bias speech recognition towards: sheet and column names."""
    words: list[str] = []
    for name, df in sheets.items():
        words.append(name)
        if name == active:
            words.extend(str(c) for c in df.columns)
    seen, out = set(), []
    for w in words:
        if w and w not in seen:
            seen.add(w)
            out.append(w)
    return out[:80]
