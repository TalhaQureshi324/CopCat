"""Golden grading tests: rubric scores on the synthetic batch.

G06 (complete, standard naming) must score near full marks; G09 (partial)
must score low. G10 (same logic, every class renamed) documents the
interface-name sensitivity: it scores low until structural class binding
lands (assertion tightened in that milestone).
"""

import json
import sys
from pathlib import Path

import pytest

from copcat.models import AuditConfig
from copcat.rubric import run_grade

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_audit_golden import build_batch, ROOT, RUBRIC  # noqa: E402


@pytest.fixture(scope="module")
def grade_rows(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("golden_grade")
    build_batch(tmp)
    rows = run_grade(str(tmp), str(RUBRIC), str(tmp / "grade_report.csv"))
    return {r["roll"]: r for r in rows}


def test_complete_standard_naming_scores_high(grade_rows):
    assert grade_rows["G06"]["final"] >= 9.0


def test_partial_submission_scores_low(grade_rows):
    assert grade_rows["G09"]["final"] <= 2.0


def test_commented_out_file_scores_zero(grade_rows):
    assert grade_rows["G05"]["final"] <= 1.0


def test_renamed_classes_get_structural_binding_not_zero(grade_rows):
    """G10 = G06's logic with every mandated class renamed. Structural
    binding must recover the logic marks and apply only small naming
    deductions - not wipe the submission to zero."""
    row = grade_rows["G10"]
    assert 7.5 <= row["final"] <= 9.5, "final: {}".format(row["final"])
    assert any("structural match" in bit or "non-standard naming" in bit
               for bit in row["report"].split("; "))
    assert len(row.get("aliases", {})) >= 10


def test_standard_naming_outranks_renamed_naming(grade_rows):
    # identical logic: the standard-named file must still score higher
    assert grade_rows["G06"]["final"] > grade_rows["G10"]["final"]


def test_gradebook_csv_written(tmp_path_factory):
    # grade a tiny fresh batch to prove the CSV artifact is parseable
    tmp = tmp_path_factory.mktemp("csv")
    build_batch(tmp)
    out = tmp / "grade_report.csv"
    run_grade(str(tmp), str(RUBRIC), str(out))
    import csv
    with open(out, encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    assert rows[0][:2] == ["Roll_Number", "Filename"]
    assert any(r[0] == "G06" for r in rows[1:])


def test_report_contains_evidence(grade_rows):
    report = grade_rows["G09"]["report"]
    assert report and report != "None"
