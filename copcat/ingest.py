"""Submission discovery + roll-number extraction."""

import os
import re

ROLL_RE = re.compile(r"bscs(\d{3,7})", re.IGNORECASE)


def extract_roll(filename):
    """'bscs25134_ai_lab02.py' -> 'BSCS25134'; falls back to name token."""
    m = ROLL_RE.search(filename)
    if m:
        return "BSCS" + m.group(1).upper()
    base = os.path.splitext(filename)[0]
    tok = re.split(r"[_\-\s]+", base.strip())[0]
    return (tok or base).upper()


def discover(directory, extra_excludes=()):
    """Sorted list of *.py paths in `directory` (non-recursive), excluding
    copcat's own artifacts and anything under an output folder."""
    excludes = {"copcat_audit.csv", "copcat_audit.txt",
                "lab02_evaluation_report.csv", "plagiarism_audit.txt"}
    excludes.update(extra_excludes)
    out = []
    for name in sorted(os.listdir(directory)):
        path = os.path.join(directory, name)
        if not os.path.isfile(path) or not name.endswith(".py"):
            continue
        if name in excludes or name.startswith("copcat_"):
            continue
        out.append(path)
    return out


def load_sources(directory, extra_excludes=()):
    """[(path, roll, filename, source)]"""
    results = []
    for path in discover(directory, extra_excludes):
        with open(path, encoding="utf-8-sig", errors="replace") as fh:
            src = fh.read()
        fname = os.path.basename(path)
        results.append((path, extract_roll(fname), fname, src))
    return results
