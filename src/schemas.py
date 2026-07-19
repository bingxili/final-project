"""
Structured intermediate artifact schemas exchanged between agents.

Every agent node in the LangGraph workflow consumes/produces one (or more)
of these Pydantic models:
  1. Validation - malformed LLM JSON output is caught early and can
     trigger a repair retry (see llm_client.call_structured).
  2. Persistence - every model has .model_dump_json() so it can be
     written verbatim to disk as an inspectable artifact.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------
# 1. Requirements Engineer output
# --------------------------------------------------------------------------
class FunctionalRequirement(BaseModel):
    id: str = Field(description="Short identifier, e.g. FR-1")
    description: str


class AcceptanceCriterion(BaseModel):
    id: str = Field(description="Short identifier, e.g. AC-1")
    description: str
    related_requirement_ids: List[str] = Field(default_factory=list)


class Requirements(BaseModel):
    project_summary: str
    functional_requirements: List[FunctionalRequirement]
    non_functional_requirements: List[str] = Field(default_factory=list)
    acceptance_criteria: List[AcceptanceCriterion]
    assumptions: List[str] = Field(default_factory=list)
    out_of_scope: List[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# 2. Architect output
# --------------------------------------------------------------------------
class ModuleSpec(BaseModel):
    name: str = Field(description="e.g. 'calculator.py' or 'core module'")
    responsibility: str
    key_functions_or_classes: List[str] = Field(default_factory=list)
    public_interfaces: List[str] = Field(
        default_factory=list,
        description=(
            "Exact, importable public signatures a caller needs - not just "
            "names. One entry per public function/method/constructor, e.g. "
            "'def add(a: float, b: float) -> float', "
            "'class Game:  def __init__(self, board_size: int = 15) -> None', "
            "'def check_winner(board: list[list[str]]) -> Optional[str]'. "
            "This is the only place QA (which never sees the source code) "
            "learns exact parameter names/types/defaults, so it must be "
            "precise enough to call correctly without guessing."
        ),
    )


class Architecture(BaseModel):
    overview: str = Field(description="High-level description of the design/approach")
    language: str = Field(default="python")
    modules: List[ModuleSpec]
    data_structures: List[str] = Field(default_factory=list)
    design_notes: List[str] = Field(
        default_factory=list, description="Key decisions, tradeoffs, patterns used"
    )


# --------------------------------------------------------------------------
# 3. Developer output
# --------------------------------------------------------------------------
class SourceFile(BaseModel):
    path: str = Field(description="Relative path within generated_project/, e.g. 'calculator.py'")
    content: str


class CodeArtifact(BaseModel):
    revision: int = Field(description="0 = first attempt, increments per Developer revision")
    summary: str = Field(description="Short description of what was implemented/changed")
    source_files: List[SourceFile]
    notes_for_reviewer: List[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# 4. Reviewer output
# --------------------------------------------------------------------------
class ReviewVerdict(str, Enum):
    APPROVE = "approve"
    REVISE = "revise"


class ReviewComment(BaseModel):
    severity: str = Field(description="one of: minor, major, blocking")
    file: Optional[str] = None
    comment: str


class ReviewFeedback(BaseModel):
    revision_reviewed: int
    verdict: ReviewVerdict
    comments: List[ReviewComment] = Field(default_factory=list)
    summary: str


# --------------------------------------------------------------------------
# 5. Tester / QA output (independent, black-box testing)
# --------------------------------------------------------------------------
class QATestCase(BaseModel):
    id: str = Field(description="e.g. QA-1")
    description: str
    related_acceptance_criteria: List[str] = Field(default_factory=list)


class QATestPartial(BaseModel):
    """What the Tester LLM call actually produces - test cases, the raw
    test file contents, and a summary. The execution-outcome fields
    (executed/passed/stdout/stderr/return_code, per-test results, pass
    rate) are filled in afterwards by tester.py from actually running
    pytest, not by the model, so they live only on the full TestResults
    below."""

    qa_test_cases: List[QATestCase]
    qa_test_files: List[SourceFile] = Field(
        description="Independent black-box test files written by QA, "
        "separate from the Developer's own unit tests"
    )
    summary: str


class QATestCaseResult(BaseModel):
    """Actual pytest outcome for one test function, parsed from a JUnit
    XML report - not written by the model, so this is ground truth,
    unlike QATestPartial.summary."""

    name: str = Field(
        description="e.g. 'tests/test_game.py::TestGame::test_reset_game'"
    )
    outcome: str = Field(description="one of: passed, failed, error, skipped")
    message: str = Field(
        default="", description="Short failure/error message, empty if passed."
    )


class TestResults(BaseModel):
    revision_tested: int
    qa_test_cases: List[QATestCase]
    qa_test_files: List[SourceFile] = Field(
        description="Independent black-box test files written by QA, "
        "separate from the Developer's own unit tests"
    )
    executed: bool
    passed: bool
    stdout: str = ""
    stderr: str = ""
    return_code: Optional[int] = None
    total_tests: int = 0
    passed_tests: int = 0
    failed_tests: int = 0
    pass_rate: float = Field(
        default=0.0, description="passed_tests / total_tests, 0.0 if no tests ran"
    )
    test_case_results: List[QATestCaseResult] = Field(
        default_factory=list,
        description="Per-test pytest outcome, parsed from a JUnit XML "
        "report - ground truth, independent of the model's own summary.",
    )
    qa_summary: str = Field(
        default="",
        description="The Tester LLM's own (unverified, sometimes "
        "inaccurate/hallucinated) natural-language summary, written "
        "before tests were actually executed. Kept for reference only - "
        "see `summary` for the code-computed, ground-truth summary.",
    )
    summary: str = Field(
        description="Code-computed, ground-truth summary built from the "
        "actual pytest results (pass rate, failing test names) - NOT "
        "written by the model. See `qa_summary` for the model's own "
        "(unverified) account."
    )


# --------------------------------------------------------------------------
# 6. Overall workflow status / shared state summary (persisted as run_meta)
# --------------------------------------------------------------------------
class WorkflowStatus(str, Enum):
    RUNNING = "running"
    PASSED = "passed"
    FAILED_MAX_REVISIONS = "failed_max_revisions"
    ERROR = "error"


class RunMeta(BaseModel):
    task_id: str
    task_prompt: str
    model: str
    started_at: str
    finished_at: Optional[str] = None
    status: WorkflowStatus = WorkflowStatus.RUNNING
    revision_count: int = 0
    max_revisions: int
    total_llm_calls: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int = 0
    error: Optional[str] = None
