"""Core data models for CopCat."""

from dataclasses import dataclass, field


@dataclass
class AuditConfig:
    k: int = 16                  # tokens per k-gram (code channels)
    window: int = 8              # winnowing window
    comment_ngram: int = 5       # words per shingle (comment/string channels)
    suspicious: float = 0.60     # flag threshold
    high: float = 0.80           # high-probability threshold
    confirm_min: float = 0.45    # prefilter bar for expensive confirmations
    evasion_shadow_min: float = 0.15  # shadow-vs-live containment for evasion match
    evasion_big_shadow: int = 400     # folded shadow tokens for evasion match
    min_lines: int = 15          # skip pairs where a side has fewer code lines
    preserved: tuple = ()        # interface names never canonicalized
    starters: tuple = ()         # starter/base-code files (subtracted)
    evasion_ratio: float = 0.25  # code-like comment lines / total comments
    evasion_min_shadow: int = 40 # min folded shadow tokens to report evasion


@dataclass
class Submission:
    roll: str
    filename: str
    path: str
    source: str
    n_lines: int = 0
    n_comment_lines: int = 0
    n_code_lines: int = 0
    # channel streams
    tokens: list = field(default_factory=list)          # code tokens (strings kept)
    canonical_tokens: list = field(default_factory=list)  # AST-canonical stream
    comment_words: list = field(default_factory=list)   # normalized prose words
    string_words: list = field(default_factory=list)    # normalized literal words
    shadow_tokens: list = field(default_factory=list)   # folded commented-out code
    effective_lines: list = field(default_factory=list) # comment-stripped code lines
    code_text: str = ""                                 # "\n"-joined effective lines
    # stats / diagnostics
    code_like_comment_lines: int = 0
    parse_ok: bool = True
    chunks_failed: int = 0
    notes: list = field(default_factory=list)
    fps: dict = field(default_factory=dict)             # channel -> fingerprint set


@dataclass
class PairResult:
    roll_a: str
    roll_b: str
    file_a: str
    file_b: str
    scores: dict = field(default_factory=dict)  # channel -> (containment, jaccard)
    blended: float = 0.0
    flag: str = "CLEAN"
    evidence: list = field(default_factory=list)

    def as_csv_row(self, rank: int) -> list:
        def pct(x):
            return "{:.1f}".format(100.0 * x) if x is not None else ""
        s = self.scores
        src = s.get("source", (None, None))[0]
        return [
            rank, self.roll_a, self.roll_b, pct(self.blended), self.flag,
            pct(src),
            pct(s.get("token", (None, None))[0]),
            pct(s.get("ast", (None, None))[0]),
            pct(s.get("shadow", (None, None))[0]),
            pct(s.get("comment", (None, None))[0]),
            pct(s.get("string", (None, None))[0]),
        ]
