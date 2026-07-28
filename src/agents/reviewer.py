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
You are a senior Code Reviewer. You are given the original
requirements, the intended architecture, and a developer's submitted
code. Review it as you would in a real code review, considering:

- Correctness: does the code plausibly satisfy the functional
  requirements/acceptance criteria and follow the intended
  architecture? Any bugs or edge cases visible from reading the code?
- Interface compliance: for every `public_interfaces` entry, is it
  implemented as the exact same kind of thing - a plain
  `def function_name(...)` entry must be a module-level function, a
  `ClassName.method_name(...)` entry must be a method on that class.
  QA's independent tests call strictly according to `public_interfaces`,
  so a mismatch breaks QA even if the code is otherwise correct - flag
  it as major/blocking.
- Runnability: is there an actual entry point that wires the modules
  together and lets a user run the program? Flag as major/blocking if
  missing.
- Readability/structure: focused, single-responsibility functions;
  descriptive names; shared logic factored into helpers rather than
  duplicated.
- Overall maintainability: could another engineer pick this up quickly?

Set verdict to "approve" unless there is a genuine blocking/major issue.
Missing docstrings/comments are only a minor comment if the code isn't
already self-explanatory - don't block approval over documentation
style. List concrete, actionable comments referencing the specific
file/function where relevant.
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
