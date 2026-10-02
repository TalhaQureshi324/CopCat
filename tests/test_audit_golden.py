"""Golden audit tests: the synthetic batch must reproduce the calibrated
ground truth — copy pair flagged, commented-out evasion pair flagged via the
shadow channel, renamed pair matched by the AST channel, clean pairs clean,
and results deterministic across runs."""

import os
import shutil
import sys
from pathlib import Path

import pytest

from copcat.models import AuditConfig
from copcat.audit import run_audit

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "tests" / "golden" / "submissions"
RUBRIC = ROOT / "examples" / "rubric_lab02.yaml"

PRESERVE = ("Book,Library,Employee,Manager,Developer,Intern,BankAccount,"
            "Complex,Shape,Circle,Rectangle,Triangle,InventoryError,"
            "InsufficientStockError,InvalidQuantityError,InventoryItem,"
            "borrow_book,return_book,find_by_title,total_books_available,"
            "calculate_pay,deposit,withdraw,remove_stock,area,perimeter,balance").split(",")

# G10: G06 with every mandated class renamed (structural-binding golden file)
G10_RENAMES = {
    "BankAccountError": "BankAccError",
    "InsufficientStockError": "LowStockError",
    "InvalidQuantityError": "BadQtyError",
    "BankAccount": "BankAcc",
    "InventoryError": "StockError",
    "InventoryItem": "StockItem",
    "Rectangle": "Rect",
    "Triangle": "Tri",
    "Circle": "Circ",
    "Shape": "ShapeBase",
    "Complex": "Cpx",
    "Employee": "StaffMember",
    "Manager": "Lead",
    "Developer": "Coder",
    "Intern": "Trainee",
    "Library": "Catalog",
    "Book": "BookItem",
}


def build_batch(tmp_dir):
    """Assemble the golden batch: 9 committed files + generated G05/G10."""
    for src in sorted(GOLDEN.glob("*.py")):
        shutil.copy(src, tmp_dir / src.name)
    # G05: G06 fully commented out (the MOSS-evasion twin)
    lines = Path(tmp_dir / "g06_live.py").read_text(encoding="utf-8").splitlines()
    out = ["# G05 - honestly I wrote this myself last semester", "# please ignore"]
    for ln in lines:
        out.append(("# " + ln.strip()) if ln.strip() else "")
    (tmp_dir / "g05_hidden.py").write_text("\n".join(out), encoding="utf-8")
    # G10: G06 with all mandated classes renamed
    import re
    g10 = Path(tmp_dir / "g06_live.py").read_text(encoding="utf-8")
    for old in sorted(G10_RENAMES, key=len, reverse=True):
        g10 = re.sub(r"\b%s\b" % old, G10_RENAMES[old], g10)
    (tmp_dir / "g10_rename_class.py").write_text(g10, encoding="utf-8")


@pytest.fixture(scope="module")
def audit_result(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("golden_batch")
    build_batch(tmp)
    cfg = AuditConfig(preserved=tuple(PRESERVE))
    pairs = run_audit(str(tmp), cfg, str(tmp / "out"), workers=1)
    return pairs


def _pair(pairs, a, b):
    for p in pairs:
        if {p.roll_a, p.roll_b} == {a, b}:
            return p
    raise AssertionError("pair not found: {} vs {}".format(a, b))


def test_copy_pair_flagged(audit_result):
    p = _pair(audit_result, "G03", "G04")
    assert p.flag in ("SUSPICIOUS", "HIGH_PROBABILITY_PLAGIARISM")
    assert p.scores["source"][0] >= 0.6


def test_evasion_pair_flagged_by_shadow(audit_result):
    p = _pair(audit_result, "G05", "G06")
    assert p.flag in ("SUSPICIOUS", "HIGH_PROBABILITY_PLAGIARISM")
    assert any("evasion match" in e for e in p.evidence)


def test_renamed_pair_matched_by_ast_channel(audit_result):
    p = _pair(audit_result, "G07", "G08")
    # renaming must crater the source channel while the AST channel stays
    # high — the rename-invariance signal is the gap between the two
    assert p.scores["source"][0] < 0.6
    assert p.scores["ast"][0] >= 0.5
    assert p.scores["ast"][0] - p.scores["source"][0] >= 0.15
    assert p.flag in ("SUSPICIOUS", "HIGH_PROBABILITY_PLAGIARISM")


def test_rename_class_solution_flagged_against_its_source(audit_result):
    p = _pair(audit_result, "G06", "G10")
    assert p.flag in ("SUSPICIOUS", "HIGH_PROBABILITY_PLAGIARISM")


def test_clean_pairs_stay_clean(audit_result):
    for a, b in (("G01", "G02"), ("G01", "G09"), ("G02", "G09"),
                 ("G01", "G03"), ("G02", "G03")):
        p = _pair(audit_result, a, b)
        assert p.flag == "CLEAN", "{} vs {} -> {} {:.0%}".format(
            a, b, p.flag, p.blended)


def test_determinism(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("golden_det")
    build_batch(tmp)
    cfg = AuditConfig(preserved=tuple(PRESERVE))
    run1 = [(p.roll_a, p.roll_b, round(p.blended, 6))
            for p in run_audit(str(tmp), cfg, str(tmp / "o1"), workers=1)]
    run2 = [(p.roll_a, p.roll_b, round(p.blended, 6))
            for p in run_audit(str(tmp), cfg, str(tmp / "o2"), workers=1)]
    assert run1 == run2
