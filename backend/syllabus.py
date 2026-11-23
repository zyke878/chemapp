"""Syllabus data: which functional groups are taught in which grade.

Reads syllabus.json (edit that file, not this one, to change the data).
Person B can use these helpers to keep explanations at the right grade level.
"""
import json
from pathlib import Path

with open(Path(__file__).with_name("syllabus.json"), encoding="utf-8") as _f:
    _DATA = json.load(_f)

SUPPORTED_BOARDS = [_DATA["board"]]
SUPPORTED_GRADES = sorted(int(g) for g in _DATA["grades"])


def _grade_data(board, grade):
    if board not in SUPPORTED_BOARDS or str(grade) not in _DATA["grades"]:
        raise KeyError(f"No syllabus for board={board!r}, grade={grade!r}")
    return _DATA["grades"][str(grade)]


def chapters(board, grade):
    """List of chapter dicts (name, topics, groups, ...) for the grade."""
    return _grade_data(board, grade)["chapters"]


def groups_for_grade(board, grade):
    """Return {'in_syllabus': [...], 'to_verify': [...]} (sorted, no overlap)."""
    core, verify = set(), set()
    for ch in chapters(board, grade):
        core.update(ch.get("groups_in_syllabus", []))
        verify.update(ch.get("groups_to_verify", []))
    return {"in_syllabus": sorted(core), "to_verify": sorted(verify - core)}


def covers_everything(board, grade):
    """True if every detectable group counts as relevant for this grade (no syllabus gating)."""
    return bool(_grade_data(board, grade).get("covers_everything", False))


def relevant_groups(board, grade):
    """Set of group keys listed in this grade's chapters (verified or not).

    For grades where covers_everything() is True, treat every group as relevant instead.
    """
    g = groups_for_grade(board, grade)
    return set(g["in_syllabus"]) | set(g["to_verify"])


def topics_for_group(board, grade, group):
    """Chapter names (and their topics) that involve the given group key."""
    out = []
    for ch in chapters(board, grade):
        if group in ch.get("groups_in_syllabus", []) or group in ch.get("groups_to_verify", []):
            out.append({"chapter": ch["name"], "topics": ch["topics"]})
    return out


def practical_test_for_group(board, grade, group):
    """Name of the practical functional-group test for this group, or None."""
    return _grade_data(board, grade).get("functional_group_tests", {}).get(group)
