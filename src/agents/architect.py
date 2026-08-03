"""
Architect agent.

Consumes: Requirements artifact.
Produces: Architecture artifact (schemas.Architecture).
"""
from __future__ import annotations

import config
from src.llm_client import call_structured, LLMCallStats
from src.schemas import Architecture, Requirements

SYSTEM_PROMPT = """\
You are a Software Architect. Given structured requirements, produce a
high-level design: overview, modules/files with responsibilities and key
functions/classes, data structures, and brief design notes.

Use the language specified by the requirements (default: Python); prefer
the standard library unless a dependency is clearly justified. Keep the
design proportional to the task.

For every module, fill `public_interfaces` with the EXACT callable
signature (params, types, defaults, return type) of every public
function/method/constructor - QA never sees your source code, so this is
its only contract for calling your design correctly. Convention:
  - Module-level function: `def function_name(args) -> ReturnType`
  - Constructor: `ClassName(args)` (the `__init__` signature, no `self`)
  - Method: `ClassName.method_name(args) -> ReturnType` (dotted prefix
    marks it as a class member, not a free function)

Include a runnable entry point module (e.g. `main.py`) that wires the
other modules together and starts the application - state this in its
`responsibility`. For GUIs, keep any blocking event loop call (e.g.
`root.mainloop()`) only in the entry point, not in a reusable
"build the window" function, so that function stays testable.

Be concise and keep the architecture proportional to the task.
"""


def run(requirements: Requirements, stats: LLMCallStats) -> Architecture:
    user_prompt = (
        "Requirements document (JSON):\n"
        f"{requirements.model_dump_json()}"
    )
    return call_structured(
        SYSTEM_PROMPT, user_prompt, Architecture, stats=stats,
        model=config.ARCHITECT_MODEL, agent_role="architecture",
    )
