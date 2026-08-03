"""
Reviewer agent.

Consumes: Requirements, Architecture, and CodeArtifact (source files).
Produces: ReviewFeedback artifact (schemas.ReviewFeedback).

Performs a static internal code review (reads code only) - it does
not execute anything itself. Independent dynamic verification is the
Tester/QA agent's job.
"""
from __future__ import annotations

import config
from src.llm_client import call_structured, LLMCallStats
from src.schemas import Architecture, CodeArtifact, ReviewFeedback, Requirements

SYSTEM_PROMPT = """\
You are a senior Code Reviewer. Given the requirements, architecture, and
a developer's submitted code, review it as in a real code review:

- Correctness: does the code satisfy the functional requirements/
  acceptance criteria and follow the architecture? Flag any bugs or edge
  cases visible from reading the code.
- Interface compliance (major/blocking if violated): every
  `public_interfaces` entry must be implemented exactly as specified -
  a plain `def function_name(...)` must be a module-level function, a
  `ClassName.method_name(...)` must be a method on that class. QA's
  independent tests call strictly against `public_interfaces`, so any
  mismatch breaks QA even if the code is otherwise correct.
- Runnability (major/blocking if missing): is there a real entry point
  that wires the modules together and lets a user run the program?
- Readability/maintainability: focused functions, descriptive names,
  shared logic factored out rather than duplicated.

Approve unless there's a genuine blocking/major issue - don't block over
documentation style. List concrete, actionable comments referencing the
specific file/function where relevant.
"""


def run(
    requirements: Requirements,
    architecture: Architecture,
    code: CodeArtifact,
    stats: LLMCallStats,
) -> ReviewFeedback:
    source_dump = "\n\n".join(
        f"--- {f.path} ---\n{f.content}" for f in code.source_files
    )

    user_prompt = (
        "Requirements (JSON):\n"
        f"{requirements.model_dump_json()}\n\n"
        "Architecture (JSON):\n"
        f"{architecture.model_dump_json()}\n\n"
        f"Code revision under review: {code.revision}\n\n"
        f"Source files:\n{source_dump}\n\n"
        f"Set revision_reviewed to {code.revision}."
    )
    return call_structured(
        SYSTEM_PROMPT, user_prompt, ReviewFeedback, stats=stats,
        model=config.REVIEWER_MODEL, agent_role="review",
    )
