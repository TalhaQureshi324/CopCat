"""Shadow channel: detect commented-out code and fold it back into a
fingerprintable token stream.

MOSS ignores comments, so commenting code out is a working evasion trick
(e.g. a whole file commented out to hide a copied submission). Here every
comment line is tested:
  * consecutive comment blocks are joined and parsed with ast.parse —
    a block that parses IS code and its tokens join the shadow stream;
  * otherwise individual lines matching code-likeness heuristics
    (def/class/if/return/assignment/call...) are folded loosely;
  * prose comments go to the comment channel only.
Result: commenting your file out makes it MORE similar to the live copy,
not less. Files with anomalous code-like-comment ratios are surfaced as
evasion candidates in the report.
"""

import ast
import re

TOKEN_RE = re.compile(r"[A-Za-z_]\w*|\d+(?:\.\d+)?|\S")

HASH_RE = re.compile(r"^#+\s*")

CODE_LIKE_RE = re.compile(
    r"^(?:"
    r"def\s|class\s|async\s+def\s|if\s|elif\s|else\s*:|for\s|while\s|"
    r"return\b|import\s|from\s|with\s|try\s*:|raise\s|del\s|assert\s|"
    r"pass$|break$|continue$|yield\b|lambda\b"
    r"|[A-Za-z_][\w.\[\]]*(?:\s*,\s*[A-Za-z_][\w.\[\]]*)*\s*=[^=]"   # assignment
    r"|[A-Za-z_][\w.]*\s*\("                                          # bare call
    r"|\)|\]|\}|\:"                                                   # block tails
    r")"
)


def _strip_hash(line):
    return HASH_RE.sub("", line).strip()

_STRING_RE = re.compile(r"\"([^\"\n]*)\"|'([^'\n]*)'")


def _group_blocks(comment_pairs):
    """[(lineno, text)] -> [[text, ...]] grouped by line adjacency (gap<=2)."""
    blocks, cur, prev = [], [], None
    for lineno, text in comment_pairs:
        if prev is not None and lineno - prev > 2 and cur:
            blocks.append(cur)
            cur = []
        cur.append(text)
        prev = lineno
    if cur:
        blocks.append(cur)
    return blocks


def fold_comments(comment_pairs):
    """Return (shadow_token_stream, shadow_string_literals,
    code_like_line_count, total_comment_lines).

    comment_pairs: [(lineno, raw_comment_text)] — text already had its
    leading '#' stripped by the lexer.
    """
    shadow, shadow_strings, code_like = [], [], 0
    total = len(comment_pairs)
    for block in _group_blocks(comment_pairs):
        text = "\n".join(_strip_hash(t) for t in block if t.strip())
        if not text.strip():
            continue
        try:
            ast.parse(text)
            shadow.extend(TOKEN_RE.findall(text))
            for m in _STRING_RE.finditer(text):
                shadow_strings.append(m.group(1) or m.group(2) or "")
            code_like += sum(1 for t in block if t.strip())
            continue
        except (SyntaxError, ValueError):
            pass
        # loose per-line folding
        for raw in block:
            s = _strip_hash(raw)
            if not s:
                continue
            if CODE_LIKE_RE.match(s):
                code_like += 1
                shadow.extend(TOKEN_RE.findall(s))
                for m in _STRING_RE.finditer(s):
                    shadow_strings.append(m.group(1) or m.group(2) or "")
    return shadow, [s for s in shadow_strings if s.strip()], code_like, total
