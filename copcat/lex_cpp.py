"""C/C++ lexer for the audit pipeline. Mirrors `lexing.lex`'s contract:

    tokens, comment_pairs, string_literals, code_lines, ok

- tokens: flat code-token stream (comments and preprocessor lines removed;
  string/char literals kept as single tokens)
- comment_pairs: [(lineno, text)] for // and /* */ comments (markers stripped)
- string_literals: raw string/char literal tokens
- code_lines: per-line " ".join(tokens) for the source-line channel
- never raises: a hand-rolled scanner with hard line-limit guards

Also provides the C++ halves of the language-aware channels:
`cpp_canonical_tokens` (rename-invariant structure stream), `fold_comments_cpp`
(commented-out code folding), `cpp_shadow_code_lines` (dossier alignment) and
`strip_cpp_comment` (decomment for the source-line fallback).
"""

import re

TOKEN_CPP_RE = re.compile(r"[A-Za-z_]\w*|\d+(?:\.\d+)?|\S")
KEYWORDS = frozenset("""
alignas alignof and and_eq asm auto bitand bitor bool break case catch
char char8_t char16_t char32_t class compl concept const consteval
constexpr constinit const_cast continue co_await co_return co_yield
decltype default delete do double dynamic_cast else enum explicit export
extern false float for friend goto if inline int long mutable namespace
new noexcept not not_eq nullptr operator or or_eq private protected
public register reinterpret_cast requires return short signed sizeof
static static_assert static_cast struct switch template this thread_local
throw true try typedef typeid typename union unsigned using virtual void
volatile wchar_t while xor xor_eq
""".split())

_MULTI_OPS = ["<<=", ">>=", "...", "->*", "::", "->", "++", "--", "<<", ">>",
              "<=", ">=", "==", "!=", "&&", "||", "+=", "-=", "*=", "/=",
              "%=", "&=", "^=", "|="]

_WS_RE = re.compile(r"\s+")
_IDENT_RE = re.compile(r"[A-Za-z_]\w*")
_NUM_RE = re.compile(r"(?:0[xX][0-9a-fA-F]+|\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)[fFuUlL]*")

_BLOCK_STAR_RE = re.compile(r"^\s*\*+\s?")
_RAW_STR_RE = re.compile(r'R"([^"(]*)\(')

_CODE_LIKE_CPP_RE = re.compile(
    r"^(?:"
    r".*[;{]\s*$"                           # statement / block opener
    r"|\}.*$"                               # closing brace line
    r"|(?:for|if|else|while|do|switch|case|catch)\s*\("
    r"|(?:cout|cin|cerr)\b"
    r"|\breturn\b"
    r"|\b(?:int|float|double|bool|char|void|auto|long|short|unsigned|"
    r"signed|size_t|string|vector|template|struct|class|namespace|using)\b"
    r"|[A-Za-z_][\w\])>]*\s*=[^=]"          # assignment (not ==)
    r"|#\s*include\b"
    r")")


def cpp_code_like(text):
    """Heuristic: does this comment text look like C++ code?

    Start-anchored and punctuation-hungry on purpose: English prose that
    merely CONTAINS the words 'for', 'if' or 'while' (e.g. a commented task
    description: 'Ask the user for the number of runners.') must NOT count.
    """
    s = text.strip()
    if not s:
        return False
    return bool(_CODE_LIKE_CPP_RE.match(s))


def strip_cpp_comment(line):
    """Strip leading // and block-comment markers (and a trailing */) ."""
    s = line.strip()
    while True:
        if s.startswith("//"):
            s = s[2:].strip()
        elif s.startswith("/*"):
            s = s[2:].strip()
            if s.endswith("*/"):
                s = s[:-2].strip()
        elif s.startswith("*"):
            s = s.lstrip("*").strip()
            if s.endswith("*/"):
                s = s[:-2].strip()
        else:
            break
    return s


def _find_string_end(src, i, quote):
    """Index just past the closing quote; stops at newline (unterminated
    literals must not swallow the file)."""
    j = i + 1
    n = len(src)
    while j < n:
        ch = src[j]
        if ch == "\\" and j + 1 < n:
            j += 2
            continue
        if ch == quote:
            return j + 1
        if ch == "\n":
            return j                     # unterminated: stop at end of line
        j += 1
    return n


