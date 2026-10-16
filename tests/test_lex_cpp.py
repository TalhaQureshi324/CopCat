"""C++ lexer unit tests: contract parity with lexing.lex, comment/string
handling, and never-raises robustness."""

from copcat.lex_cpp import (lex_cpp, cpp_canonical_tokens, fold_comments_cpp,
                            cpp_code_like, cpp_shadow_code_lines,
                            strip_cpp_comment)

SRC = """#include <iostream>
// returns the doubled value
int doub(int x) {
    /* block comment
       spanning lines */
    return x * 2;   // trailing note
}

int main() {
    int v = doub(21);
    std::cout << "value: " << v << std::endl;
    if (v != 42) return 1;
    return 0;
}
"""


def test_lex_contract_shapes():
    tokens, comments, strings, code_lines, ok = lex_cpp(SRC)
    assert ok is True
    assert "int" in tokens and "doub" in tokens and "42" in tokens
    assert "#include" not in " ".join(tokens)       # preprocessor skipped
    assert ("2", "returns the doubled value") in [(str(l), t) for l, t in comments]
    texts = [t for _l, t in comments]
    assert any("block comment" in t for t in texts)
    assert any("spanning lines" in t for t in texts)
    assert any("trailing note" in t for t in texts)
    assert any(s.startswith('"value:') for s in strings)


def test_code_lines_are_tokenized_and_comment_free():
    tokens, _c, _s, code_lines, _ok = lex_cpp(SRC)
    joined = "\n".join(code_lines)
    assert "doub" in joined and "<<" in joined
    for ln in code_lines:
        assert "//" not in ln and "/*" not in ln
        assert not ln.strip().startswith("#")


def test_multichar_operators_kept_whole():
    _t, _c, _s, code_lines, _ok = lex_cpp("int main(){std::cout<<1;return x!=y;}")
    blob = " ".join(code_lines)
    assert "<<" in blob and "::" in blob and "!=" in blob


def test_never_raises_on_garbage():
    for src in ('', 'int x = ";  // unterminated', "/* never closed",
                'char c = \'a\' + "\\', "R\"(raw\" string", "#", "\\\\ oddities"):
        tokens, comments, strings, code_lines, ok = lex_cpp(src)
        assert ok is True


def test_canonical_stream_is_rename_invariant():
    a = cpp_canonical_tokens(
        "int total(int a, int b) { return a + b; }")[0]
    b = cpp_canonical_tokens(
        "int total(int p, int q) { return p + q; }")[0]
    assert a == b                       # only names differ -> same stream
    assert a == ["int", "ID", "(", "int", "ID", ",", "int", "ID", ")",
                 "{", "return", "ID", "+", "ID", ";", "}"]
    c = cpp_canonical_tokens(
        "int total(int a, int b) { return a - b; }")[0]
    assert c != a                      # different logic -> different stream


def test_fold_comments_cpp():
    pairs = [(1, "this function doubles the input"),
             (2, "return x * 2;"),
             (3, "for (int i = 0; i < n; i++) {"),
             (4, "cout << \"hi\" << endl;")]
    shadow, strings, code_like, total = fold_comments_cpp(pairs)
    assert total == 4
    assert code_like == 3
    assert "return" in shadow and "for" in shadow
    assert '"hi"' in strings


def test_shadow_lines_and_strip():
    src = ("// int helper(int a) {\n"
           "//     return a * 3;\n"
           "// }\n"
           "// helper just triples its argument\n")
    lines = cpp_shadow_code_lines(src)
    assert any("helper" in ln and "{" in ln for ln in lines)
    assert not any("triples its argument" in ln for ln in lines)
    assert strip_cpp_comment("// int x = 1;") == "int x = 1;"
    assert strip_cpp_comment("/* int y; */") == "int y;"
    assert cpp_code_like("visited.push_back(curr);")
    assert not cpp_code_like("this loop walks the graph level by level")
