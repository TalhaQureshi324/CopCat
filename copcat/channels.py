"""Build all fingerprint channels for a submission, with optional
starter/base-code subtraction (MOSS `-b` equivalent)."""

from .lexing import lex, normalize_words, TOKEN_RE
from .canon import canonical_tokens
from .shadow import fold_comments, CODE_LIKE_RE, _strip_hash
from .normal import fingerprint, fingerprint_adaptive, word_shingles

WINNOW_CHANNELS = ("token", "ast", "shadow")
SHINGLE_CHANNELS = ("comment", "string")


def is_code_like_line(raw):
    s = _strip_hash(raw)
    return bool(s) and bool(CODE_LIKE_RE.match(s))


def build_submission(roll, filename, path, source, cfg):
    from .models import Submission

    sub = Submission(roll=roll, filename=filename, path=path, source=source)
    sub.n_lines = sum(1 for _ in source.splitlines())
    tokens, comments, strings, code_lines, _ = lex(source)
    sub.tokens = tokens
    sub.n_comment_lines = len(comments)
    sub.n_code_lines = len(code_lines)

    # shadow stream: fold commented-out code (prose stays out); literals
    # inside commented-out code join the string channel
    shadow_tokens, shadow_strings, code_like, _total = fold_comments(comments)
    sub.shadow_tokens = shadow_tokens
    sub.code_like_comment_lines = code_like

    # prose channels
    sub.comment_words = normalize_words(" ".join(t for _, t in comments))
    sub.string_words = normalize_words(" ".join(list(strings) + list(shadow_strings)))

    # canonical AST channel (fault-tolerant parse inside)
    sub.canonical_tokens, sub.parse_ok, sub.chunks_failed = \
        canonical_tokens(source, preserved=())  # audit: rename-invariant

    # source-line channel: token-stripped lines; if the file is mostly
    # comments, fall back to decommented CODE-LIKE lines only (prose lines
    # stay in the comment channel) so hidden code aligns against live code
    nonblank = sum(1 for _ in source.splitlines() if _.strip())
    if len(code_lines) < 0.30 * max(nonblank, 1):
        sub.effective_lines = [
            " ".join(TOKEN_RE.findall(_strip_hash(ln)))
            for ln in source.splitlines() if is_code_like_line(ln)]
        sub.notes.append("mostly-commented file; shadow/decomment stream used")
    else:
        sub.effective_lines = code_lines
    sub.code_text = "\n".join(sub.effective_lines)

    # fingerprints
    sub.fps["token"] = fingerprint_adaptive(tokens, cfg.k, cfg.window)
    # k=8 for the AST channel: canonical numbering drifts by one after any
    # rename-count difference, and k=16 windows would shatter around every
    # drift point. Finer granularity tolerates that; the batch damper still
    # removes generic structural k-grams.
    sub.fps["ast"] = fingerprint_adaptive(sub.canonical_tokens,
                                           min(cfg.k, 8), max(2, cfg.window // 2))
    sub.fps["shadow"] = fingerprint_adaptive(shadow_tokens, cfg.k, cfg.window)
    sub.fps["comment"] = word_shingles(sub.comment_words, cfg.comment_ngram)
    sub.fps["string"] = word_shingles(sub.string_words, cfg.comment_ngram)
    return sub


def decomment_lines(src):
    """Strip leading comment markers from every line (for mostly-commented
    files), keeping non-empty lines."""
    out = []
    for ln in src.splitlines():
        s = ln.strip()
        while s.startswith("#"):
            s = s.lstrip("#").strip()
        if s:
            out.append(" ".join(TOKEN_RE.findall(s)))
    return out


def build_starter_profile(starter_sources, cfg):
    """Union of all starter-code fingerprints + normalized line set."""
    fps = {ch: set() for ch in WINNOW_CHANNELS + SHINGLE_CHANNELS}
    lines = set()
    for src in starter_sources:
        tokens, comments, strings, code_lines, _ = lex(src)
        shadow_tokens, shadow_strings, _cl, _t = fold_comments(comments)
        canon, _ok, _f = canonical_tokens(src, preserved=())
        fps["token"] |= fingerprint_adaptive(tokens, cfg.k, cfg.window)
        fps["ast"] |= fingerprint_adaptive(canon, cfg.k, cfg.window)
        fps["shadow"] |= fingerprint_adaptive(shadow_tokens, cfg.k, cfg.window)
        fps["comment"] |= word_shingles(normalize_words(" ".join(t for _, t in comments)),
                                        cfg.comment_ngram)
        fps["string"] |= word_shingles(normalize_words(" ".join(list(strings) + list(shadow_strings))),
                                       cfg.comment_ngram)
        for ln in code_lines:
            lines.add(" ".join(ln.split()))
        for ln in source_code_lines(src):
            lines.add(" ".join(ln.split()))
    return {"fps": fps, "lines": lines}


def source_code_lines(src):
    """Token-stripped code lines; code-like decommented lines when the file
    is mostly comments (mirrors build_submission's source channel)."""
    tokens, comments, strings, code_lines, _ = lex(src)
    nonblank = sum(1 for _ in src.splitlines() if _.strip())
    if len(code_lines) < 0.30 * max(nonblank, 1):
        return [" ".join(TOKEN_RE.findall(_strip_hash(ln)))
                for ln in src.splitlines() if is_code_like_line(ln)]
    return code_lines


def subtract_starter(sub, profile):
    """Remove starter fingerprints/lines from a submission (base-code damper)."""
    for ch in WINNOW_CHANNELS + SHINGLE_CHANNELS:
        sub.fps[ch] = sub.fps[ch] - profile["fps"][ch]
    starter_lines = profile["lines"]
    sub.effective_lines = [ln for ln in sub.effective_lines
                           if " ".join(ln.split()) not in starter_lines]


def apply_batch_damper(subs, cfg, min_docs=3):
    """Remove fingerprints shared by too much of the batch (mandated
    skeleton / manual boilerplate), so common template code can't manufacture
    similarity. The AST channel uses a stricter bar (see
    AuditConfig.damp_share_ast) or rename-invariance evidence would be
    erased wherever a third submission happens to duplicate the same
    structure. Returns {channel: removed_count}."""
    n = len(subs)
    removed = {}
    for ch in WINNOW_CHANNELS + SHINGLE_CHANNELS:
        share = cfg.damp_share_ast if ch == "ast" else cfg.damp_share
        cutoff = max(min_docs, int(round(share * n)))
        df = {}
        for s in subs:
            for h in s.fps[ch]:
                df[h] = df.get(h, 0) + 1
        common = {h for h, c in df.items() if c >= cutoff}
        if common:
            for s in subs:
                s.fps[ch] -= common
        removed[ch] = len(common)
    return removed


def build_consensus_lines(subs, share=0.30, min_docs=3):
    """Normalized lines present in >= share of the batch = circulating
    skeleton. These are subtracted from the source-line channel so whole-file
    similarity reflects pair-specific overlap, not shared template code."""
    n = len(subs)
    cutoff = max(min_docs, int(round(share * n)))
    df = {}
    for s in subs:
        seen = {" ".join(ln.split()) for ln in s.effective_lines}
        for ln in seen:
            df[ln] = df.get(ln, 0) + 1
    return {ln for ln, c in df.items() if c >= cutoff}


def subtract_consensus_lines(sub, consensus):
    sub.effective_lines = [ln for ln in sub.effective_lines
                           if " ".join(ln.split()) not in consensus]
