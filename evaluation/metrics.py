"""
Maintainability metrics for a directory of Python source files, computed
with `radon`. Used to compare the multi-agent system's generated code
against a ChatGPT baseline for the same task.

Metrics computed, per file and aggregated per project:
  - Maintainability Index (MI)         -> radon.metrics.mi_visit
  - Cyclomatic Complexity (CC)          -> radon.complexity.cc_visit
  - Halstead metrics (volume, effort..) -> radon.metrics.h_visit
  - Raw metrics (LOC, LLOC, SLOC, comments, blank) -> radon.raw.analyze
  - Code duplication (intra- and inter-file) -> PMD CPD (external `pmd cpd`
    command-line tool; see https://pmd.github.io/)

Only files matching *.py are analysed; test files (dev_tests/, qa_tests/,
tests/) are analysed separately so they don't skew the "production code"
maintainability numbers, but are still reported for completeness.

Duplication is computed once per project (over the production files only,
same rule as everything else here) by invoking PMD's Copy/Paste Detector
(CPD) with Python as the source language and a fixed
`--minimum-tokens 50` threshold. Unlike a purely cross-file comparison,
CPD tokenizes and scans across the whole set of files it's given, so it
finds duplicate blocks *within* a single file as well as *across*
different files. The reported "Duplication %" is the percentage of
physical production-code lines (LOC) that fall inside at least one duplicate
block, with overlapping duplicate ranges merged so lines are never
double-counted (see `_merge_intervals`).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from radon.complexity import cc_visit
from radon.metrics import h_visit, mi_visit
from radon.raw import analyze as raw_analyze


# Directory names (anywhere in the relative path) treated as "test" code
# rather than "production" code, so aggregates can be split meaningfully.
TEST_DIR_MARKERS = {"dev_tests", "qa_tests", "tests", "test"}

# Minimum token-length for a code block to be reported as a duplicate by
# PMD CPD - used for both intra-file and inter-file duplication, since a
# single CPD run naturally detects both at once.
CPD_MINIMUM_TOKENS = 50


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
    total_cyclomatic_complexity: int
    max_cyclomatic_complexity: Optional[int]
    complexity_block_count: int
    blocks_above_cc_10: int
    halstead_volume: Optional[float]
    halstead_effort: Optional[float]
    halstead_difficulty: Optional[float]
    error: Optional[str] = None


@dataclass
class DuplicationMetrics:
    """Intra- and inter-file code duplication for a set of production files."""

    total_lines: int
    duplicated_lines: int
    duplication_percentage: float
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
                "total_lloc": 0,
                "total_sloc": 0,
                "total_comments": 0,
                "total_blank": 0,
                # Mean of each file's own MI value - NOT a single whole-project
                # MI computed from combined/aggregated source metrics.
                "average_maintainability_index": None,
                "minimum_maintainability_index": None,
                # Weighted across all radon complexity blocks project-wide:
                # sum(block CC) / count(blocks). Files with more blocks
                # contribute proportionally more, unlike averaging per-file
                # averages.
                "average_cyclomatic_complexity": None,
                "max_cyclomatic_complexity": None,
                "total_complexity_block_count": 0,
                "blocks_above_cc_10": 0,
                "average_halstead_volume": None,
                "average_halstead_difficulty": None,
                "average_halstead_effort": None,
            }
        mi_values = [f.maintainability_index for f in files if f.maintainability_index is not None]
        total_cc = sum(f.total_cyclomatic_complexity for f in files)
        total_blocks = sum(f.complexity_block_count for f in files)
        max_cc_values = [f.max_cyclomatic_complexity for f in files if f.max_cyclomatic_complexity is not None]
        blocks_above_10 = sum(f.blocks_above_cc_10 for f in files)
        hv_values = [f.halstead_volume for f in files if f.halstead_volume is not None]
        hd_values = [f.halstead_difficulty for f in files if f.halstead_difficulty is not None]
        he_values = [f.halstead_effort for f in files if f.halstead_effort is not None]
        return {
            "file_count": len(files),
            "total_loc": sum(f.loc for f in files),
            "total_lloc": sum(f.lloc for f in files),
            "total_sloc": sum(f.sloc for f in files),
            "total_comments": sum(f.comments for f in files),
            "total_blank": sum(f.blank for f in files),
            # Mean of each file's own MI value - NOT a single whole-project
            # MI computed from combined/aggregated source metrics.
            "average_maintainability_index": round(sum(mi_values) / len(mi_values), 2) if mi_values else None,
            "minimum_maintainability_index": round(min(mi_values), 2) if mi_values else None,
            # Weighted across all radon complexity blocks project-wide:
            # sum(block CC) / count(blocks), rather than averaging each
            # file's own (already-averaged) CC value.
            "average_cyclomatic_complexity": round(total_cc / total_blocks, 2) if total_blocks else None,
            "max_cyclomatic_complexity": max(max_cc_values) if max_cc_values else None,
            "total_complexity_block_count": total_blocks,
            "blocks_above_cc_10": blocks_above_10,
            "average_halstead_volume": round(sum(hv_values) / len(hv_values), 2) if hv_values else None,
            "average_halstead_difficulty": round(sum(hd_values) / len(hd_values), 2) if hd_values else None,
            "average_halstead_effort": round(sum(he_values) / len(he_values), 2) if he_values else None,
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
                    "duplication_percentage": self.duplication.duplication_percentage,
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
        # multi=True: treat multiline strings as lines of comments
        mi = mi_visit(source, multi=True)

        total_cc = sum(b.complexity for b in cc_blocks)
        avg_cc = (total_cc / len(cc_blocks)) if cc_blocks else None
        max_cc = max((b.complexity for b in cc_blocks), default=None)
        blocks_above_cc_10 = sum(1 for b in cc_blocks if b.complexity > 10)

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
            total_cyclomatic_complexity=total_cc,
            max_cyclomatic_complexity=max_cc,
            complexity_block_count=len(cc_blocks),
            blocks_above_cc_10=blocks_above_cc_10,
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
            total_cyclomatic_complexity=0,
            max_cyclomatic_complexity=None,
            complexity_block_count=0,
            blocks_above_cc_10=0,
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


def _find_pmd_executable() -> str:
    """Locate the PMD CLI executable. PMD 7+ ships a single `pmd` binary
    with a `cpd` subcommand (e.g. `brew install pmd` on macOS, or download
    a release from https://pmd.github.io/ and add its `bin/` directory to
    PATH). Checks the `PMD_BIN`/`PMD_HOME` environment variables first for
    custom installs, then falls back to PATH.
    """
    env_bin = os.environ.get("PMD_BIN")
    if env_bin and shutil.which(env_bin):
        return env_bin

    pmd_home = os.environ.get("PMD_HOME")
    if pmd_home:
        candidate = os.path.join(pmd_home, "bin", "pmd")
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate

    found = shutil.which("pmd")
    if found:
        return found

    raise RuntimeError(
        "PMD CPD not found. Duplication analysis requires the PMD CLI "
        "(`pmd cpd ...`) to be installed and on PATH - e.g. run "
        "`brew install pmd` on macOS, or download a release from "
        "https://pmd.github.io/ and add its bin/ directory to PATH. "
        "Alternatively, set the PMD_BIN (full path to the `pmd` "
        "executable) or PMD_HOME (PMD install directory) environment "
        "variable."
    )


def _local_tag(tag: str) -> str:
    """Strip the XML namespace from an ElementTree tag, e.g.
    '{https://pmd-code.org/schema/cpd-report}duplication' -> 'duplication'.
    """
    return tag.rsplit("}", 1)[-1]


def _merge_intervals(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Merge overlapping/adjacent (start, end) line-number intervals (both
    inclusive) into their union, so lines shared by more than one interval
    are only ever counted once.
    """
    if not intervals:
        return []
    ordered = sorted(intervals)
    merged = [ordered[0]]
    for start, end in ordered[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end + 1:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def _compute_duplication(
    root_dir: str, files: list[FileMetrics], min_tokens: int = CPD_MINIMUM_TOKENS
) -> DuplicationMetrics:
    """Detect duplicate code blocks among `files` using PMD's Copy/Paste
    Detector (CPD), with Python as the source language and a fixed
    `--minimum-tokens` threshold. A single CPD run covers both:
      - intra-file duplication (two blocks in the same file), and
      - inter-file duplication (blocks shared across different files),
    since CPD tokenizes and scans the whole set of given files together
    rather than comparing files pairwise.

    Returns the total analysed production-code lines (LOC), how many of them
    fall inside at least one duplicate block (with overlapping duplicate
    ranges merged so lines are never double-counted), and the resulting
    percentage.
    """
    if not files:
        return DuplicationMetrics(total_lines=0, duplicated_lines=0, duplication_percentage=0.0)

    pmd_bin = _find_pmd_executable()
    file_paths = [os.path.join(root_dir, f.path) for f in files]

    cmd = [
        pmd_bin,
        "cpd",
        "--language",
        "python",
        "--minimum-tokens",
        str(min_tokens),
        "--format",
        "xml",
        "--no-fail-on-violation",
        "--no-fail-on-error",
        *file_paths,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise RuntimeError(f"Failed to run PMD CPD ({pmd_bin}): {exc}") from exc

    if not result.stdout.strip():
        raise RuntimeError(
            f"PMD CPD produced no output (exit code {result.returncode}). "
            f"stderr: {result.stderr.strip()}"
        )

    root = ET.fromstring(result.stdout)

    duplicate_groups = []
    intervals_by_file: dict[str, list[tuple[int, int]]] = defaultdict(list)

    for dup_elem in root:
        if _local_tag(dup_elem.tag) != "duplication":
            continue
        lines = int(dup_elem.attrib.get("lines", 0))
        tokens = int(dup_elem.attrib.get("tokens", 0))
        occurrences = []
        for file_elem in dup_elem:
            if _local_tag(file_elem.tag) != "file":
                continue
            rel_path = os.path.relpath(file_elem.attrib["path"], root_dir)
            start_line = int(file_elem.attrib["line"])
            end_line = int(file_elem.attrib["endline"])
            occurrences.append({"file": rel_path, "start_line": start_line, "end_line": end_line})
            intervals_by_file[rel_path].append((start_line, end_line))
        duplicate_groups.append(
            {
                "duplicated_lines": lines,
                "tokens": tokens,
                "occurrences": sorted(occurrences, key=lambda o: (o["file"], o["start_line"])),
            }
        )

    # Union duplicated line ranges per file, so a line that's part of more
    # than one reported duplicate group (e.g. it overlaps two separate
    # matches) is only counted once towards duplicated_lines/percentage.
    duplicated_lines = 0
    for intervals in intervals_by_file.values():
        for start, end in _merge_intervals(intervals):
            duplicated_lines += end - start + 1

    total_lines = sum(f.loc for f in files)
    duplication_percentage = round(duplicated_lines * 100.0 / total_lines, 2) if total_lines else 0.0

    return DuplicationMetrics(
        total_lines=total_lines,
        duplicated_lines=duplicated_lines,
        duplication_percentage=duplication_percentage,
        duplicate_groups=sorted(duplicate_groups, key=lambda g: -g["duplicated_lines"]),
    )
