"""
Compare maintainability metrics between:
  (a) the multi-agent system's generated code for a task
      (evaluation/multi_agent_output/<task_id>/generated_project/), and
  (b) a single-prompt baseline for the same task
      (evaluation/direct_single_assistant_output/<task_id>/generated_project/).

By default, both (a) and (b) resolve to these fixed evaluation/ folders,
so you first copy the final chosen version of each task's code into both:
the multi-agent side's generated_project/ folder from whichever
runs/<task_id>_<timestamp>/ you want to use as the final result for that
task, and the baseline's code pasted from a single-prompt chat session.
See evaluation/README.md for the folder conventions for both sides. Pass
--generated-dir/--baseline-dir explicitly to override either side.

Usage:
    python -m evaluation.compare --task task_1
    python -m evaluation.compare --task task_1 --generated-dir /path/to/final_code_folder
    python -m evaluation.compare --task task_1 --baseline-dir /path/to/baseline_folder

Writes:
    evaluation/results/<task_id>_comparison.json   (detailed, per-file + aggregate)
    evaluation/results/summary.csv                  (long/transposed format:
                                                      one row per metric per task,
                                                      replacing any prior rows
                                                      for that task_id)
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
    "metric",
    "multi_agent",
    "baseline",
    "difference_multi_agent_minus_baseline",
]

# (label, summary-dict key) pairs pulled from each side's `production` summary,
# in the order they should be reported. "duplication" is handled separately
# since it lives in a sibling "production_duplication" summary key.
METRIC_FIELDS = [
    ("Production file count", "file_count"),
    ("Average MI (mean file MI)", "average_maintainability_index"),
    ("Minimum MI", "minimum_maintainability_index"),
    ("Average CC (block-weighted)", "average_cyclomatic_complexity"),
    ("Max CC", "max_cyclomatic_complexity"),
    ("Blocks with CC > 10", "blocks_above_cc_10"),
    ("Total complexity block count", "total_complexity_block_count"),
    ("LOC", "total_loc"),
    ("LLOC", "total_lloc"),
    ("SLOC", "total_sloc"),
    ("Comments", "total_comments"),
    ("Blank lines", "total_blank"),
    ("Avg Halstead Volume", "average_halstead_volume"),
    ("Avg Halstead Difficulty", "average_halstead_difficulty"),
    ("Avg Halstead Effort", "average_halstead_effort"),
]
DUPLICATION_LABEL = "Duplication %"


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


def _forward_filled_task_ids(rows: list[dict]) -> list[str]:
    """Since only the first row of each task's block carries a `task_id`
    (blank thereafter, for readability), recover the logical task_id for
    every row by carrying the last non-blank value forward."""
    ids = []
    last = ""
    for r in rows:
        tid = r.get("task_id") or ""
        if tid:
            last = tid
        ids.append(last)
    return ids


def _append_summary_rows(task_id: str, rows: list[dict]) -> None:
    """Replace all summary rows for `task_id` with `rows` (one row per metric).

    Only the first row of `rows` is expected to carry `task_id`/`compared_at`
    (blank on the rest) so the CSV reads as one grouped block per task
    instead of repeating those columns on every line.
    """
    os.makedirs(RESULTS_DIR, exist_ok=True)
    file_exists = os.path.isfile(SUMMARY_CSV)
    existing_rows = []
    if file_exists:
        with open(SUMMARY_CSV, "r", newline="") as fh:
            raw_rows = list(csv.DictReader(fh))
        # restval/reader handles rows from older/newer schema versions without
        # misaligning columns; drop any rows belonging to the task we're
        # about to rewrite (recovering their logical task_id via forward-fill
        # since it's only stored on each block's first row).
        logical_ids = _forward_filled_task_ids(raw_rows)
        for r, logical_id in zip(raw_rows, logical_ids):
            if logical_id == task_id:
                continue
            existing_rows.append({field: r.get(field, "") for field in CSV_FIELDS})
    existing_rows.extend(rows)
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

    multi_dup = multi_summary["production_duplication"]
    base_dup = baseline_summary["production_duplication"]
    multi_dup_pct = multi_dup["duplication_percentage"] if multi_dup else None
    base_dup_pct = base_dup["duplication_percentage"] if base_dup else None

    def _diff(multi_val, base_val):
        if isinstance(multi_val, (int, float)) and isinstance(base_val, (int, float)):
            return round(multi_val - base_val, 2)
        return None

    # One (label, multi_value, base_value, difference) tuple per reported
    # metric - this drives both the CSV rows and the transposed console table.
    metric_rows = []
    for label, key in METRIC_FIELDS:
        multi_val = multi_prod.get(key)
        base_val = base_prod.get(key)
        metric_rows.append((label, multi_val, base_val, _diff(multi_val, base_val)))
    metric_rows.append((DUPLICATION_LABEL, multi_dup_pct, base_dup_pct, _diff(multi_dup_pct, base_dup_pct)))

    compared_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    # Single combined row for both directories (instead of two sparse rows
    # each with only one side filled in). Only this first row of the block
    # carries task_id/compared_at; every row after it leaves them blank so
    # the CSV reads as one grouped block per task.
    csv_rows = [
        {
            "task_id": task_id,
            "compared_at": compared_at,
            "metric": "Directories",
            "multi_agent": _relpath(multi_agent_dir),
            "baseline": _relpath(baseline_dir),
            "difference_multi_agent_minus_baseline": "",
        },
    ]
    for label, multi_val, base_val, diff in metric_rows:
        csv_rows.append(
            {
                "task_id": "",
                "compared_at": "",
                "metric": label,
                "multi_agent": multi_val,
                "baseline": base_val,
                "difference_multi_agent_minus_baseline": diff,
            }
        )
    _append_summary_rows(task_id, csv_rows)

    _print_transposed_summary(task_id, multi_agent_dir, baseline_dir, metric_rows)
    print(f"[compare] Report written to: {out_path}")
    print(f"[compare] Summary rows updated in: {SUMMARY_CSV}")
    return report


def _print_transposed_summary(
    task_id: str, multi_agent_dir: str, baseline_dir: str, metric_rows: list[tuple]
) -> None:
    """Print a human-readable table with one row per metric (transposed),
    rather than the wide, hard-to-scan single-row-per-task layout."""

    def _fmt(value) -> str:
        if value is None:
            return "-"
        if isinstance(value, float):
            return f"{value:.2f}"
        return str(value)

    headers = ("Metric", "Multi-agent", "Baseline", "Diff (multi - baseline)")
    rows = [(label, _fmt(m), _fmt(b), _fmt(d)) for label, m, b, d in metric_rows]
    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]

    def _line(cols: tuple) -> str:
        return "  ".join(col.ljust(widths[i]) for i, col in enumerate(cols))

    print(f"\n[compare] Task: {task_id}")
    print(f"[compare] Multi-agent dir: {multi_agent_dir}")
    print(f"[compare] Baseline dir:    {baseline_dir}\n")
    print(_line(headers))
    print("  ".join("-" * w for w in widths))
    for row in rows:
        print(_line(row))
    print()


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
