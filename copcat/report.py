"""Report writers: pair CSV + human-readable audit TXT with evidence."""

import difflib
import time

CSV_HEADER = ["rank", "roll_a", "roll_b", "blended_pct", "flag",
              "source_pct", "token_pct", "ast_pct", "shadow_pct",
              "comment_pct", "string_pct"]


def _pct(x):
    return "{:.1f}%".format(100.0 * x) if x is not None else "-"


def _matched_blocks(sub_a, sub_b, min_len=6, max_blocks=3, max_lines=8, width=100):
    sm = difflib.SequenceMatcher(None, sub_a.effective_lines, sub_b.effective_lines,
                                 autojunk=False)
    out = []
    for m in sm.get_matching_blocks():
        if m.size >= min_len:
            blk = [ln[:width] for ln in sub_a.effective_lines[m.a:m.a + min(m.size, max_lines)]]
            out.append((m.size, blk))
        if len(out) >= max_blocks:
            break
    return out


def write_csv(path, pairs):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        fh.write(",".join(CSV_HEADER) + "\n")
        for rank, p in enumerate(pairs, 1):
            row = p.as_csv_row(rank)
            fh.write(",".join(str(x) for x in row) + "\n")


def write_txt(path, subs, pairs, clusters, cfg, started, damped=None,
              forensics=None, collisions=None):
    L = []
    ap = L.append
    bar = "=" * 78
    ap(bar)
    ap("COPCAT AUDIT REPORT")
    ap(bar)
    ap("Generated        : {}".format(time.strftime("%Y-%m-%d %H:%M:%S")))
    ap("Runtime          : {:.1f}s".format(time.time() - started))
    ap("Submissions      : {}".format(len(subs)))
    ap("Pairs compared   : {}".format(len(pairs)))
    ap("Settings         : k={} winnow={} comment-{}gram | SUS>{} HIGH>{}".format(
        cfg.k, cfg.window, cfg.comment_ngram, cfg.suspicious, cfg.high))
    ap("Starters         : {}".format(list(cfg.starters) or "none"))
    ap("Batch damper     : removed batch-common fingerprints (>=30% of files):")
    if damped:
        for ch, n in damped.items():
            ap("    {:<8} {}".format(ch, n))
    else:
        ap("    (none)")
    ap("Preserved names  : {}".format(
        ",".join(cfg.preserved) if cfg.preserved else
        "(builtins + dunders only)"))
    ap("")

    ap("-" * 78)
    ap("SECTION A - EVASION INDICATORS (commented-out code)")
    ap("-" * 78)
    flagged_ev = []
    for s in subs:
        total = max(s.n_comment_lines, 1)
        ratio = s.code_like_comment_lines / total
        if (ratio >= cfg.evasion_ratio and len(s.shadow_tokens) >= cfg.evasion_min_shadow):
            flagged_ev.append((ratio, s))
    flagged_ev.sort(reverse=True)
    if not flagged_ev:
        ap("No files with anomalous commented-out-code ratios.")
    for ratio, s in flagged_ev:
        ap("  {} : {:.0%} of comment lines are code-like; folded shadow stream "
           "= {} tokens{}".format(
               s.roll, ratio, len(s.shadow_tokens),
               "  [FILE MOSTLY COMMENTED OUT]" if s.notes else ""))
    ap("")

    ap("-" * 78)
    ap("SECTION B - FLAGGED PAIRS (blended >= {:.0%}), ranked".format(cfg.suspicious))
    ap("-" * 78)
    flagged = [p for p in pairs if p.blended >= cfg.suspicious]
    if not flagged:
        ap("No pairs crossed the suspicion threshold.")
    sub_by_roll = {s.roll: s for s in subs}
    for p in flagged:
        ap("")
        ap("Pair: {} vs {}   blended {}  [{}]".format(
            p.roll_a, p.roll_b, _pct(p.blended), p.flag))
        s = p.scores
        ap("   source-line {} | token {} | ast {} | shadow {} | comment {} | string {}".format(
            _pct(s["source"][0]), _pct(s["token"][0]), _pct(s["ast"][0]),
            _pct(s["shadow"][0]), _pct(s["comment"][0]), _pct(s["string"][0])))
        for ev in p.evidence:
            ap("   >> " + ev)
        sa, sb = sub_by_roll.get(p.roll_a), sub_by_roll.get(p.roll_b)
        if sa and sb:
            for size, blk in _matched_blocks(sa, sb):
                ap("   [{} identical code lines]".format(size))
                for ln in blk:
                    ap("      | " + ln)
    ap("")

    ap("-" * 78)
    ap("SECTION C - TOP {} PAIRS BY BLENDED SCORE (all channels)".format(
        min(40, len(pairs))))
    ap("-" * 78)
    ap("{:>4} {:<12} {:<12} {:>8} {:>8} {:>8} {:>8} {:>8} {:>8} {:>8}".format(
        "#", "A", "B", "BLEND", "SRC", "TOKEN", "AST", "SHDW", "COMM", "STR"))
    for i, p in enumerate(pairs[:40], 1):
        s = p.scores
        ap("{:>4} {:<12} {:<12} {:>8} {:>8} {:>8} {:>8} {:>8} {:>8} {:>8}".format(
            i, p.roll_a, p.roll_b, _pct(p.blended), _pct(s["source"][0]),
            _pct(s["token"][0]), _pct(s["ast"][0]), _pct(s["shadow"][0]),
            _pct(s["comment"][0]), _pct(s["string"][0])))
    ap("")

    ap("-" * 78)
    ap("SECTION D - CLUSTERS (connected components of flagged pairs)")
    ap("-" * 78)
    if not clusters:
        ap("No clusters — flagged pairs are isolated.")
    for i, members in enumerate(clusters, 1):
        ap("  Cluster {} (size {}): {}".format(i, len(members), ", ".join(members)))
    ap("")

    ap("-" * 78)
    ap("SECTION D2 - FORENSICS (submission provenance artifacts)")
    ap("-" * 78)
    if forensics:
        with_notebook = [(roll, info) for roll, info in sorted(forensics.items())
                         if info["colab_ids"] or info["drive_ids"]
                         or info["generator"] or info["ipython_artifacts"]]
        ap("{} of {} submissions carry provenance metadata:".format(
            len(with_notebook), len(forensics)))
        for roll, info in with_notebook:
            bits = []
            if info["colab_ids"]:
                bits.append("colab notebook id " + ", ".join(info["colab_ids"]))
            if info["drive_ids"]:
                bits.append("drive file id " + ", ".join(info["drive_ids"]))
            if info["generator"]:
                bits.append("generated by " + info["generator"])
            if info["ipython_artifacts"]:
                bits.append("IPython artifacts")
            ap("  {:<12} {}".format(roll, "; ".join(bits)))
    else:
        ap("No provenance metadata found.")
    if collisions:
        ap("")
        ap("!! SHARED NOTEBOOK IDs (same source notebook passed between students):")
        for kind, nid, rolls in collisions:
            ap("  {} `{}` -> {}".format(kind, nid, ", ".join(rolls)))
    else:
        ap("No notebook/drive IDs are shared between students.")
    ap("")

    ap("-" * 78)
    ap("SECTION E - METHOD NOTES & CAVEATS")
    ap("-" * 78)
    ap("* Source channel = max(char-ratio of comment-stripped stream, char-ratio")
    ap("  of raw file), difflib defaults. Calibrated on a 47-file ground truth:")
    ap("  known collusion pairs scored 52-67%, known-clean family pairs <=56%.")
    ap("* Raw whole-file similarity CANNOT by itself distinguish collusion from")
    ap("  a circulating shared base; always read flags together with the")
    ap("  per-channel breakdown, the evasion indicators, and the clusters.")
    ap("* Shadow channel folds commented-out code back into matching; a high")
    ap("  shadow score with low source score means the overlap lives inside")
    ap("  comments (classic MOSS-evasion). Evasion matches require a large")
    ap("  folded shadow (>=400 tokens) and >=12% alignment with live code.")
    ap("* AST channel uses scope-aware canonical renaming with preserved symbols;")
    ap("  it is insensitive to variable/method renaming but sensitive to the")
    ap("  mandated interface skeleton, so moderate ast values are expected.")
    ap("* Batch damper strips fingerprints present in >=30% of submissions from")
    ap("  token/ast/shadow/comment/string channels before comparison.")
    ap("* Thresholds are defaults; recalibrate with --sus/--high against your")
    ap("  own ground truth before disciplinary use.")

    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
