"""
Tester / QA agent.

Consumes: Requirements (acceptance criteria), Architecture (module/function
names AND exact public_interfaces signatures to call), and CodeArtifact
(source file names only - contents and Developer's own test files are
deliberately withheld to keep QA independent).
Produces: TestResults artifact (schemas.TestResults).

Independent testing: QA never sees the Developer's own unit
tests. It writes fresh test cases derived only from the Requirements
(acceptance criteria) and the Architecture (module/function names plus
exact call signatures via public_interfaces), then executes them (via
pytest) against the generated source code.

Scope note: QA is deliberately limited to pytest-based unit/functional
tests of individual functions/classes. An earlier version also tried to
launch the project's entry point (e.g. main.py) as a subprocess as a
"smoke test", but that added a lot of fragile complexity (ambiguous
timeout-vs-crash handling for GUI apps, subprocess plumbing) for
relatively little benefit in a thesis-scoped project - it was removed.
Runnability (does the project have a working entry point) is instead
checked by the Reviewer as a code-review criterion, not executed here.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

import config
from src.llm_client import call_tester_code, LLMCallStats
from src.schemas import (
    Architecture,
    CodeArtifact,
    QATestCaseResult,
    QATestPartial,
    Requirements,
    TestResults,
)

SYSTEM_PROMPT = """\
You are an independent QA / Test Engineer.

Design black-box tests using only the requirements, acceptance criteria,
and the architecture's `public_interfaces`. Do not rely on the
Developer's own tests or implementation details.

Treat every `public_interfaces` entry as an exact API contract. Do not
guess function/class names, parameters, return values, or whether an
interface is a module-level function or class method.

Write test files that import the generated modules using their project
paths and verify the observable behaviour required by the acceptance
criteria.

Return:
- the designed QA test cases, including an id, description, and covered
  acceptance criteria;
- the corresponding test file contents.

Do not return or rewrite the application source files.

Avoid tests that block waiting for user interaction, including GUI event
loops, terminal input, or modal dialogs. Where interactive behaviour must
be exercised, mock the blocking interaction or skip direct execution and
explain why.
"""


def _build_user_prompt(
    requirements: Requirements, architecture: Architecture, code: CodeArtifact
) -> str:
    file_list = "\n".join(f"- {f.path}" for f in code.source_files)
    return (
        "Requirements (JSON):\n"
        f"{requirements.model_dump_json()}\n\n"
        "Architecture (JSON):\n"
        f"{architecture.model_dump_json()}\n\n"
        "Generated source file names available for import (contents withheld "
        "deliberately - test only via public interfaces):\n"
        f"{file_list}"
    )


def _parse_junit_xml(xml_path: str) -> list[QATestCaseResult]:
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


# Auto-injected into every QA run as conftest.py. The Tester's system
# prompt tells the model not to call blocking GUI event loops/dialogs
# directly, but LLMs don't reliably follow that instruction (observed in
# practice: a test called a helper that internally opened a
# tkinter.messagebox dialog and hung the whole pytest process for the
# full CODE_EXECUTION_TIMEOUT, discarding every test's results even
# though pytest-timeout's per-test timeout was set - signal-based
# timeouts don't reliably interrupt a blocking native GUI wait loop).
# Neutralising these calls at the harness level is a deterministic fix
# that doesn't depend on model compliance.
_GUI_SAFETY_CONFTEST = '''\
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


def _execute_tests(
    source_files, qa_test_files
) -> tuple[bool, str, str, int | None, list[QATestCaseResult]]:
    """Write source + QA test files to a temp dir and run pytest, parsing
    a JUnit XML report for reliable per-test pass/fail results (parsing
    pytest's human-readable stdout would be brittle by comparison)."""
    with tempfile.TemporaryDirectory(prefix="qa_run_") as tmp_dir:
        for f in source_files:
            path = os.path.join(tmp_dir, f.path)
            os.makedirs(os.path.dirname(path) or tmp_dir, exist_ok=True)
            with open(path, "w") as fh:
                fh.write(f.content)
        for f in qa_test_files:
            path = os.path.join(tmp_dir, f.path)
            os.makedirs(os.path.dirname(path) or tmp_dir, exist_ok=True)
            with open(path, "w") as fh:
                fh.write(f.content)
        with open(os.path.join(tmp_dir, "conftest.py"), "w") as fh:
            fh.write(_GUI_SAFETY_CONFTEST)

        # PYTHONPATH=tmp_dir lets test files import source modules using a
        # dotted path matching their location under the project root (see
        # developer._run_self_tests for the same rationale).
        env = {**os.environ, "PYTHONPATH": tmp_dir}
        junit_xml_path = os.path.join(tmp_dir, "_qa_report.xml")
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
            test_case_results = _parse_junit_xml(junit_xml_path)
            return (
                result.returncode == 0,
                result.stdout,
                result.stderr,
                result.returncode,
                test_case_results,
            )
        except subprocess.TimeoutExpired as exc:
            test_case_results = _parse_junit_xml(junit_xml_path)
            return False, exc.stdout or "", f"Timed out: {exc}", None, test_case_results


def _build_ground_truth_summary(
    total_tests: int,
    passed_tests: int,
    failed_tests: int,
    test_case_results: list[QATestCaseResult],
) -> str:
    """Build a summary string from actual, code-verified results only -
    never from the model's own (sometimes hallucinated) account. See
    TestResults.summary vs TestResults.qa_summary."""
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


def run(
    requirements: Requirements,
    architecture: Architecture,
    code: CodeArtifact,
    stats: LLMCallStats,
) -> TestResults:
    user_prompt = _build_user_prompt(requirements, architecture, code)
    partial = call_tester_code(
        SYSTEM_PROMPT, user_prompt, QATestPartial, stats=stats,
        model=config.TESTER_MODEL, agent_role="test_result",
    )

    passed, stdout, stderr, return_code, test_case_results = _execute_tests(
        code.source_files, partial.qa_test_files
    )

    total_tests = len(test_case_results)
    passed_tests = sum(1 for r in test_case_results if r.outcome == "passed")
    failed_tests = sum(1 for r in test_case_results if r.outcome in ("failed", "error"))
    pass_rate = (passed_tests / total_tests) if total_tests else 0.0

    summary = _build_ground_truth_summary(
        total_tests, passed_tests, failed_tests, test_case_results
    )

    return TestResults(
        revision_tested=code.revision,
        qa_test_cases=partial.qa_test_cases,
        qa_test_files=partial.qa_test_files,
        executed=True,
        passed=passed,
        stdout=stdout,
        stderr=stderr,
        return_code=return_code,
        total_tests=total_tests,
        passed_tests=passed_tests,
        failed_tests=failed_tests,
        pass_rate=pass_rate,
        test_case_results=test_case_results,
        qa_summary=partial.summary,
        summary=summary,
    )
