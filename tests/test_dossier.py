"""Evidence dossier tests: flagged pairs produce printable, self-contained
dossiers whose executive summary reflects the measured evidence."""

import re
import shutil

from copcat.models import AuditConfig, PairResult
from copcat.dossier import write_dossier


def _pair_with_evidence():
    p = PairResult("G07", "G08", "g07.py", "g08.py")
    p.blended = 0.83
    p.flag = "HIGH_PROBABILITY_PLAGIARISM"
    p.scores = {"source": (0.62, None), "token": (0.41, None),
                "ast": (0.88, None), "shadow": (0.0, None),
                "comment": (0.1, None), "string": (0.22, None)}
    p.evidence = ["evasion match: shadow of X aligns with live code of Y"]
    return p


def test_dossier_contains_committee_sections(tmp_path):
    from tests.test_audit_golden import build_batch
    batch = tmp_path / "batch"
    batch.mkdir()
    build_batch(batch)
    a = batch / "g07_renamed.py"
    b = tmp_path / "g08_copy.py"
    shutil.copy(batch / "g08_orig.py", b)

    from copcat.models import Submission
    cfg = AuditConfig()
    sub_a = Submission("G07", "g07.py", str(a), a.read_text(encoding="utf-8"))
    sub_b = Submission("G08", "g08.py", str(b), b.read_text(encoding="utf-8"))

    out = tmp_path / "dossier.html"
    write_dossier(out, sub_a, sub_b, _pair_with_evidence(), cfg)
    html = out.read_text(encoding="utf-8")

    for section in ("1. Parties", "2. Executive summary", "3. Verdict",
                    "4. Measured similarity by channel",
                    "5. Renamed identifiers", "6. Shared string literals",
                    "7. Side-by-side comparison", "8. Methodology"):
        assert section in html, section
    assert "HIGH_PROBABILITY_PLAGIARISM" in html
    assert "@media print" in html            # printable
    assert "no machine-learning" in html     # methodology disclosure


def test_executive_summary_is_measured_not_speculative(tmp_path):
    from tests.test_audit_golden import build_batch
    from copcat.models import Submission
    batch = tmp_path / "batch"
    batch.mkdir()
    build_batch(batch)
    a = batch / "g03_copy_a.py"
    b = tmp_path / "g04_copy.py"
    shutil.copy(batch / "g04_copy_b.py", b)
    sub_a = Submission("G03", "g03.py", str(a), a.read_text(encoding="utf-8"))
    sub_b = Submission("G04", "g04.py", str(b), b.read_text(encoding="utf-8"))
    p = _pair_with_evidence()
    p.flag = "SUSPICIOUS"

    out = tmp_path / "d.html"
    write_dossier(out, sub_a, sub_b, p, cfg=AuditConfig())
    html = out.read_text(encoding="utf-8")
    m = re.search(r"Overall blended similarity measured (\d+)%", html)
    assert m and 50 <= int(m.group(1)) <= 100
    assert "deterministic" in html
