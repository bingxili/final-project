"""
Compare maintainability metrics between:
  (a) the multi-agent system's generated code for a task
      (evaluation/multi_agent_output/<task_id>/generated_project/), and
  (b) a single-prompt baseline for the same task
      (evaluation/direct_single_assistant_output/<task_id>/generated_project/).

By default, both (a) and (b) resolve to these fixed evaluation/ folders,
so you first copy the final chosen version of each task's code there
(see evaluation/direct_single_assistant_output/README.md for the
baseline convention; for the multi-agent side, copy the
generated_project/ folder from whichever runs/<task_id>_<timestamp>/
you want to use as the final result for that task). Pass
--generated-dir/--baseline-dir explicitly to override either side.

Usage:
    python -m evaluation.compare --task task_1
    python -m evaluation.compare --task task_1 --generated-dir /path/to/final_code_folder
    python -m evaluation.compare --task task_1 --baseline-dir /path/to/baseline_folder

Writes:
    evaluation/results/<task_id>_comparison.json   (detailed, per-file + aggregate)
    evaluation/results/summary.csv                  (one row per task, appended/updated)
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from datetime import datetime, timezone

import config
from evaluation.metrics import analyze_project

EVALUATION_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(EVALUATION_DIR)
RESULTS_DIR = os.path.join(EVALUATION_DIR, "results")
SUMMARY_CSV = os.path.join(RESULTS_DIR, "summary.csv")
MULTI_AGENT_OUTPUT_DIR = os.path.join(EVALUATION_DIR, "data", "multi_agent_output")
BASELINE_OUTPUT_DIR = os.path.join(EVALUATION_DIR, "data", "direct_single_assistant_output")

CSV_FIELDS = [
    "task_id",
    "compared_at",
    "multi_agent_dir",
    "multi_agent_mi",
    "multi_agent_avg_cc",
    "multi_agent_max_cc",
    "multi_agent_sloc",
    "multi_agent_duplication_pct",
    "baseline_dir",
    "baseline_mi",
    "baseline_avg_cc",
    "baseline_max_cc",
    "baseline_sloc",
    "baseline_duplication_pct",
    "mi_difference_multi_agent_minus_baseline",
    "duplication_pct_difference_multi_agent_minus_baseline",
]


def _resolve_multi_agent_dir(task_id: str, generated_dir_override: str | None) -> str:
    if generated_dir_override:
        return generated_dir_override
    generated_project = os.path.join(MULTI_AGENT_OUTPUT_DIR, task_id, "generated_project")
    if not os.path.isdir(generated_project):
        raise FileNotFoundError(
            f"No generated code found at {generated_project}. Copy the final "
            f"generated_project/ folder for this task there (e.g. from "
            f"runs/{task_id}_<timestamp>/generated_project/), or pass "
            "--generated-dir explicitly."
        )
    return generated_project


def _resolve_baseline_dir(task_id: str, baseline_dir_override: str | None) -> str:
    if baseline_dir_override:
        return baseline_dir_override
    return os.path.join(BASELINE_OUTPUT_DIR, task_id, "generated_project")


def _relpath(path: str) -> str:
    """Shorten an absolute path to be relative to the repo root, for readability."""
    try:
        return os.path.relpath(path, REPO_ROOT)
    except ValueError:
        return path


def _append_summary_row(row: dict) -> None:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    file_exists = os.path.isfile(SUMMARY_CSV)
    existing_rows = []
    if file_exists:
        with open(SUMMARY_CSV, "r", newline="") as fh:
            # restval/reader handles rows from older/newer schema versions without
            # misaligning columns; drop any row for the task we're about to rewrite.
            for r in csv.DictReader(fh):
                if r.get("task_id") == row["task_id"]:
                    continue
                existing_rows.append({field: r.get(field, "") for field in CSV_FIELDS})
    existing_rows.append(row)
    with open(SUMMARY_CSV, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(existing_rows)


def compare(
    task_id: str,
    generated_dir_override: str | None = None,
    baseline_dir_override: str | None = None,
) -> dict:
    multi_agent_dir = _resolve_multi_agent_dir(task_id, generated_dir_override)
    baseline_dir = _resolve_baseline_dir(task_id, baseline_dir_override)

    multi_agent_metrics = analyze_project(multi_agent_dir)
    baseline_metrics = analyze_project(baseline_dir)

    multi_summary = multi_agent_metrics.summary()
    baseline_summary = baseline_metrics.summary()

    report = {
        "task_id": task_id,
        "compared_at": datetime.now(timezone.utc).isoformat(),
        "multi_agent": {
            "root_dir": multi_agent_dir,
            "files": [f.__dict__ for f in multi_agent_metrics.files],
            "summary": multi_summary,
        },
        "baseline_single_prompt": {
            "root_dir": baseline_dir,
            "files": [f.__dict__ for f in baseline_metrics.files],
            "summary": baseline_summary,
        },
    }

    os.makedirs(RESULTS_DIR, exist_ok=True)
    out_path = os.path.join(RESULTS_DIR, f"{task_id}_comparison.json")
    with open(out_path, "w") as fh:
        json.dump(report, fh, indent=2)

    multi_prod = multi_summary["production"]
    base_prod = baseline_summary["production"]
    mi_diff = None
    if multi_prod["average_maintainability_index"] is not None and base_prod["average_maintainability_index"] is not None:
        mi_diff = round(
            multi_prod["average_maintainability_index"] - base_prod["average_maintainability_index"], 2
        )

    multi_dup = multi_summary["production_duplication"]
    base_dup = baseline_summary["production_duplication"]
    multi_dup_pct = multi_dup["percent_duplicated"] if multi_dup else None
    base_dup_pct = base_dup["percent_duplicated"] if base_dup else None
    dup_diff = (
        round(multi_dup_pct - base_dup_pct, 2)
        if multi_dup_pct is not None and base_dup_pct is not None
        else None
    )

    _append_summary_row(
        {
            "task_id": task_id,
            "compared_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "multi_agent_dir": _relpath(multi_agent_dir),
            "multi_agent_mi": multi_prod["average_maintainability_index"],
            "multi_agent_avg_cc": multi_prod["average_cyclomatic_complexity"],
            "multi_agent_max_cc": multi_prod["max_cyclomatic_complexity"],
            "multi_agent_sloc": multi_prod["total_sloc"],
            "multi_agent_duplication_pct": multi_dup_pct,
            "baseline_dir": _relpath(baseline_dir),
            "baseline_mi": base_prod["average_maintainability_index"],
            "baseline_avg_cc": base_prod["average_cyclomatic_complexity"],
            "baseline_max_cc": base_prod["max_cyclomatic_complexity"],
            "baseline_sloc": base_prod["total_sloc"],
            "baseline_duplication_pct": base_dup_pct,
            "mi_difference_multi_agent_minus_baseline": mi_diff,
            "duplication_pct_difference_multi_agent_minus_baseline": dup_diff,
        }
    )

    print(f"[compare] Multi-agent dir: {multi_agent_dir}")
    print(f"[compare] Baseline dir:    {baseline_dir}")
    print(f"[compare] Multi-agent production MI: {multi_prod['average_maintainability_index']}  "
          f"avg CC: {multi_prod['average_cyclomatic_complexity']}  max CC: {multi_prod['max_cyclomatic_complexity']}  "
          f"duplication: {multi_dup_pct}%")
    print(f"[compare] Baseline production MI:    {base_prod['average_maintainability_index']}  "
          f"avg CC: {base_prod['average_cyclomatic_complexity']}  max CC: {base_prod['max_cyclomatic_complexity']}  "
          f"duplication: {base_dup_pct}%")
    print(f"[compare] Report written to: {out_path}")
    print(f"[compare] Summary row updated in: {SUMMARY_CSV}")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare maintainability metrics: multi-agent vs single-prompt baseline."
    )
    parser.add_argument("--task", required=True, help="Task id, e.g. task_1")
    parser.add_argument(
        "--generated-dir",
        default=None,
        help="Explicit folder of multi-agent-generated code to evaluate "
        "(e.g. a manually copied final version). Defaults to the most "
        "recent runs/<task>_* directory's generated_project/.",
    )
    parser.add_argument(
        "--baseline-dir",
        default=None,
        help="Explicit baseline folder to evaluate. Defaults to "
        "baseline_single_prompt/<task>/generated_project/.",
    )
    args = parser.parse_args()
    compare(args.task, args.generated_dir, args.baseline_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
