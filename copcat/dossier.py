"""Misconduct evidence packets: a printable, self-contained HTML dossier per
flagged pair, written for academic-integrity committees.

Contents: plain-English executive summary (auto-composed from measured
evidence - never speculation), per-channel similarity table, side-by-side
color-coded diff, renamed-identifier table, shared literal fingerprints,
forensics (shared notebook IDs), and a methodology appendix. Print to PDF
with the browser (Ctrl+P); print CSS renders it cleanly on A4.
"""

import difflib
import os
import shutil
import time

from .webreport import (_CSS, _diff_rows, _esc, _flag_span,
                        _rename_evidence)

_PRINT_CSS = """
@media print {
  body { background: #fff; font-size: 11px; }
  .page-break { page-break-before: always; }
  header { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  .no-print { display: none; }
  .diffwrap { max-height: none; overflow: visible; }
}
.dossier { background: #fff; border: 1px solid #dcdde1; padding: 18px 22px; margin: 14px 0; }
.dossier h3 { margin: 14px 0 6px; font-size: 14px; color: #2c3e50; }
.summary li { margin: 4px 0; }
.verdict { font-size: 15px; font-weight: 600; padding: 10px 14px; background: #fdecea;
           border-left: 5px solid #c0392b; margin: 10px 0; }
"""


def _executive_summary(pair, sub_a, sub_b, cfg, renames, shared_lits):
    """Plain-English summary composed strictly from measured evidence."""
    s = pair.scores
    statements = []
    statements.append(
        "Submissions {} ({}) and {} ({}) were compared across six independent "
        "similarity channels.".format(sub_a.roll, sub_a.filename,
                                      sub_b.roll, sub_b.filename))
    statements.append(
        "Overall blended similarity measured {:.0f}%; the source-code channel "
        "alone measured {:.0f}% (threshold for suspicion: {:.0f}%).".format(
            100 * pair.blended, 100 * s["source"][0], 100 * cfg.suspicious))
    if renames:
        sample = ", ".join("{} &harr; {}".format(a, b) for (a, b), _n in renames[:4])
        statements.append(
            "{} identifier positions match one-to-one with different names on "
            "either side (e.g. {}), consistent with a variable-renamed copy."
            .format(len(renames), sample))
    if shared_lits:
        statements.append(
            "The two files share {} distinctive string-literal words (test "
            "values, messages and demo data).".format(len(shared_lits)))
    for e in pair.evidence:
        statements.append(e.replace("evasion match:", "Evasion indicator -")
                          .replace("forensics:", "Forensics -"))
    n_blocks = len(_matched_block_count(sub_a, sub_b))
    if n_blocks:
        statements.append(
            "{} contiguous blocks of identical code lines were located in the "
            "side-by-side comparison below.".format(n_blocks))
    statements.append(
        "Both files implement the same assigned tasks; the shared assignment "
        "skeleton was statistically removed before scoring (batch damper), so "
        "the measured overlap reflects the submissions themselves.")
    items = "".join("<li>{}</li>".format(x) for x in statements)
    verdict = (
        "The measured evidence is consistent with the two submissions sharing "
        "authorship beyond the assignment template. It is recommended that the "
        "academic integrity process review this dossier together with any "
        "draft history the students can provide.")
    return ("<ul class='summary'>" + items + "</ul>"
            "<div class='verdict'>" + _esc(verdict) + "</div>")


def _matched_block_count(sub_a, sub_b):
    sm = difflib.SequenceMatcher(None, sub_a.effective_lines,
                                 sub_b.effective_lines, autojunk=False)
    return [m for m in sm.get_matching_blocks() if m.size >= 6]


