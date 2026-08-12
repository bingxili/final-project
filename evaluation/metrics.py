"""
Maintainability metrics for a directory of Python source files, computed
with `radon`. Used to compare the multi-agent system's generated code
against a ChatGPT baseline for the same task.

Metrics computed, per file and aggregated per project:
  - Maintainability Index (MI)         -> radon.metrics.mi_visit
  - Cyclomatic Complexity (CC)          -> radon.complexity.cc_visit
  - Halstead metrics (volume, effort..) -> radon.metrics.h_visit
  - Raw metrics (LOC, LLOC, SLOC, comments, blank) -> radon.raw.analyze
  - Code duplication (cross-file)       -> pylint.checkers.symilar.Symilar

Only files matching *.py are analysed; test files (dev_tests/, qa_tests/,
tests/) are analysed separately so they don't skew the "production code"
maintainability numbers, but are still reported for completeness.

Duplication is inherently cross-file, so it is computed once per project
(over the production files only) rather than per file, using the same
line-matching algorithm pylint uses for its `R0801 duplicate-code` check:
blocks of >= MIN_DUPLICATE_LINES consecutive, near-identical lines that
appear in more than one place count as duplicated.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

from pylint.checkers.symilar import Symilar
from radon.complexity import cc_visit
from radon.metrics import h_visit, mi_visit
from radon.raw import analyze as raw_analyze


# Directory names (anywhere in the relative path) treated as "test" code
# rather than "production" code, so aggregates can be split meaningfully.
TEST_DIR_MARKERS = {"dev_tests", "qa_tests", "tests", "test"}

# Minimum number of consecutive similar lines for a block to count as
# duplicated - same default pylint's own duplicate-code checker uses.
MIN_DUPLICATE_LINES = 4


@dataclass
class FileMetrics:
    path: str
    is_test_file: bool
    loc: int
    lloc: int
    sloc: int
    comments: int
    blank: int
    maintainability_index: Optional[float]
    average_cyclomatic_complexity: Optional[float]
    max_cyclomatic_complexity: Optional[int]
    function_count: int
    halstead_volume: Optional[float]
    halstead_effort: Optional[float]
    halstead_difficulty: Optional[float]
    error: Optional[str] = None


@dataclass
class DuplicationMetrics:
    """Cross-file code duplication for a set of files (see module docstring)."""

    total_lines: int
    duplicated_lines: int
    percent_duplicated: float
    duplicate_groups: list[dict] = field(default_factory=list)


@dataclass
class ProjectMetrics:
    root_dir: str
    files: list[FileMetrics] = field(default_factory=list)
    duplication: Optional[DuplicationMetrics] = None

    @property
    def production_files(self) -> list[FileMetrics]:
        return [f for f in self.files if not f.is_test_file and f.error is None]

    @property
    def test_files(self) -> list[FileMetrics]:
        return [f for f in self.files if f.is_test_file and f.error is None]

    def _aggregate(self, files: list[FileMetrics]) -> dict:
        if not files:
            return {
                "file_count": 0,
                "total_loc": 0,
                "total_sloc": 0,
                "average_maintainability_index": None,
                "average_cyclomatic_complexity": None,
                "max_cyclomatic_complexity": None,
                "total_function_count": 0,
            }
        mi_values = [f.maintainability_index for f in files if f.maintainability_index is not None]
        cc_values = [f.average_cyclomatic_complexity for f in files if f.average_cyclomatic_complexity is not None]
        max_cc_values = [f.max_cyclomatic_complexity for f in files if f.max_cyclomatic_complexity is not None]
        return {
            "file_count": len(files),
            "total_loc": sum(f.loc for f in files),
            "total_sloc": sum(f.sloc for f in files),
            "average_maintainability_index": round(sum(mi_values) / len(mi_values), 2) if mi_values else None,
            "average_cyclomatic_complexity": round(sum(cc_values) / len(cc_values), 2) if cc_values else None,
            "max_cyclomatic_complexity": max(max_cc_values) if max_cc_values else None,
            "total_function_count": sum(f.function_count for f in files),
        }

    def summary(self) -> dict:
        return {
            "root_dir": self.root_dir,
            "production": self._aggregate(self.production_files),
            "tests": self._aggregate(self.test_files),
            "files_with_errors": [f.path for f in self.files if f.error is not None],
            "production_duplication": (
                {
                    "total_lines": self.duplication.total_lines,
                    "duplicated_lines": self.duplication.duplicated_lines,
                    "percent_duplicated": self.duplication.percent_duplicated,
                    "duplicate_groups": self.duplication.duplicate_groups,
                }
                if self.duplication is not None
                else None
            ),
        }


def _is_test_file(relative_path: str) -> bool:
    parts = set(os.path.normpath(relative_path).split(os.sep))
    return bool(parts & TEST_DIR_MARKERS)


def _analyze_file(root_dir: str, relative_path: str) -> FileMetrics:
    full_path = os.path.join(root_dir, relative_path)
    is_test = _is_test_file(relative_path)
    try:
        with open(full_path, "r") as fh:
            source = fh.read()

        raw = raw_analyze(source)
        cc_blocks = cc_visit(source)
        mi = mi_visit(source, multi=True)

        avg_cc = (
            sum(b.complexity for b in cc_blocks) / len(cc_blocks) if cc_blocks else None
        )
        max_cc = max((b.complexity for b in cc_blocks), default=None)

        halstead_volume = halstead_effort = halstead_difficulty = None
        try:
            h = h_visit(source)
            if h.total is not None:
                halstead_volume = h.total.volume
                halstead_effort = h.total.effort
                halstead_difficulty = h.total.difficulty
        except Exception:  # noqa: BLE001 - Halstead can fail on some inputs; non-critical
            pass

        return FileMetrics(
            path=relative_path,
            is_test_file=is_test,
            loc=raw.loc,
            lloc=raw.lloc,
            sloc=raw.sloc,
            comments=raw.comments,
            blank=raw.blank,
            maintainability_index=round(mi, 2) if mi is not None else None,
            average_cyclomatic_complexity=round(avg_cc, 2) if avg_cc is not None else None,
            max_cyclomatic_complexity=max_cc,
            function_count=len(cc_blocks),
            halstead_volume=halstead_volume,
            halstead_effort=halstead_effort,
            halstead_difficulty=halstead_difficulty,
        )
    except Exception as exc:  # noqa: BLE001 - report the error, don't crash the whole run
        return FileMetrics(
            path=relative_path,
            is_test_file=is_test,
            loc=0, lloc=0, sloc=0, comments=0, blank=0,
            maintainability_index=None,
            average_cyclomatic_complexity=None,
            max_cyclomatic_complexity=None,
            function_count=0,
            halstead_volume=None,
            halstead_effort=None,
            halstead_difficulty=None,
            error=str(exc),
        )


def analyze_project(root_dir: str) -> ProjectMetrics:
    """Recursively analyze all *.py files under root_dir."""
    project = ProjectMetrics(root_dir=root_dir)
    if not os.path.isdir(root_dir):
        return project

    for dirpath, _dirnames, filenames in os.walk(root_dir):
        for filename in sorted(filenames):
            if not filename.endswith(".py"):
                continue
            full_path = os.path.join(dirpath, filename)
            relative_path = os.path.relpath(full_path, root_dir)
            project.files.append(_analyze_file(root_dir, relative_path))

    project.duplication = _compute_duplication(root_dir, project.production_files)
    return project


def _compute_duplication(
    root_dir: str, files: list[FileMetrics], min_lines: int = MIN_DUPLICATE_LINES
) -> DuplicationMetrics:
    """Detect copy-pasted blocks across `files` using pylint's duplicate-code
    engine (the same algorithm behind its `R0801` check): near-identical runs
    of >= min_lines consecutive lines shared between two or more locations.

    Returns total analysed lines, how many of them are duplicated, and the
    percentage - the same formula pylint itself reports for R0801.
    """
    checker = Symilar(min_lines=min_lines)
    analysed_any = False
    for f in files:
        full_path = os.path.join(root_dir, f.path)
        try:
            with open(full_path, "r", encoding="utf-8") as fh:
                checker.append_stream(f.path, fh)
            analysed_any = True
        except OSError:
            continue

    if not analysed_any:
        return DuplicationMetrics(total_lines=0, duplicated_lines=0, percent_duplicated=0.0)

    total_lines = sum(len(lineset) for lineset in checker.linesets)
    duplicated_lines = 0
    duplicate_groups = []
    for num_lines, couples in checker._compute_sims():
        duplicated_lines += num_lines * (len(couples) - 1)
        duplicate_groups.append(
            {
                "duplicated_lines": num_lines,
                "occurrences": sorted(
                    (
                        {"file": lineset.name, "start_line": start, "end_line": end}
                        for lineset, start, end in couples
                    ),
                    key=lambda o: (o["file"], o["start_line"]),
                ),
            }
        )

    percent_duplicated = round(duplicated_lines * 100.0 / total_lines, 2) if total_lines else 0.0
    return DuplicationMetrics(
        total_lines=total_lines,
        duplicated_lines=duplicated_lines,
        percent_duplicated=percent_duplicated,
        duplicate_groups=sorted(duplicate_groups, key=lambda g: -g["duplicated_lines"]),
    )
