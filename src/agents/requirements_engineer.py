"""
Requirements Engineer agent.

Consumes: raw user task prompt (string).
Produces: Requirements artifact (schemas.Requirements).
"""
from __future__ import annotations

import config
from src.llm_client import call_structured, LLMCallStats
from src.schemas import Requirements

SYSTEM_PROMPT = """\
You are an experienced Requirements Engineer. Given a user's task
description, produce a structured requirements specification.

Describe what the system must do from a user-facing, behavioural point
of view (observable inputs/outputs/behaviour) - leave function/class/file
names and module structure to the Architect and Developer.

Each acceptance criterion should describe a concrete scenario (inputs +
expected observable outcome), clear enough that an independent tester
could turn it directly into a black-box test case without seeing code.

Also include: a short project summary, genuinely applicable non-
functional requirements, and any assumptions/out-of-scope items needed
to resolve ambiguity. Be concise but complete.
"""


def run(task_prompt: str, stats: LLMCallStats) -> Requirements:
    user_prompt = f"User task:\n\"\"\"\n{task_prompt}\n\"\"\""
    return call_structured(
        SYSTEM_PROMPT, user_prompt, Requirements, stats=stats,
        model=config.REQUIREMENTS_MODEL, agent_role="requirements",
    )
