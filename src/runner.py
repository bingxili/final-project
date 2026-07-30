"""
CLI entry point: run the full multi-agent workflow on a single task
prompt and persist all artifacts/generated code/logs under runs/.

Usage:
    python -m src.runner --task tasks/task_1.txt
    python -m src.runner --task tasks/task_1.txt --max-revisions 2
"""
from __future__ import annotations

import argparse
import os
import sys
import traceback
from datetime import datetime, timezone

import config
from src import persistence
from src.graph import build_graph
from src.llm_client import LLMCallStats, set_current_run_dir
from src.schemas import RunMeta, WorkflowStatus


def load_task_prompt(task_path: str) -> str:
    with open(task_path, "r") as fh:
        return fh.read().strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the multi-agent dev workflow.")
    parser.add_argument("--task", required=True, help="Path to a task prompt .txt file")
    parser.add_argument(
        "--max-revisions",
        type=int,
        default=config.MAX_REVISIONS,
        help="Override max revision loops (default from config.py)",
    )
    args = parser.parse_args()

    task_id = os.path.splitext(os.path.basename(args.task))[0]
    task_prompt = load_task_prompt(args.task)

    run_dir = persistence.new_run_dir(task_id)
    set_current_run_dir(run_dir)
    stats = LLMCallStats()

    meta = RunMeta(
        task_id=task_id,
        task_prompt=task_prompt,
        model=config.LLM_MODEL,
        started_at=datetime.now(timezone.utc).isoformat(),
        max_revisions=args.max_revisions,
    )
    persistence.save_run_meta(run_dir, meta)
    persistence.append_log(run_dir, "run_started", task_id=task_id)

    initial_state = {
        "task_id": task_id,
        "task_prompt": task_prompt,
        "run_dir": run_dir,
        "stats": stats,
        "revision_count": 0,
        "max_revisions": args.max_revisions,
        "review_feedback": None,
        "test_results": None,
    }

    print(f"[runner] Starting run for task '{task_id}' -> {run_dir}")

    graph = build_graph()
    final_status = WorkflowStatus.ERROR
    error_message = None
    final_state: dict = {}

    try:
        # recursion_limit guards against unexpected infinite loops in the
        # graph; generous enough for max_revisions loops x nodes per loop.
        final_state = graph.invoke(
            initial_state, config={"recursion_limit": 50 + args.max_revisions * 10}
        )
        final_status = WorkflowStatus(final_state.get("status", WorkflowStatus.ERROR.value))
    except Exception as exc:  # noqa: BLE001
        error_message = f"{exc}\n{traceback.format_exc()}"
        persistence.append_log(run_dir, "run_error", error=str(exc))
        print(f"[runner] ERROR: {exc}", file=sys.stderr)

    meta.finished_at = datetime.now(timezone.utc).isoformat()
    meta.status = final_status
    meta.revision_count = final_state.get("revision_count", 0)
    meta.total_llm_calls = stats.total_calls
    meta.total_prompt_tokens = stats.total_prompt_tokens
    meta.total_completion_tokens = stats.total_completion_tokens
    meta.total_tokens = stats.total_tokens
    meta.error = error_message
    persistence.save_run_meta(run_dir, meta)
    persistence.append_log(run_dir, "run_finished", status=final_status.value)

    print(f"[runner] Finished with status: {final_status.value}")
    print(f"[runner] Artifacts written to: {run_dir}")
    print(
        f"[runner] LLM calls: {stats.total_calls}, "
        f"tokens used: {stats.total_tokens} "
        f"(prompt={stats.total_prompt_tokens}, completion={stats.total_completion_tokens})"
    )
    return 0 if final_status == WorkflowStatus.PASSED else 1


if __name__ == "__main__":
    raise SystemExit(main())
