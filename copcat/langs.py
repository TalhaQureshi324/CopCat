"""Submission language detection - single source of truth.

The audit pipeline (loader -> channels -> compare) is language-aware and
currently supports Python and C/C++.  The grading engine runs Python
submissions only: `ingest.discover` deliberately stays .py-only so a C++
file can never reach the Python sandbox.
"""

import re

CPP_RE = re.compile(r"\.(?:cpp|cc|cxx|c\+\+|c|h|hh|hpp)$", re.IGNORECASE)
PY_RE = re.compile(r"\.py$", re.IGNORECASE)


def lang_of(filename):
    """"cpp" | "python" for a submission filename."""
    if CPP_RE.search(filename or ""):
        return "cpp"
    return "python"


def is_source(filename):
    """True for any file the audit pipeline ingests (any language)."""
    return bool(CPP_RE.search(filename or "") or PY_RE.search(filename or ""))
