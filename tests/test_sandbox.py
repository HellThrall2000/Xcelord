import pandas as pd
import pytest

from xcelord.sandbox.validator import UnsafeCode, validate


@pytest.mark.parametrize("code", [
    "import os",
    "from subprocess import run",
    "open('x.txt', 'w')",
    "df.to_csv('out.csv')",
    "pd.read_csv('/etc/passwd')",
    "().__class__.__bases__",
    "__import__('os')",
    "getattr(df, 'to_csv')('x')",
])
def test_validator_blocks(code):
    with pytest.raises(UnsafeCode):
        validate(code)


@pytest.mark.parametrize("code", [
    "df['Total'] = df['A'] * 2",
    "import math\nresult = math.sqrt(4)",
    "result = df.groupby('A').sum()",
    "df['D'] = pd.to_datetime(df['D'], errors='coerce').dt.year",
])
def test_validator_allows(code):
    validate(code)


def test_run_modifies_df(sandbox):
    sheets = {"S": pd.DataFrame({"A": [1, 2, 3]})}
    res = sandbox.run("df['B'] = df['A'] * 10", sheets, "S")
    assert res.ok, res.error
    assert list(res.sheets["S"]["B"]) == [10, 20, 30]
    assert "B" not in sheets["S"].columns  # input untouched


def test_run_result_and_print(sandbox):
    res = sandbox.run("print('hi')\nresult = df['A'].sum()", {"S": pd.DataFrame({"A": [1, 2]})}, "S")
    assert res.ok and res.output.strip() == "hi" and res.result == 3


def test_run_new_sheet(sandbox):
    res = sandbox.run("sheets['Summary'] = df.describe()", {"S": pd.DataFrame({"A": [1, 2]})}, "S")
    assert res.ok and "Summary" in res.sheets


def test_run_error_reports_line(sandbox):
    res = sandbox.run("x = 1\ndf['Nope'].sum()", {"S": pd.DataFrame({"A": [1]})}, "S")
    assert not res.ok and "KeyError" in res.error and "line 2" in res.error


def test_runtime_import_blocked(sandbox):
    # Validator allows the string, but the runtime import hook still refuses.
    res = sandbox.run("m = __builtins__['__import__']('os')", {"S": pd.DataFrame()}, "S")
    assert not res.ok


def test_timeout_recovers(sandbox):
    res = sandbox.run("while True:\n    pass", {"S": pd.DataFrame({"A": [1]})}, "S")
    assert not res.ok and "longer than" in res.error
    ok = sandbox.run("result = 1", {"S": pd.DataFrame({"A": [1]})}, "S")
    assert ok.ok and ok.result == 1
