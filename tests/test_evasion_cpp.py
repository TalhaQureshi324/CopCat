"""C++ evasion golden: a whole C++ solution commented out (// hidden) is
matched against the live counterpart - the shadow channel must fire, the
pair must be evasion-promoted, and the dossier must align hidden-vs-live
C++ lines."""

import re

from copcat.channels import build_submission
from copcat.dossier import write_dossier
from copcat.models import AuditConfig
from copcat.audit import run_audit

BODY_LINES = [
    "int leafCount(TreeNode* node) {",
    "    if (node == nullptr) {",
    "        return 0;",
    "    }",
    "    if (node->left == nullptr && node->right == nullptr) {",
    "        return 1;",
    "    }",
    "    return leafCount(node->left) + leafCount(node->right);",
    "}",
    "",
    "int treeHeight(TreeNode* node) {",
    "    if (node == nullptr) {",
    "        return 0;",
    "    }",
    "    int lh = treeHeight(node->left);",
    "    int rh = treeHeight(node->right);",
    "    return 1 + (lh > rh ? lh : rh);",
    "}",
    "",
    "int treeDepth(TreeNode* node) {",
    "    if (node == nullptr) {",
    "        return -1;",
    "    }",
    "    int ld = treeDepth(node->left);",
    "    int rd = treeDepth(node->right);",
    "    return 1 + (ld > rd ? ld : rd);",
    "}",
    "",
    "void inorderPrint(TreeNode* node) {",
    "    if (node == nullptr) {",
    "        return;",
    "    }",
    "    inorderPrint(node->left);",
    "    cout << node->value << endl;",
    "    inorderPrint(node->right);",
    "}",
] * 3        # repeat so the folded shadow clears the 400-token bar


def _hidden_source():
    out = []
    for ln in BODY_LINES:
        out.append("// " + ln if ln.strip() else "")
    return "\n".join(out) + "\n"


def _live_source():
    return "\n".join(BODY_LINES) + "\n"


def test_cpp_evasion_promotion_and_dossier_alignment(tmp_path):
    hidden_src = _hidden_source()
    live_src = _live_source()
    h = build_submission("BSCS40101", "hidden_bscs40101.cpp",
                         str(tmp_path / "h.cpp"), hidden_src, AuditConfig())
    v = build_submission("BSCS40102", "live_bscs40102.cpp",
                         str(tmp_path / "v.cpp"), live_src, AuditConfig())
    assert h.notes, "hidden fixture must register as mostly-commented"
    assert len(h.shadow_tokens) >= 400, len(h.shadow_tokens)

    batch = tmp_path / "batch"
    batch.mkdir()
    (batch / "hidden_bscs40101.cpp").write_text(hidden_src, encoding="utf-8")
    (batch / "live_bscs40102.cpp").write_text(live_src, encoding="utf-8")
    pairs = run_audit(str(batch), AuditConfig(), str(tmp_path / "out"),
                      workers=1)
    assert len(pairs) == 1
    p = pairs[0]
    assert p.evasion >= 0.12, "evasion rule did not fire on the C++ hidden copy"
    assert p.flag == "HIGH_PROBABILITY_PLAGIARISM"
    assert p.blended >= 0.8            # identical code hidden vs live

    # dossier: hidden-vs-live alignment section renders C++ lines
    out = (tmp_path / "out" / "dossiers" /
           "dossier_BSCS40101__vs__BSCS40102.html")
    assert out.exists(), "dossier not generated"
    html = out.read_text(encoding="utf-8")
    assert "Evasion alignment" in html
    m = re.search(r"\((\d+) of (\d+) lines identical\)", html)
    assert m and int(m.group(1)) > 0
    assert "leafCount" in html          # actual C++ content aligned
