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


def test_commented_prose_next_to_live_match_is_not_evasion(tmp_path):
    """Regression: a mostly-commented file whose comments are PROSE (a task
    description) next to a strong live-code match must get the plain
    live-vs-live dossier - never an 'Evasion alignment' section."""
    prose = (
        "// Ask the user for the number of runners.\n"
        "// 1. Hours, minutes, and seconds if the margin is at least 1 hour.\n"
        "// 2. Minutes and seconds if the margin is less than 1 hour.\n"
        "// 3. Seconds only if the margin is less than 1 minute.\n"
        "// The program uses arrays, while loops, and if-else statements\n"
        "// to solve the problem and can work with different numbers of runners.\n"
        "// Step 1: read how many runners took part in the race.\n"
        "// Step 2: read the finish time of every runner one by one.\n"
        "// Step 3: find the runner with the smallest finish time.\n"
        "// Step 4: find the second smallest time among the remaining runners.\n"
        "// Step 5: compute the margin between winner and runner-up.\n"
        "// Step 6: print hours, minutes and seconds depending on the size\n"
        "// of the margin, using while loops for the counting.\n"
        "// The margin can also be printed only in seconds when it is small.\n"
        "#include <iostream>\n"
        "using namespace std;\n"
        "int main() {\n"
        '    cout << "done";\n'
        "    return 0;\n"
        "}\n")
    live = (
        "#include <iostream>\n"
        "using namespace std;\n"
        "int main() {\n"
        "    int index;\n"
        "    int RunnerTime[100];\n"
        '    cout << "Enter number of runners";\n'
        "    cin >> index;\n"
        '    cout << "Enter Finish Times";\n'
        "    for (int i = 0; i < index; i++) { cin >> RunnerTime[i]; }\n"
        "    int WinnerTime = RunnerTime[0];\n"
        "    for (int i = 1; i < index; i++) {\n"
        "        if (RunnerTime[i] < WinnerTime) { WinnerTime = RunnerTime[i]; }\n"
        "    }\n"
        "    cout << WinnerTime << endl;\n"
        "    return 0;\n"
        "}\n")
    cfg = AuditConfig()
    prose_sub = build_submission("BSCS26094", "bscs26094_task3.cpp",
                                 str(tmp_path / "p.cpp"), prose, cfg)
    live_sub = build_submission("BSCS26020", "bscs26020_task3.cpp",
                                str(tmp_path / "l.cpp"), live, cfg)
    assert prose_sub.notes, "fixture must be mostly-commented"

    pair = PairResult(
        roll_a="BSCS26094", roll_b="BSCS26020",
        file_a="bscs26094_task3.cpp", file_b="bscs26020_task3.cpp",
        scores={"source": (0.71, None), "token": (0.56, 0.3),
                "ast": (0.86, 0.5), "shadow": (0.0, 0.0),
                "comment": (0.0, 0.0), "string": (1.0, 0.6)},
        blended=0.862, flag="HIGH_PROBABILITY_PLAGIARISM", evasion=0.0)

    out = tmp_path / "dossier.html"
    write_dossier(out, prose_sub, live_sub, pair, cfg)
    html = out.read_text(encoding="utf-8")
    assert "Evasion alignment" not in html
    assert "Side-by-side comparison" in html
    assert "evasion signature" not in html


