# Evaluation

This is the overall guide to the `evaluation/` folder: how to run the
maintainability comparison, and the conventions for both sides being
compared. It holds everything needed to compare the multi-agent
pipeline's generated code against a single-prompt baseline, for each
task, using objective code-quality/maintainability metrics rather than
subjective judgement. It isolates the variable the dissertation is
testing: **single-prompt generation vs. the multi-agent pipeline**.

Both sides are prepared the same way: the final code for each task is
copied into its own folder under `data/` before running the comparison
— `data/multi_agent_output/<task_id>/generated_project/` for the
pipeline's output, and `data/direct_single_assistant_output/<task_id>/generated_project/`
for the single-prompt baseline. Neither side is generated automatically
by `compare.py`; it only reads whatever has already been copied into
these two folders (or into the folders passed via `--generated-dir`/
`--baseline-dir`).

There are only **two dissertation tasks**, `task_1` and `task_2` (other
files under `tasks/`, e.g. `task_3.txt`/`task_simple.txt`, are unused
drafts and are not part of this comparison).

## Layout

```
evaluation/
    metrics.py   # radon-based static analysis + PMD CPD duplication check
    compare.py   # runs metrics.py on both sides for a task and writes a report
    data/
        multi_agent_output/<task_id>/generated_project/
        direct_single_assistant_output/<task_id>/generated_project/
    results/
        <task_id>_comparison.json   # full per-file + aggregate detail
        summary.csv                 # long/transposed table, one row per metric per task
```

### `data/multi_agent_output/<task_id>/generated_project/`

The final code produced by the multi-agent pipeline for a given task.
Copy it here from whichever `runs/<task_id>_<timestamp>/generated_project/`
run you want to treat as that task's result. Keep the flat-file
convention used by the pipeline itself (no extra nesting for the main
source files); if the pipeline's own tests should be included, keep them
separated the same way the pipeline does (`dev_tests/`, `qa_tests/`).

### `data/direct_single_assistant_output/<task_id>/generated_project/`

The baseline implementation for the same task: the *same* task prompt
(from `tasks/task_N.txt`) pasted directly into a normal AI chat window
(e.g. ChatGPT, Claude, etc.) in a single shot, with no multi-agent
pipeline, no iterative review/revision, and no independent QA. Copy/paste
the baseline's code as real `.py` files here, mirroring the multi-agent
side's flat-file convention so the two can be compared apples-to-apples:

```
data/direct_single_assistant_output/task_1/generated_project/
    calculator.py
    tests/
        test_calculator.py
```

Consider also recording, alongside the code, the raw prompt used, a
chat transcript, and which model/version produced the baseline (e.g. in
a `notes.txt`), so reviewers/your supervisor can see exactly what was
asked and by what.

## What gets measured (`metrics.py`)

Static analysis is done per `.py` file, then aggregated per project.
Files under `dev_tests/`, `qa_tests/`, `tests/`, or `test/` (anywhere in
the relative path) are treated as test code and reported separately so
they don't skew the "production code" numbers.

Per file (via `radon`):
- Maintainability Index (MI), computed from that file's own metrics only
- Cyclomatic Complexity (CC) per function/method block, plus the total
  and count of blocks in the file
- Halstead volume, difficulty, and effort
- Raw metrics: LOC, LLOC, SLOC, comment lines, blank lines

Aggregated per project (production code only):
- Production file count
- Average MI — the arithmetic mean of each file's own MI value (this is
  *not* a single whole-project MI formula)
- Minimum MI — the lowest MI across production files
- Average CC — weighted across every complexity block project-wide
  (total CC summed over all blocks, divided by the number of blocks),
  so files with more functions/methods contribute proportionally more
- Maximum CC across all blocks
- Count of blocks with CC > 10, and the total block count
- Totals for LOC, LLOC, SLOC, comments, and blank lines
- Average Halstead volume, difficulty, and effort across valid files

Duplication ("Duplication %", via PMD's Copy/Paste Detector, `pmd cpd`,
with Python as the language and a fixed `--minimum-tokens 50` threshold):
a single CPD run scans all production files together, so it finds
duplicate blocks both *within* a single file and *across* different
files. The reported percentage is the share of analysed production-code
lines that fall inside at least one duplicate block, with overlapping
duplicate ranges merged so lines are never double-counted. Requires the
PMD CLI to be installed and on PATH (e.g. `brew install pmd` on macOS,
or download a release from https://pmd.github.io/); `PMD_BIN`/`PMD_HOME`
can be set to point at a custom install.

## What `compare.py` produces

For a given task, it runs the above analysis on both the multi-agent
and baseline `generated_project/` folders and writes:

- `results/<task_id>_comparison.json` — full per-file metrics plus the
  aggregated summary for both sides
- `results/summary.csv` — a long/transposed table: one row per metric
  per task (multi-agent value, baseline value, and their difference),
  plus a leading "Directories" row recording which folders were
  compared. Only the first row of each task's block carries the
  `task_id`/`compared_at` values (blank on the rest) so the file reads
  as one grouped block per task rather than repeating those columns on
  every line. Re-running for a task replaces its whole block rather than
  appending duplicates.

It also prints a transposed, human-readable table to the console for
quick inspection.

## Usage

Once both sides' code are in place under `data/`, run from the repo root
(with the project's virtualenv activated so `radon` is available, and
PMD's `pmd` CLI installed and on PATH so `metrics.py` can invoke `pmd cpd`
for the duplication check):

```bash
python -m evaluation.compare --task task_1
python -m evaluation.compare --task task_2
```

This defaults to `data/multi_agent_output/task_1/generated_project/` and
`data/direct_single_assistant_output/task_1/generated_project/`. To point
at a different folder for either side (e.g. a specific `runs/` output),
override explicitly:

```bash
python -m evaluation.compare --task task_1 \
    --generated-dir runs/task_1_<timestamp>/generated_project \
    --baseline-dir /path/to/other/baseline
```
