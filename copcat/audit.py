"""`copcat audit` orchestrator: ingest -> channels -> starter subtraction ->
pairwise comparison -> clustering -> reports."""

import os
import time

from .models import AuditConfig
from .ingest import load_sources
from .channels import (build_submission, build_starter_profile,
                       subtract_starter, apply_batch_damper)
from .compare import compare_all
from .cluster import clusters_from_pairs
from .forensics import build_forensics, apply_forensics_to_pairs
from . import report as report_mod


def run_audit(directory, cfg, out_dir, workers=1):
    started = time.time()
    os.makedirs(out_dir, exist_ok=True)

    rows = load_sources(directory)
    if not rows:
        print("No .py submissions found in {}".format(directory))
        return []

    subs = []
    for path, roll, fname, src in rows:
        subs.append(build_submission(roll, fname, path, src, cfg))

    # starter/base-code subtraction
    if cfg.starters:
        starter_srcs = []
        for sp in cfg.starters:
            if os.path.isdir(sp):
                for name in sorted(os.listdir(sp)):
                    if name.endswith(".py"):
                        with open(os.path.join(sp, name),
                                  encoding="utf-8-sig", errors="replace") as fh:
                            starter_srcs.append(fh.read())
            else:
                with open(sp, encoding="utf-8-sig", errors="replace") as fh:
                    starter_srcs.append(fh.read())
        profile = build_starter_profile(starter_srcs, cfg)
        for s in subs:
            subtract_starter(s, profile)

    # batch-common damper: strip fingerprints present in >=30% of the batch
    damped = apply_batch_damper(subs, cfg)

    pairs = compare_all(subs, cfg, workers=workers)

    # forensics: shared notebook/drive IDs are definitive regardless of metrics
    forensics, collisions = build_forensics(subs)
    if collisions:
        pairs = apply_forensics_to_pairs(pairs, collisions)
        pairs.sort(key=lambda r: r.blended, reverse=True)
    clusters = clusters_from_pairs(pairs, cfg.suspicious)

    csv_path = os.path.join(out_dir, "copcat_audit.csv")
    txt_path = os.path.join(out_dir, "copcat_audit.txt")
    html_path = os.path.join(out_dir, "index.html")
    report_mod.write_csv(csv_path, pairs)
    report_mod.write_txt(txt_path, subs, pairs, clusters, cfg, started,
                         damped=damped, forensics=forensics,
                         collisions=collisions)
    try:
        from .webreport import write_html_report
        write_html_report(html_path, subs, pairs, clusters, cfg,
                          forensics=forensics, collisions=collisions)
        print("Wrote {}".format(html_path))
    except Exception as exc:            # the HTML dashboard must never break the audit
        print("HTML report skipped: {}".format(exc))

    n_susp = sum(1 for p in pairs if p.flag == "SUSPICIOUS")
    n_high = sum(1 for p in pairs if p.flag == "HIGH_PROBABILITY_PLAGIARISM")
    print("Submissions : {}".format(len(subs)))
    print("Pairs       : {}".format(len(pairs)))
    print("Flags       : {} SUSPICIOUS, {} HIGH_PROBABILITY_PLAGIARISM".format(
        n_susp, n_high))
    print("Clusters    : {}".format(len(clusters)))
    if pairs:
        print("Top match   : {} vs {} at {:.1%} [{}]".format(
            pairs[0].roll_a, pairs[0].roll_b, pairs[0].blended, pairs[0].flag))
    ev = [s.roll for s in subs
          if s.code_like_comment_lines / max(s.n_comment_lines, 1) >= cfg.evasion_ratio
          and len(s.shadow_tokens) >= cfg.evasion_min_shadow]
    if ev:
        print("Evasion candidates (commented-out code): {}".format(", ".join(ev)))
    print("Wrote {}".format(csv_path))
    print("Wrote {}".format(txt_path))
    return pairs
