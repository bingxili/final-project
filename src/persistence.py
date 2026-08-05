"""
Persistence layer: everything a workflow run produces is written to disk
immediately, under a run-specific directory. This is deliberate - see
README.md for the rationale (reproducibility + crash-safety + dissertation
inspection). Nothing important should live only in memory.

Directory layout produced per run:

runs/<task_id>_<timestamp>/
    run_meta.json           # RunMeta, updated/rewritten as the run progresses
    workflow_log.jsonl       # append-only event log, one JSON object per line
    artifacts/
        01_requirements.json
        02_architecture.json
        03_code_v0.json
        04_review_v0.json
        05_test_results_v0.json
        06_code_v1.json       # ... if a revision loop happens
        ...
    generated_project/
        <source files as written by the Developer's latest accepted/final revision>
        dev_tests/<Developer's own self-tests, kept separate for clarity>
        qa_tests/<QA's independent test files, kept separate for clarity>

To compare a specific run's code, manually copy the
run's generated_project/ (or the whole run directory) to wherever you
want it (see evaluation/compare.py --generated-dir).
"""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel

import config
from src.schemas import CodeArtifact, RunMeta, SourceFile, TestResults


def new_run_dir(task_id: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_dir = os.path.join(config.RUNS_DIR, f"{task_id}_{timestamp}")
    os.makedirs(os.path.join(run_dir, "artifacts"), exist_ok=True)
    os.makedirs(os.path.join(run_dir, "generated_project"), exist_ok=True)
    return run_dir


def save_artifact(run_dir: str, filename: str, artifact: BaseModel) -> str:
    """Write a Pydantic artifact as pretty JSON under artifacts/. Returns path."""
    path = os.path.join(run_dir, "artifacts", filename)
    with open(path, "w") as fh:
        fh.write(artifact.model_dump_json(indent=2))
    return path


def save_run_meta(run_dir: str, meta: RunMeta) -> None:
    path = os.path.join(run_dir, "run_meta.json")
    with open(path, "w") as fh:
        fh.write(meta.model_dump_json(indent=2))


def append_log(run_dir: str, event: str, **fields: Any) -> None:
    """Append one structured event line to workflow_log.jsonl."""
    path = os.path.join(run_dir, "workflow_log.jsonl")
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **fields,
    }
    with open(path, "a") as fh:
        fh.write(json.dumps(record) + "\n")


def _write_source_files(base_dir: str, files: list[SourceFile], clean: bool = True) -> None:
    """Write files under base_dir. By default wipes base_dir first so a
    file renamed/removed across revisions doesn't leave a stale copy
    behind (e.g. QA naming a test file differently revision to revision
    previously left both the old and new file on disk side by side)."""
    if clean and os.path.isdir(base_dir):
        shutil.rmtree(base_dir)
    os.makedirs(base_dir, exist_ok=True)
    for f in files:
        path = os.path.join(base_dir, f.path)
        os.makedirs(os.path.dirname(path) or base_dir, exist_ok=True)
        with open(path, "w") as fh:
            fh.write(f.content)


def save_generated_project(run_dir: str, code: CodeArtifact) -> None:
    """
    Overwrite generated_project/ with the given code revision's source
    files. Called after every Developer revision so the latest code is
    always on disk, not just the final one. The directory is wiped first
    (see _write_source_files) - qa_tests/ (written separately by
    save_qa_tests, after Tester runs) and dev_tests/ (written by
    save_dev_tests, right after this call) are intentionally cleared too
    here: a fresh Developer revision hasn't been QA-tested/self-tested
    yet, and leaving a stale qa_tests/ from a previous revision around
    would make it look like it was tested against code that's no longer
    on disk. If the workflow ends before Tester re-runs (e.g. hitting
    MAX_REVISIONS right after a Reviewer rejection), qa_tests/ will
    simply be absent for that final revision - that's the correct,
    unambiguous signal that QA never verified it.
    """
    project_dir = os.path.join(run_dir, "generated_project")
    _write_source_files(project_dir, code.source_files)


def save_dev_tests(run_dir: str, code: CodeArtifact) -> None:
    """Persist the Developer's own self-test files, kept separate from
    QA's independent tests (see dev_tests/ vs qa_tests/) to preserve the
    independence distinction on disk."""
    if not code.self_test_files:
        return
    dev_dir = os.path.join(run_dir, "generated_project", "dev_tests")
    _write_source_files(dev_dir, code.self_test_files)


def save_qa_tests(run_dir: str, test_results: TestResults) -> None:
    """Persist QA's independent black-box test files, kept separate from
    the developer's own tests to preserve the independence distinction.
    Wipes qa_tests/ first so a file QA renamed across revisions doesn't
    leave a stale copy under its old name."""
    qa_dir = os.path.join(run_dir, "generated_project", "qa_tests")
    _write_source_files(qa_dir, test_results.qa_test_files)
