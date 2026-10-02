"""Fingerprint math: stable k-gram hashing, winnowing (MOSS's algorithm),
shingling for word streams, and set-similarity metrics. Hashing uses
blake2b so fingerprints are stable across runs (unlike builtin hash())."""

import hashlib

_SEP = "\x1f"


def _hash(kgram):
    payload = _SEP.join(kgram).encode("utf-8", "replace")
    return int.from_bytes(hashlib.blake2b(payload, digest_size=8).digest(), "big")


def kgram_hashes(tokens, k):
    if not tokens:
        return []
    if len(tokens) < k:
        return [_hash(tuple(tokens))]
    return [_hash(tokens[i:i + k]) for i in range(len(tokens) - k + 1)]


def winnow(hashes, w):
    """Winnowing: keep the (rightmost) min hash of every sliding window."""
    if not hashes:
        return set()
    if len(hashes) <= w:
        return set(hashes)
    fp = set()
    for i in range(len(hashes) - w + 1):
        window = hashes[i:i + w]
        m = min(window)
        idx = len(window) - 1 - window[::-1].index(m)  # rightmost min
        fp.add(window[idx])
    return fp


def fingerprint(tokens, k, w):
    return winnow(kgram_hashes(tokens, k), w)


def full_kgram_set(tokens, k):
    """Unsampled k-gram set — the exact similarity denominator for typical
    file sizes. Winnowing only guarantees a shared region is *detected*
    (some fingerprint shared); its window samples drift on same-length
    rewrites, so set containment undercounts renamed copies. Full sets do
    not, and are cheap up to a few thousand tokens."""
    return set(kgram_hashes(tokens, k))


def fingerprint_adaptive(tokens, k, w, full_set_cap=4000):
    if len(tokens) <= full_set_cap:
        return full_kgram_set(tokens, k)
    return winnow(kgram_hashes(tokens, k), w)


def word_shingles(words, n):
    if not words:
        return set()
    if len(words) < n:
        return {" ".join(words)}
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


def containment(a, b):
    """Fraction of the smaller set found in the larger (asymmetric, stable)."""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def jaccard(a, b):
    if not a and not b:
        return 0.0
    u = len(a | b)
    return len(a & b) / u if u else 0.0