def write_dossier(path, sub_a, sub_b, pair, cfg, lab="the assignment"):
    s = pair.scores
    map_tbl, n_renames, renames = _rename_evidence(sub_a.effective_lines,
                                                   sub_b.effective_lines,
                                                   limit=12)
    shared_lits = sorted(set(sub_a.string_words) & set(sub_b.string_words))
    rows_html, eq, tot, truncated = _diff_rows(
        sub_a.effective_lines, sub_b.effective_lines)

    now = time.strftime("%Y-%m-%d %H:%M")
    chan_rows = "".join(
        "<tr><td>{}</td><td>{:.1f}%</td></tr>".format(_esc(name), 100 * val)
        for name, val in (
            ("Source code (chars)", s["source"][0]),
            ("Token fingerprints", s["token"][0]),
            ("AST structure (rename-invariant)", s["ast"][0]),
            ("Commented-out code shadow", s["shadow"][0]),
            ("Comment prose", s["comment"][0]),
            ("String literals", s["string"][0])))
    lit_html = " ".join("<span class='badge lit'>{}</span>".format(_esc(w))
                        for w in shared_lits[:60])

    page = ("<!DOCTYPE html><html><head><meta charset='utf-8'>"
            "<title>Evidence dossier: {a} vs {b}</title><style>{css}{pcss}"
            "</style></head><body>"
            "<header><h1>Misconduct Evidence Dossier</h1>"
            "<div class='sub'>CopCat deterministic analysis &middot; generated "
            "{now} &middot; lab: {lab}</div></header><main>"
            "<div class='dossier'><h3>1. Parties</h3>"
            "<table><tr><th>Student A</th><th>Submission file</th></tr>"
            "<tr><td>{ra}</td><td>{fa}</td></tr>"
            "<tr><th>Student B</th><th>Submission file</th></tr>"
            "<tr><td>{rb}</td><td>{fb}</td></tr></table>"
            "<h3>2. Executive summary</h3>{summary}"
            "<h3>3. Verdict</h3>{verdict_span}"
            "</div>"
            "<div class='page-break'></div>"
            "<div class='dossier'><h3>4. Measured similarity by channel</h3>"
            "<table><tr><th>Channel</th><th>Score</th></tr>{chan}</table>"
            "<p class='note'>Blended verdict: {blended:.1f}% &mdash; {flag}</p>"
            "{evidence}</div>"
            "<div class='page-break'></div>"
            "<div class='dossier'><h3>5. Renamed identifiers "
            "({n} one-to-one swaps)</h3>{maptbl}"
            "<h3>6. Shared string literals</h3>{lits}</div>"
            "<div class='page-break'></div>"
            "<div class='dossier'><h3>7. Side-by-side comparison "
            "({eq} of {tot} lines identical)</h3>"
            "<div class='diffwrap'><table class='diff'>"
            "<tr><th class='ln'>A#</th><th>{ra}</th>"
            "<th class='ln'>B#</th><th>{rb}</th></tr>{rows}</table></div></div>"
            "<div class='page-break'></div>"
            "<div class='dossier'><h3>8. Methodology (for the committee)</h3>"
            "<p>All measurements are deterministic program analysis - no "
            "machine-learning or AI judging was involved. Scores are computed "
            "from token fingerprints, an AST canonicalization that is "
            "insensitive to variable renaming, comment/string-literal "
            "comparison, and a shadow channel that folds commented-out code "
            "back into matching. The assignment's own starter code and any "
            "code shared by 30%+ of the batch are excluded before scoring. "
            "Thresholds: similarity above {sus:.0f}% is flagged SUSPICIOUS; "
            "above {high:.0f}% HIGH_PROBABILITY.</p>"
            "<p class='note'>Generated by CopCat on {now}. This document "
            "contains evidence, not conclusions; the determination of "
            "responsibility belongs to the committee.</p></div>"
            "</main></body></html>").format(
        a=_esc(sub_a.roll), b=_esc(sub_b.roll),
        ra=_esc(sub_a.roll), rb=_esc(sub_b.roll),
        fa=_esc(sub_a.filename), fb=_esc(sub_b.filename),
        css=_CSS, pcss=_PRINT_CSS, now=_esc(now), lab=_esc(lab),
        summary=_executive_summary(pair, sub_a, sub_b, cfg,
                               renames, shared_lits),
        verdict_span=_flag_span(pair.flag),
        chan=chan_rows, blended=100 * pair.blended, flag=_esc(pair.flag),
        evidence="".join("<div class='evidence'>{}</div>".format(_esc(e))
                         for e in pair.evidence),
        n=n_renames, maptbl=map_tbl or "<p class='note'>None detected.</p>",
        lits=lit_html or "<p class='note'>None.</p>",
        eq=eq, tot=tot, rows=rows_html,
        sus=100 * cfg.suspicious, high=100 * cfg.high)

    with open(path, "w", encoding="utf-8") as fh:
        fh.write(page)


def generate_dossiers(out_dir, subs, pairs, cfg, lab="the assignment"):
    """Write a dossier for every flagged pair; returns [paths]."""
    dossier_dir = os.path.join(out_dir, "dossiers")
    os.makedirs(dossier_dir, exist_ok=True)
    by_roll = {s.roll: s for s in subs}
    paths = []
    for p in pairs:
        if p.flag == "CLEAN":
            continue
        sa, sb = by_roll.get(p.roll_a), by_roll.get(p.roll_b)
        if not sa or not sb:
            continue
        path = os.path.join(dossier_dir,
                            "dossier_{}__vs__{}.html".format(p.roll_a, p.roll_b))
        write_dossier(path, sa, sb, p, cfg, lab=lab)
        paths.append(path)
    return paths
