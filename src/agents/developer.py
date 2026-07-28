"""
Developer agent.

Consumes: Requirements, Architecture, optional prior CodeArtifact +
ReviewFeedback/TestResults (when revising).
Produces: CodeArtifact - source files implementing the design.

Note: the Developer does not write or run its own tests - independent
QA/Tester black-box tests in agents/tester.py are the only test suite
exercised against this code. This keeps QA fully independent and keeps
the Developer's response small (fewer tokens spent per call, which
matters a lot under a tight tokens-per-minute budget).
"""
from __future__ import annotations

from typing import Optional

import config
from src.llm_client import call_developer_code, LLMCallStats
from src.schemas import (
    Architecture,
    CodeArtifact,
    ReviewFeedback,
    Requirements,
    TestResults,
)

SYSTEM_PROMPT = """\
You are a Software Developer. Given requirements and an architecture,
implement the code in the language chosen by the architecture.

Rules:
- Follow the architecture's language/dependency choices; stick to the
  standard library unless it specifies otherwise.
- The architecture's `public_interfaces` entries are exact contracts -
  implement every one with EXACTLY that signature. QA's independent
  tests are written against those signatures without seeing your code,
  so any deviation causes spurious test failures. Respect the
  function-vs-method distinction exactly: `def function_name(args)` (no
  class prefix) MUST be a module-level function; `ClassName.method_name(args)`
  MUST be a method on that class - do not turn one into the other.
- Source file paths are relative to the project root (e.g.
  "calculator.py", or "models/user.py" for subdirectories) - one
  project root, no extra top-level package prefix.
- If given previous review comments and/or QA test failures, fix those
  specific issues and briefly note in notes_for_reviewer what changed.
- On a revision, only include files you added or changed - unchanged
  files are carried over automatically. There is no way to delete a
  file this way - if one must be removed, say so in notes_for_reviewer.
- Implement every piece of functionality fully; the generated project
  MUST be runnable end-to-end.
"""


def _build_user_prompt(
    requirements: Requirements,
    architecture: Architecture,
    previous_code: Optional[CodeArtifact],
    review_feedback: Optional[ReviewFeedback],
    test_results: Optional[TestResults],
    next_revision: int,
) -> str:
    parts = [
        "Requirements (JSON):",
        requirements.model_dump_json(),
        "",
        "Architecture (JSON):",
        architecture.model_dump_json(),
        "",
        f"This is revision {next_revision} of the code "
        f"({'first attempt' if next_revision == 0 else 'a revision'}).",
    ]

    if previous_code is not None:
        prev_src = "\n\n".join(
            f"--- {f.path} ---\n{f.content}" for f in previous_code.source_files
        )
        parts += ["", "Previous source code submitted:", prev_src]

    if review_feedback is not None:
        comments = "\n".join(
            f"- [{c.severity}] {c.file or ''}: {c.comment}"
            for c in review_feedback.comments
        )
        parts += [
            "",
            f"Previous Reviewer verdict: {review_feedback.verdict.value}",
            "Reviewer comments to address:",
            comments or "(none)",
        ]

    if test_results is not None and not test_results.passed:
        parts += [
            "",
            "Previous independent QA test run FAILED. QA summary:",
            test_results.summary,
            "QA stdout:",
            test_results.stdout,
            "QA stderr:",
            test_results.stderr,
            "(Note: you cannot see QA's actual test file contents by design - "
            "fix the underlying bug based on the failure output and requirements.)",
        ]

    parts += [
        "",
        f"Set revision to {next_revision} in your response.",
    ]
    return "\n".join(parts)


def run(
    requirements: Requirements,
    architecture: Architecture,
    stats: LLMCallStats,
    previous_code: Optional[CodeArtifact] = None,
    review_feedback: Optional[ReviewFeedback] = None,
    test_results: Optional[TestResults] = None,
) -> CodeArtifact:
    next_revision = 0 if previous_code is None else previous_code.revision + 1

    user_prompt = _build_user_prompt(
        requirements,
        architecture,
        previous_code,
        review_feedback,
        test_results,
        next_revision,
    )
    code = call_developer_code(
        SYSTEM_PROMPT, user_prompt, CodeArtifact, stats=stats,
        model=config.DEVELOPER_MODEL, agent_role="developer",
    )
    code.revision = next_revision  # enforce, don't trust the model

    # The Developer is only asked to return files it added/changed this
    # revision (see the prompt's token-saving rationale in the module
    # docstring) - it must NOT be treated as re-emitting the full project
    # every time. So merge onto the previous revision's file set here:
    # new/changed paths overwrite the old content, untouched paths are
    # carried forward unchanged. Without this, any file the model omits
    # (because it considers it "unchanged") would silently disappear from
    # CodeArtifact.source_files, breaking QA/Reviewer which only see this
    # artifact's files (a real bug seen in practice: revision 2 returned
    # only new test files and dropped ai.py/game_logic.py/gui.py/main.py,
    # causing QA's pytest run to fail with ModuleNotFoundError).
    if previous_code is not None:
        merged = {f.path: f for f in previous_code.source_files}
        for f in code.source_files:
            merged[f.path] = f
        code.source_files = list(merged.values())

    return code
