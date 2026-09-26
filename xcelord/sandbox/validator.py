"""Static checks on model-generated code before it runs.

This is a guard-rail against model mistakes (file writes, shell calls), not a
hard security boundary. The worker process adds a timeout and an empty cwd.
"""

from __future__ import annotations

import ast

ALLOWED_MODULES = {
    "pandas", "numpy", "math", "datetime", "re", "statistics", "collections",
    "itertools", "functools", "string", "random", "decimal", "calendar", "textwrap",
}

BLOCKED_NAMES = {
    "open", "exec", "eval", "compile", "__import__", "globals", "locals", "vars",
    "getattr", "setattr", "delattr", "input", "breakpoint", "exit", "quit", "help",
    "memoryview", "classmethod", "staticmethod", "super", "object",
}

BLOCKED_ATTRS = {
    # file / network I/O on pandas & numpy
    "to_csv", "to_excel", "to_pickle", "to_parquet", "to_sql", "to_json", "to_hdf",
    "to_feather", "to_stata", "to_clipboard", "to_orc", "to_xml", "read_clipboard",
    "load", "save", "savez", "savez_compressed", "savetxt", "loadtxt", "fromfile",
    "tofile", "genfromtxt", "memmap", "ctypeslib", "io", "system", "popen",
}


class UnsafeCode(ValueError):
    pass


def validate(code: str) -> ast.Module:
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as exc:
        raise UnsafeCode(f"Syntax error on line {exc.lineno}: {exc.msg}") from exc

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] not in ALLOWED_MODULES:
                    raise UnsafeCode(f"Import of '{alias.name}' is not allowed")
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] not in ALLOWED_MODULES or node.level:
                raise UnsafeCode(f"Import from '{node.module}' is not allowed")
        elif isinstance(node, ast.Name) and node.id in BLOCKED_NAMES:
            raise UnsafeCode(f"Use of '{node.id}' is not allowed")
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("_"):
                raise UnsafeCode(f"Access to private attribute '{node.attr}' is not allowed")
            if node.attr.startswith("read_") or node.attr in BLOCKED_ATTRS:
                raise UnsafeCode(f"'{node.attr}' does file or system I/O and is not allowed")
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            raise UnsafeCode("global/nonlocal statements are not allowed")
    return tree
