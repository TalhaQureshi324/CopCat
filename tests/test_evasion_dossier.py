"""Evasion dossiers: the side-by-side must show the hidden (commented-out)
code aligned against the counterpart's live code, with real line matches —
not a tokenized-vs-raw diff that reads '0 identical'.
"""

import re

from copcat.channels import build_submission
from copcat.dossier import write_dossier
from copcat.models import AuditConfig, PairResult

BODY = (
    "class InventoryError(Exception):\n"
    "    pass\n"
    "\n"
    "class InsufficientStockError(InventoryError):\n"
    "    pass\n"
    "\n"
    "class InventoryItem:\n"
    "    def __init__(self, name, quantity, reorder_level):\n"
    "        self.name = name\n"
    "        self.quantity = quantity\n"
    "        self.reorder_level = reorder_level\n"
    "\n"
    "    def remove_stock(self, qty):\n"
    "        if qty <= 0:\n"
    "            raise InvalidQuantityError('must be positive')\n"
    "        if qty > self.quantity:\n"
    "            raise InsufficientStockError('not enough stock')\n"
    "        self.quantity -= qty\n"
    "        print('removed', qty)\n"
    "\n"
    "item = InventoryItem('USB Cable', 10, 5)\n"
    "item.remove_stock(4)\n")


def _subs(tmp_path):
    cfg = AuditConfig()
    hidden_src = "\n".join("# " + ln if ln.strip() else ""
                           for ln in BODY.splitlines())
    hidden = build_submission("H1", "hidden.py",
                              str(tmp_path / "hidden.py"), hidden_src, cfg)
    live = build_submission("L1", "live.py",
                            str(tmp_path / "live.py"), BODY, cfg)
    return cfg, hidden, live


def test_evasion_dossier_shows_hidden_vs_live_alignment(tmp_path):
    cfg, hidden, live = _subs(tmp_path)
    assert hidden.notes, "fixture must be detected as mostly-commented"

    pair = PairResult(
        roll_a="H1", roll_b="L1", file_a="hidden.py", file_b="live.py",
        scores={"source": (0.02, None), "token": (0.0, 0.0),
                "ast": (0.0, 0.0), "shadow": (0.28, 0.1),
                "comment": (0.0, 0.0), "string": (0.0, 0.0)},
        blended=0.45, flag="HIGH_PROBABILITY_PLAGIARISM", evasion=0.28)

    out = tmp_path / "dossier.html"
    write_dossier(out, hidden, live, pair, cfg)
    html = out.read_text(encoding="utf-8")

    # the evasion alignment section exists with a NON-ZERO identical count
    m = re.search(r"Evasion alignment[^<]*\((\d+) of (\d+) lines identical\)",
                  html)
    assert m, "evasion alignment section missing"
    assert int(m.group(1)) > 0, "no identical lines shown between hidden " \
        "and live code: {}".format(m.group(0))

    # column labels explain what each side is
    assert "commented-out code, unfolded" in html
    assert "live code" in html

    # executive summary names the signature explicitly
    assert "evasion signature" in html

    # and at least one matched (equal-class) diff row is rendered
    assert 'class="eq"' in html


def test_normal_dossier_unchanged(tmp_path):
    cfg, hidden, live = _subs(tmp_path)
    # a plain live-vs-live pair (no evasion promotion)
    live2 = build_submission("L2", "twin.py", str(tmp_path / "twin.py"),
                             BODY + "\n# small comment\n", cfg)
    pair = PairResult(
        roll_a="L1", roll_b="L2", file_a="live.py", file_b="twin.py",
        scores={"source": (0.99, None), "token": (0.9, 0.8),
                "ast": (0.9, 0.8), "shadow": (0.0, 0.0),
                "comment": (0.0, 0.0), "string": (0.9, 0.8)},
        blended=0.99, flag="HIGH_PROBABILITY_PLAGIARISM", evasion=0.0)
    out = tmp_path / "dossier2.html"
    write_dossier(out, live, live2, pair, cfg)
    html = out.read_text(encoding="utf-8")
    assert "Side-by-side comparison" in html
    assert "Evasion alignment" not in html
    m = re.search(r"\((\d+) of (\d+) lines identical\)", html)
    assert m and int(m.group(1)) > 0
