"""Pairwise comparison across channels + blended verdict.

Calibration (validated against the 47-file Lab 02 ground truth):
* source channel = max(char-ratio on comment-stripped code stream, char-ratio
  on raw source), difflib defaults (autojunk on). The autojunk popularity
  heuristic empirically discounts batch-consensus boilerplate and cleanly
  separated known collusion pairs (52-67%) from clean family pairs (<=56%);
  autojunk=False measures the circulating shared base instead and cannot
  separate them.
* shadow channel folds commented-out code; a mostly-commented file whose
  shadow matches another student's live code is an evasion match.
* token/ast channels are post-damper containments (boilerplate removed).
"""

import difflib

from .normal import containment, jaccard


def compare_pair(a, b, cfg):
    from .models import PairResult

    scores = {}
    for ch in ("token", "ast", "comment", "string"):
        fa, fb = a.fps[ch], b.fps[ch]
        scores[ch] = (containment(fa, fb), jaccard(fa, fb))

    # shadow channel: folded commented-out code of one side vs the live
    # code (token stream) of the other. Every direction requires a
    # substantial shadow (min token count) so a single code-like comment
    # can't produce a 1/1 = 100% containment.
    enough = cfg.evasion_min_shadow
    directions = []
    if len(a.shadow_tokens) >= enough:
        directions.append(containment(
            a.fps["shadow"], b.fps["token"] | b.fps["shadow"]))
    if len(b.shadow_tokens) >= enough:
        directions.append(containment(
            b.fps["shadow"], a.fps["token"] | a.fps["shadow"]))
    if len(a.shadow_tokens) >= enough and len(b.shadow_tokens) >= enough:
        directions.append(containment(a.fps["shadow"], b.fps["shadow"]))
    shadow_direct = max(directions) if directions else 0.0
    scores["shadow"] = (shadow_direct, jaccard(a.fps["shadow"], b.fps["shadow"]))

    # source channel: char-ratio with difflib defaults (fast + calibrated),
    # max over comment-stripped stream and raw source
    src_code = difflib.SequenceMatcher(None, a.code_text, b.code_text).ratio()
    src_raw = difflib.SequenceMatcher(None, a.source, b.source).ratio()
    scores["source"] = (max(src_code, src_raw), None)

    # evasion-match rule: a mostly-commented file whose folded code shadow
    # lines up with another student's live code = MOSS-evasion signature.
    # Unrelated files sit at ~1-8% shadow containment, so >=15% with a large
    # folded shadow is decisive evidence; >=25% escalates to HIGH.
    blended = max(
        scores["source"][0],
        scores["token"][0],
        scores["ast"][0],
        shadow_direct,
    )
    evidence = []
    big_shadow = max(len(a.shadow_tokens), len(b.shadow_tokens))
    mostly_commented = bool(a.notes or b.notes)
    evasion = (mostly_commented and big_shadow >= cfg.evasion_big_shadow
               and shadow_direct >= cfg.evasion_shadow_min)
    if evasion:
        who = a.roll if len(a.shadow_tokens) == big_shadow else b.roll
        evidence.append(
            "evasion match: commented-out code shadow of {} aligns with live "
            "code at {:.0%} ({} folded tokens; unrelated pairs sit at ~1-8%)"
            .format(who, shadow_direct, big_shadow))
        if shadow_direct >= cfg.evasion_shadow_min + 0.10:
            blended = max(blended, cfg.high)
        else:
            blended = max(blended, cfg.suspicious)

    if blended >= cfg.high:
        flag = "HIGH_PROBABILITY_PLAGIARISM"
    elif blended >= cfg.suspicious:
        flag = "SUSPICIOUS"
    else:
        flag = "CLEAN"

    return PairResult(
        roll_a=a.roll, roll_b=b.roll,
        file_a=a.filename, file_b=b.filename,
        scores=scores, blended=blended, flag=flag, evidence=evidence,
    )


def compare_all(subs, cfg, workers=1):
    jobs = []
    n = len(subs)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = subs[i], subs[j]
            if (len(a.effective_lines) < cfg.min_lines
                    or len(b.effective_lines) < cfg.min_lines):
                continue
            jobs.append((a, b))

    if workers and workers > 1 and len(jobs) > 64:
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(max_workers=workers) as ex:
            results = list(ex.map(_compare_job,
                                  [(a, b, cfg) for a, b in jobs]))
    else:
        results = [compare_pair(a, b, cfg) for a, b in jobs]

    results.sort(key=lambda r: r.blended, reverse=True)
    return results


def _compare_job(args):
    """Top-level worker so ProcessPoolExecutor can pickle it (Windows spawn)."""
    a, b, cfg = args
    return compare_pair(a, b, cfg)
