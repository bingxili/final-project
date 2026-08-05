"""
Standalone pytest-execution harness used ONLY by the Developer agent's
internal self-test loop (agents/developer.py).

Deliberately NOT shared with agents/tester.py: QA's execution path stays
untouched and fully independent of the Developer's - this module is a
separate (small) implementation, not a refactor of the tester's private
helpers.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

import config
from src.schemas import QATestCaseResult, SourceFile

# Same rationale as tester.py's own copy: a self-test that calls a
# blocking GUI event loop or modal dialog (tkinter mainloop/messagebox,
# input()) would hang the subprocess for the full CODE_EXECUTION_TIMEOUT.
# Neutralising these at the harness level is deterministic and doesn't
# depend on model compliance.
GUI_SAFETY_CONFTEST = '''\
import pytest


@pytest.fixture(autouse=True)
def _prevent_gui_blocking(monkeypatch):
    try:
        import tkinter
        from tkinter import messagebox

        for name in ("showinfo", "showwarning", "showerror"):
            monkeypatch.setattr(messagebox, name, lambda *a, **k: "ok", raising=False)
        for name in ("askyesno", "askokcancel", "askretrycancel"):
            monkeypatch.setattr(messagebox, name, lambda *a, **k: True, raising=False)
        monkeypatch.setattr(messagebox, "askquestion", lambda *a, **k: "yes", raising=False)
        monkeypatch.setattr(tkinter.Misc, "mainloop", lambda self, *a, **k: None, raising=False)
    except ImportError:
        pass

    monkeypatch.setattr("builtins.input", lambda *a, **k: "", raising=False)
'''


def parse_junit_xml(xml_path: str) -> list[QATestCaseResult]:
    """Parse a pytest --junit-xml report into per-test outcomes. Returns
    an empty list if the report doesn't exist or can't be parsed (e.g. a
    collection error prevented any XML from being written)."""
    if not os.path.exists(xml_path):
        return []
    try:
        root = ET.parse(xml_path).getroot()
    except ET.ParseError:
        return []

    results = []
    for testcase in root.iter("testcase"):
        classname = testcase.get("classname", "")
        test_name = testcase.get("name", "")
        full_name = f"{classname}::{test_name}" if classname else test_name

        failure = testcase.find("failure")
        error = testcase.find("error")
        skipped = testcase.find("skipped")
        if failure is not None:
            outcome, message = "failed", (failure.get("message") or failure.text or "")
        elif error is not None:
            outcome, message = "error", (error.get("message") or error.text or "")
        elif skipped is not None:
            outcome, message = "skipped", (skipped.get("message") or "")
        else:
            outcome, message = "passed", ""

        results.append(
            QATestCaseResult(
                name=full_name,
                outcome=outcome,
                message=(message or "").strip()[:500],
            )
        )
    return results


def run_pytest(
    source_files: list[SourceFile], test_files: list[SourceFile]
) -> tuple[bool, str, str, "int | None", list[QATestCaseResult]]:
    """Write source + test files to a temp dir and run pytest, parsing a
    JUnit XML report for reliable per-test pass/fail results. Used by the
    Developer's self-test-and-fix loop only (see agents/developer.py)."""
    with tempfile.TemporaryDirectory(prefix="dev_selftest_") as tmp_dir:
        for f in source_files:
            path = os.path.join(tmp_dir, f.path)
            os.makedirs(os.path.dirname(path) or tmp_dir, exist_ok=True)
            with open(path, "w") as fh:
                fh.write(f.content)
        for f in test_files:
            path = os.path.join(tmp_dir, f.path)
            os.makedirs(os.path.dirname(path) or tmp_dir, exist_ok=True)
            with open(path, "w") as fh:
                fh.write(f.content)
        with open(os.path.join(tmp_dir, "conftest.py"), "w") as fh:
            fh.write(GUI_SAFETY_CONFTEST)

        # PYTHONPATH=tmp_dir lets test files import source modules using a
        # dotted path matching their location under the project root.
        env = {**os.environ, "PYTHONPATH": tmp_dir}
        junit_xml_path = os.path.join(tmp_dir, "_selftest_report.xml")
        try:
            result = subprocess.run(
                [
                    sys.executable, "-m", "pytest", "-q", tmp_dir,
                    f"--junit-xml={junit_xml_path}",
                    f"--timeout={config.PER_TEST_TIMEOUT}",
                ],
                cwd=tmp_dir,
                capture_output=True,
                text=True,
                timeout=config.CODE_EXECUTION_TIMEOUT,
                env=env,
            )
            test_case_results = parse_junit_xml(junit_xml_path)
            return (
                result.returncode == 0,
                result.stdout,
                result.stderr,
                result.returncode,
                test_case_results,
            )
        except subprocess.TimeoutExpired as exc:
            test_case_results = parse_junit_xml(junit_xml_path)
            return False, exc.stdout or "", f"Timed out: {exc}", None, test_case_results


def build_summary(
    total_tests: int,
    passed_tests: int,
    test_case_results: list[QATestCaseResult],
) -> str:
    """Code-computed, ground-truth summary from actual pytest results."""
    if total_tests == 0:
        return "No pytest test results were collected (likely a collection error - see stdout)."

    pass_rate = passed_tests / total_tests
    parts = [f"{passed_tests}/{total_tests} tests passed ({pass_rate:.0%})."]
    failing_names = [
        r.name for r in test_case_results if r.outcome in ("failed", "error")
    ]
    if failing_names:
        parts.append("Failing: " + ", ".join(failing_names) + ".")
    return " ".join(parts)
