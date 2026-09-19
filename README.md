# Multi-Agent Software Development System

A multi-agent pipeline based on LangGraph framework:

```
Requirements Engineer -> Architect -> Developer -> Reviewer -> Tester
```

The **Orchestrator** is not a separate LLM agent — it is the
LangGraph graph itself (`src/graph.py`): it owns shared state, routes
between agents, tracks `revision_count`, and enforces `max_revisions`
termination.

## Agent responsibilities

| Agent | Input | Output | Notes |
|---|---|---|---|
| Requirements Engineer | user task prompt | `Requirements` (functional/non-functional reqs, acceptance criteria) | |
| Architect | `Requirements` | `Architecture` (modules, responsibilities, design notes) | |
| Developer | `Requirements`, `Architecture`, prior feedback | `CodeArtifact` (source files only) | Implementation only — no self-written tests (kept lean for token budget) |
| Reviewer | `CodeArtifact` | `ReviewFeedback` (approve/revise + comments) | **Static** review only — does not execute code |
| Tester | `Requirements`, `Architecture`, `CodeArtifact` | `TestResults` | Writes **independent, black-box** tests from acceptance criteria only, then executes them |

If Reviewer requests changes, or Tester's independent tests fail, control
returns to the Developer. Each new attempt goes through Reviewer and
Tester again. The loop stops when Tester passes, or when `revision_count`
reaches `MAX_REVISIONS` (workflow status becomes `failed_max_revisions`,
but all partial artifacts/code are still persisted).

## Project structure

```
final_project/
├── config.py                  # model, retry, revision-limit settings (env-overridable)
├── requirements.txt
├── .env.example                # copy to .env
├── src/
│   ├── schemas.py               # Pydantic artifact schemas (Requirements, Architecture,
│   │                             #   CodeArtifact, ReviewFeedback, TestResults, RunMeta)
│   ├── llm_client.py             # Groq wrapper: retry/backoff + structured JSON parsing
│   ├── persistence.py             # run directory creation, artifact/log/code writers
│   ├── graph.py                   # LangGraph StateGraph: nodes + routing + revision limit
│   ├── runner.py                  # CLI entry point
│   ├── test_harness.py            # isolated pytest execution helper for the Developer's
│   │                               #   internal self-test loop (independent of tester.py)
│   └── agents/
│       ├── requirements_engineer.py
│       ├── architect.py
│       ├── developer.py           # generates code + own tests, runs them itself
│       ├── reviewer.py             # static review
│       └── tester.py               # independent black-box QA tests
├── tasks/                      # experiment task prompts (only two dissertation tasks)
│   ├── task_1.txt
│   └── task_2.txt
├── runs/                        # <task_id>_<timestamp>/ output per run (gitignored)
│   └── <run>/
│       ├── run_meta.json          # task, model, status, revision_count, timing
│       ├── workflow_log.jsonl      # append-only event log, one JSON object per line
│       ├── artifacts/               # every intermediate artifact, one JSON file per step/revision
│       └── generated_project/        # actual generated source code
│           ├── dev_tests/               # Developer's own self-tests (internal loop)
│           └── qa_tests/                # QA's independent black-box tests
└── experiment_artefacts/        # final run artefacts used for the dissertation evaluation,
                                  #   uploaded for reference (see experiment_artefacts/README.md)
```

## Maintainability evaluation (multi-agent vs single-prompt baseline)

For the dissertation comparison (does this pipeline improve code
maintainability vs. a single one-shot prompt in a normal AI chat
window?), there are only **two tasks**: `task_1` and `task_2`. An extra
`evaluation/` package is included:

```
evaluation/
├── metrics.py                   # wraps radon: Maintainability Index, Cyclomatic Complexity,
│                                 #   Halstead metrics, raw LOC - per file and aggregated
├── compare.py                    # compares evaluation/data/multi_agent_output/<task>/ vs
│                                 #   evaluation/data/direct_single_assistant_output/<task>/
├── data/
│   ├── multi_agent_output/<task_id>/generated_project/          # final pipeline output per task
│   └── direct_single_assistant_output/<task_id>/generated_project/  # single-prompt baseline per task
└── results/
    ├── <task_id>_comparison.json  # detailed per-file + aggregate metrics for both sides
    └── summary.csv                 # one row per metric per task, appended/updated - easy to load into pandas/Excel
```

Workflow:
1. Run the multi-agent pipeline: `python -m src.runner --task tasks/task_1.txt`
   (creates a fresh `runs/task_1_<timestamp>/`), then copy the resulting
   `generated_project/` into
   `evaluation/data/multi_agent_output/task_1/generated_project/`.
2. Paste the single-prompt baseline's response to the same prompt into
   `evaluation/data/direct_single_assistant_output/task_1/generated_project/`.
3. Compare: `python -m evaluation.compare --task task_1`
   By default this reads both folders above and prints a summary,
   writing/updating `evaluation/results/task_1_comparison.json` and
   `summary.csv`.

If you want to evaluate a different/explicit folder for either side
(e.g. straight out of `runs/`, without copying it into `evaluation/data/`
first), override explicitly:
```bash
python -m evaluation.compare --task task_1 --generated-dir runs/task_1_<timestamp>/generated_project
python -m evaluation.compare --task task_1 --baseline-dir /path/to/baseline_folder
```

See `evaluation/README.md` for full details.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then edit .env and set your LLM key
```

## Running an experiment

```bash
python -m src.runner --task tasks/task_1.txt
python -m src.runner --task tasks/task_2.txt --max-revisions 2
```

Each run creates a fresh directory under `runs/`, e.g.
`runs/task_1_20260808_020000/`, containing everything described above.
`runs/` itself is git-ignored (it accumulates every exploratory run);
the two specific runs actually used for the dissertation's final results
are copied into `experiment_artefacts/` and committed, purely as a
read-only reference for inspection — see `experiment_artefacts/README.md`.

### Developer self-test loop

Independently of the Reviewer/Tester revision loop above, the Developer
can write and run its own quick self-tests before handing off code (see
`src/test_harness.py`), controlled by `DEVELOPER_SELF_TEST_ENABLED`
(default `true`) and `DEVELOPER_SELF_FIX_ATTEMPTS` (default `1`) in
`config.py`/`.env`. This is a fast local sanity check only — it is not a
substitute for QA's independent black-box testing, and the two test
suites are kept on disk separately (`generated_project/dev_tests/` vs
`generated_project/qa_tests/`).

### Model configuration

All agents use `MODEL` (default depends on `LLM_PROVIDER` - see
`config.py`).
Each agent role can optionally be pointed at a different model (e.g. to
save TPM budget on simpler roles) by setting the corresponding env var in
`.env`: `REQUIREMENTS_MODEL`, `ARCHITECT_MODEL`, `DEVELOPER_MODEL`,
`REVIEWER_MODEL`, `TESTER_MODEL`. The model used by each agent is recorded
in `workflow_log.jsonl` for every run.

### Provider configuration

Set `LLM_PROVIDER` in `.env` to `groq` or
`openrouter`. Switching requires no code changes, only the
relevant API key (`GROQ_API_KEY` or `OPENROUTER_API_KEY`) and a model name
valid for that provider's catalogue - see `.env.example`.

## Adding more experiment tasks

The project evaluation currently compares exactly two tasks
(`task_1`, `task_2`); To add another one, create a new `
tasks/task_3.txt` (plain text prompt)
and run:
```bash
python -m src.runner --task tasks/task_3.txt
```