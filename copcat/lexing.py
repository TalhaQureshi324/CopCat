"""Lexical analysis: split source into code tokens, comments, docstrings and
string literals. Never raises — falls back to a regex tokenizer when the
stdlib tokenizer rejects the file (syntax errors, unterminated strings...)."""

import io
import re
import tokenize

TOKEN_RE = re.compile(r"[A-Za-z_]\w*|\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|\S")
TRIPLE_RE = re.compile(r"^[fFrRbBuU]{0,2}('''|\"\"\")")
WORD_RE = re.compile(r"[a-z0-9]+")

_SKIP = {
    tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT,
    tokenize.ENDMARKER, tokenize.ENCODING,
}
_FSTRING_START = getattr(tokenize, "FSTRING_START", None)
_FSTRING_END = getattr(tokenize, "FSTRING_END", None)
_FSTRING_MIDDLE = getattr(tokenize, "FSTRING_MIDDLE", None)


def normalize_words(text):
    """Lowercase alphanumeric word stream (for comment/string shingling)."""
    return WORD_RE.findall(text.lower())


def _clean_doc(raw):
    """Triple-quoted string -> plain text."""
    body = raw
    m = re.match(r"^[fFrRbBuU]{0,2}(['\"]{3})(.*)\1$", body, re.S)
    if m:
        body = m.group(2)
    return re.sub(r"\s+", " ", body).strip()


def _fallback(src):
    """Regex path when tokenize fails: per-line comment strip."""
    tokens, comments, strings, code_lines = [], [], [], []
    for lineno, ln in enumerate(src.splitlines(), 1):
        if "#" in ln:
            i = ln.index("#")
            code, com = ln[:i], ln[i + 1:]
            if com.strip():
                comments.append((lineno, com.strip()))
        else:
            code = ln
        for m in re.finditer(r"\"([^\n\"]*)\"|'([^'\n]*)'", code):
            strings.append(m.group(0))
        toks = TOKEN_RE.findall(code)
        if toks:
            tokens.extend(toks)
            code_lines.append(" ".join(toks))
    return tokens, comments, strings, code_lines, True


def lex(src):
    """Return (tokens, comment_pairs, string_literals, code_lines).

    tokens        flat code-token stream (comments/docstrings removed;
                  f-string parts kept inline so operators over the stream
                  match classic MOSS-style comparisons)
    comment_pairs [(lineno, text)] for comments AND docstrings (prose channel)
    string_literals raw string tokens (content channel)
    code_lines    per-line " ".join(tokens) for the source-line channel
    """
    tokens, comments, strings = [], [], []
    by_line = {}
    try:
        for t in tokenize.generate_tokens(io.StringIO(src).readline):
            tt, s = t.type, t.string
            if tt in _SKIP:
                continue
            if tt == tokenize.COMMENT:
                c = s.lstrip("#").strip()
                if c:
                    comments.append((t.start[0], c))
                continue
            if tt == tokenize.STRING and TRIPLE_RE.match(s):
                d = _clean_doc(s)
                if d:
                    comments.append((t.start[0], d))
                continue
            if tt == tokenize.STRING:
                strings.append(s)
            if _FSTRING_MIDDLE is not None and tt == _FSTRING_MIDDLE:
                strings.append(s)
            tokens.append(s)
            by_line.setdefault(t.start[0], []).append(s)
        code_lines = [" ".join(v) for _, v in sorted(by_line.items())]
        return tokens, comments, strings, code_lines, True
    except (tokenize.TokenError, IndentationError, SyntaxError, ValueError):
        return _fallback(src)
