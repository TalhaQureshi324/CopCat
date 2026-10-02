"""copcat command-line interface."""

import argparse
import os
import sys

from .models import AuditConfig
from .audit import run_audit


def build_parser():
    p = argparse.ArgumentParser(
        prog="copcat",
        description="Deterministic lab grading + multi-channel plagiarism audit.")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("audit", help="plagiarism audit over a folder of .py files")
    a.add_argument("directory", help="folder containing student .py submissions")
    a.add_argument("--starter", action="append", default=[],
                   help="starter/base-code file or dir to subtract (repeatable)")
    a.add_argument("--preserve", default="",
                   help="comma-separated rubric interface names to never canonicalize")
    a.add_argument("--k", type=int, default=16, help="k-gram size in tokens (default 16)")
    a.add_argument("--window", type=int, default=8, help="winnowing window (default 8)")
    a.add_argument("--comment-ngram", type=int, default=5, dest="comment_ngram")
    a.add_argument("--sus", type=float, default=0.60, help="suspicious threshold")
    a.add_argument("--high", type=float, default=0.80, help="high-probability threshold")
    a.add_argument("--min-lines", type=int, default=15, dest="min_lines")
    a.add_argument("--workers", type=int, default=0,
                   help="parallel workers for pairwise comparison "
                        "(0 = auto: one per CPU core; 1 = single process)")
    a.add_argument("--out", default="reports", help="output directory")

    g = sub.add_parser("grade", help="grade submissions against a YAML rubric")
    g.add_argument("directory")
    g.add_argument("--rubric", required=True, help="path to rubric YAML")
    g.add_argument("--timeout", type=float, default=None,
                   help="override sandbox timeout per submission (seconds)")
    g.add_argument("--memory", type=int, default=None,
                   help="override sandbox memory cap (MB)")
    g.add_argument("--out", default="grade_report.csv", help="output CSV path")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)

    if args.cmd == "grade":
        from .rubric import run_grade
        run_grade(os.path.abspath(args.directory), args.rubric,
                  os.path.abspath(args.out), timeout_s=args.timeout,
                  memory_mb=args.memory)
        return

    cfg = AuditConfig(
        k=args.k,
        window=args.window,
        comment_ngram=args.comment_ngram,
        suspicious=args.sus,
        high=args.high,
        min_lines=args.min_lines,
        preserved=tuple(x.strip() for x in args.preserve.split(",") if x.strip()),
        starters=tuple(args.starter),
    )
    directory = os.path.abspath(args.directory)
    out_dir = os.path.abspath(args.out)
    workers = args.workers
    if workers <= 0:
        workers = os.cpu_count() or 1
    run_audit(directory, cfg, out_dir, workers=workers)


if __name__ == "__main__":
    main()