def lex_cpp(src):
    """See module docstring. Returns the 5-tuple lex() returns."""
    tokens, comments, strings = [], [], []
    by_line = {}
    lineno = 1
    i, n = 0, len(src)

    def add_token(tok):
        if tok:
            tokens.append(tok)
            by_line.setdefault(lineno, []).append(tok)

    while i < n:
        ch = src[i]
        if ch == "\n":
            lineno += 1
            i += 1
            continue
        if ch in " \t\r":
            i += 1
            continue
        # line comment
        if ch == "/" and i + 1 < n and src[i + 1] == "/":
            j = src.find("\n", i)
            j = n if j == -1 else j
            text = src[i + 2:j].strip()
            if text:
                comments.append((lineno, text))
            i = j
            continue
        # block comment
        if ch == "/" and i + 1 < n and src[i + 1] == "*":
            j = src.find("*/", i + 2)
            j = n if j == -1 else j + 2
            block = src[i + 2:j - 2 if j < n else j]
            for k, bl in enumerate(block.split("\n")):
                text = _BLOCK_STAR_RE.sub("", bl).strip()
                if text:
                    comments.append((lineno + k, text))
            consumed = src[i:j]
            lineno += consumed.count("\n")
            i = j
            continue
        # raw string  R"( ... )"  (default delimiter only)
        if ch in "Rr" and i + 1 < n and src[i + 1] == '"':
            m = _RAW_STR_RE.match(src, i)
            if m:
                closer = ')"' + (m.group(1) or "")
                j = src.find(closer, i + len(m.group(0)))
                j = n if j == -1 else j + len(closer)
                lit = src[i:j]
                strings.append(lit)
                add_token(lit)
                lineno += lit.count("\n")
                i = j
                continue
        # string / char literal
        if ch in "\"'":
            j = _find_string_end(src, i, ch)
            lit = src[i:j]
            strings.append(lit)
            add_token(lit)
            lineno += lit.count("\n")
            i = j
            continue
        # preprocessor directive: skip the whole line
        if ch == "#":
            j = src.find("\n", i)
            i = n if j == -1 else j
            continue
        # identifier / number
        m = _IDENT_RE.match(src, i)
        if m:
            add_token(m.group(0))
            i = m.end()
            continue
        m = _NUM_RE.match(src, i)
        if m:
            add_token(m.group(0))
            i = m.end()
            continue
        # multi-char operators first, then any single char
        for op in _MULTI_OPS:
            if src.startswith(op, i):
                add_token(op)
                i += len(op)
                break
        else:
            add_token(ch)
            i += 1

    code_lines = [" ".join(v) for _, v in sorted(by_line.items())]
    return tokens, comments, strings, code_lines, True


def cpp_tokens(text):
    """Scanner tokens for an arbitrary snippet of (already comment-stripped)
    C++ code.  The single tokenizer every channel must use - folding and
    live code must produce identical streams for identical code, or their
    fingerprints can never meet."""
    return lex_cpp(text)[0]


# --------------------------------------------------------------------------
# language-aware channel helpers
# --------------------------------------------------------------------------
_CANON_MAP_KEEP = KEYWORDS


def cpp_canonical_tokens(source):
    """Rename-invariant structure stream for C++: keywords, operators and
    punctuation survive; identifiers collapse to ID, numbers to NUM and
    string/char literals to STR. Two structurally identical implementations
    produce identical streams regardless of what anything is called."""
    tokens, _c, _s, _cl, _ok = lex_cpp(source)
    out = []
    for tok in tokens:
        if tok[:1] in "\"'":
            out.append("STR")
        elif _IDENT_RE.fullmatch(tok) and tok not in _CANON_MAP_KEEP:
            out.append("ID")
        elif _NUM_RE.fullmatch(tok):
            out.append("NUM")
        else:
            out.append(tok)
    return out, True, 0


def fold_comments_cpp(comment_pairs):
    """C++ twin of shadow.fold_comments: fold commented-out CODE back into a
    token stream; prose stays out. Returns (shadow_tokens, shadow_strings,
    code_like_count, total_comment_lines)."""
    shadow, shadow_strings, code_like = [], [], 0
    total = len(comment_pairs)
    for _lineno, text in comment_pairs:
        s = strip_cpp_comment(text)
        if not s or not cpp_code_like(s):
            continue
        code_like += 1
        shadow.extend(cpp_tokens(s))
        for m in re.finditer(r'"(?:\\.|[^"\\])*"|' + r"'(?:\\.|[^'\\])*'", s):
            shadow_strings.append(m.group(0))
    return shadow, [s for s in shadow_strings if s.strip()], code_like, total


def cpp_shadow_code_lines(source):
    """Plain-text code lines a commented-out C++ file contributes to its
    shadow stream (comment markers stripped) - dossier alignment input."""
    _t, comments, _s, _cl, _ok = lex_cpp(source)
    lines = []
    for _lineno, text in comments:
        s = strip_cpp_comment(text)
        if s and cpp_code_like(s):
            lines.append(s)
    return lines
