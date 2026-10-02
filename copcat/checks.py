"""Static (no-execution) rubric checks over the submission's AST + source.

Every check is a pure function (tree, src, params) -> (passed, detail).
`tree` comes from the fault-tolerant chunk parser, so a syntax error in one
task does not blind the checks for other tasks. Extend the registry by
registering a new function name — the YAML `type:` field resolves here.
"""

import re

from .canon import parse_lenient

_REGISTRY = {}


def check(name):
    def deco(fn):
        _REGISTRY[name] = fn
        return fn
    return deco


def get_check(name):
    if name not in _REGISTRY:
        raise KeyError("unknown check type '{}' (available: {})".format(
            name, ", ".join(sorted(_REGISTRY))))
    return _REGISTRY[name]


# ---- AST helpers -----------------------------------------------------------

def _classes(tree):
    import ast
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            yield node


def _find_class(tree, name):
    for node in _classes(tree):
        if node.name == name:
            return node
    return None


def _methods(cls):
    import ast
    for node in cls.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def _segment(src, node):
    lines = src.splitlines()
    a = max(getattr(node, "lineno", 1) - 1, 0)
    b = getattr(node, "end_lineno", len(lines))
    return "\n".join(lines[a:b])


# ---- structural checks -----------------------------------------------------

@check("exists_class")
def _exists_class(tree, src, p):
    ok = _find_class(tree, p["name"]) is not None
    return ok, "class '{}' {}".format(p["name"], "found" if ok else "missing")


@check("exists_method")
def _exists_method(tree, src, p):
    cls = _find_class(tree, p["class"])
    if cls is None:
        return False, "class '{}' missing".format(p["class"])
    for m in _methods(cls):
        if m.name == p["method"]:
            return True, "method '{}.{}' found".format(p["class"], p["method"])
    return False, "method '{}.{}' missing".format(p["class"], p["method"])


@check("has_attrs")
def _has_attrs(tree, src, p):
    import ast
    cls = _find_class(tree, p["class"])
    if cls is None:
        return False, "class '{}' missing".format(p["class"])
    found = set()
    for node in ast.walk(cls):
        if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                and node.value.id in ("self", "cls")):
            found.add(node.attr)
    missing = [a for a in p.get("attrs", []) if a not in found]
    if not missing:
        return True, "all required attributes present"
    return False, "missing attributes: " + ", ".join(missing)


@check("has_decorator")
def _has_decorator(tree, src, p):
    import ast
    want = p["decorator"].split(".")[-1]
    cls = _find_class(tree, p.get("class"))
    if cls is None and p.get("class"):
        return False, "class '{}' missing".format(p["class"])
    targets = [cls] if cls else list(_classes(tree))
    for c in targets:
        for m in _methods(c):
            if p.get("method") and m.name != p["method"]:
                continue
            for dec in m.decorator_list:
                name = dec.func.id if isinstance(dec, ast.Call) else getattr(dec, "id", None)
                name = name or getattr(dec, "attr", "")
                if name.split(".")[-1] == want:
                    return True, "decorator @{} present".format(want)
    return False, "no {} method decorated with @{}".format(
        p.get("method", "candidate"), want)


@check("calls_super")
def _calls_super(tree, src, p):
    import ast
    cls = _find_class(tree, p["class"])
    if cls is None:
        return False, "class '{}' missing".format(p["class"])
    method = p.get("method")
    for m in _methods(cls):
        if method and m.name != method:
            continue
        for node in ast.walk(m):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Call)
                    and isinstance(node.func.value.func, ast.Name)
                    and node.func.value.func.id == "super"):
                return True, "super() call found in '{}.{}'".format(
                    cls.name, m.name)
    return False, "'{}.{}' never calls super()".format(
        cls.name, method or "*")


@check("base_class")
def _base_class(tree, src, p):
    cls = _find_class(tree, p.get("class") or p.get("name"))
    if cls is None:
        return False, "class '{}' missing".format(p.get("class") or p.get("name"))
    import ast
    for base in cls.bases:
        name = getattr(base, "id", None) or getattr(base, "attr", None)
        if name == p["base"]:
            return True, "'{}' inherits '{}'".format(cls.name, p["base"])
    return False, "'{}' does not inherit '{}'".format(cls.name, p["base"])


@check("name_mangled_attr")
def _name_mangled_attr(tree, src, p):
    import ast
    cls = _find_class(tree, p["class"])
    if cls is None:
        return False, "class '{}' missing".format(p["class"])
    want = "__" + p["attr"]
    for node in ast.walk(cls):
        if (isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name) and node.value.id == "self"
                and node.attr == want):
            return True, "name-mangled 'self.{}' found".format(want)
    return False, ("no name-mangled 'self.{}' in '{}' — attribute is public or "
                   "single-underscore".format(want, p["class"]))


# ---- source/regex checks ---------------------------------------------------

def _scoped_source(tree, src, scope):
    if not scope or scope == "file":
        return src
    if scope.startswith("class:"):
        cls = _find_class(tree, scope.split(":", 1)[1])
        return _segment(src, cls) if cls else ""
    if scope.startswith("method:"):
        qual = scope.split(":", 1)[1]
        cname, mname = qual.split(".", 1)
        cls = _find_class(tree, cname)
        if cls is None:
            return ""
        for m in _methods(cls):
            if m.name == mname:
                return _segment(src, m)
        return ""
    return src


def _code_only(src):
    """Comment-stripped source. Regex checks search this by default so a
    commented-out implementation can never earn marks (the grading-side
    mirror of the MOSS comment-evasion problem)."""
    from .lexing import lex
    _t, _c, _s, code_lines, _ok = lex(src)
    return "\n".join(code_lines)


def _alias_pattern(pattern, aliases):
    """Make a regex alias-aware: occurrences of a required interface name
    also match the student's bound name (`except InventoryError` must match
    a renamed `except StockError`)."""
    if not aliases:
        return pattern
    for required, student in aliases.items():
        pattern = re.sub(r"\b%s\b" % re.escape(required),
                         "(?:%s|%s)" % (re.escape(required), re.escape(student)),
                         pattern)
    return pattern


@check("forbidden_pattern")
def _forbidden_pattern(tree, src, p):
    seg = _scoped_source(tree, src, p.get("scope", "file"))
    if not p.get("include_comments"):
        seg = _code_only(seg)
    pattern = _alias_pattern(p["pattern"], p.get("aliases") or {})
    hits = re.search(pattern, seg)
    if hits:
        return False, p.get("fail", "forbidden pattern found in scope '{}'".format(
            p.get("scope", "file")))
    return True, "clean"


@check("regex_present")
def _regex_present(tree, src, p):
    blob = src if p.get("include_comments") else _code_only(src)
    pattern = _alias_pattern(p["pattern"], p.get("aliases") or {})
    if re.search(pattern, blob):
        return True, p.get("pass_detail", "pattern present")
    return False, p.get("fail", "pattern '{}' not found".format(p["pattern"]))


@check("comment_regex_present")
def _comment_regex_present(tree, src, p):
    from .lexing import lex
    _t, comments, _s, _c, _ok = lex(src)
    blob = "\n".join(t for _, t in comments)
    pattern = _alias_pattern(p["pattern"], p.get("aliases") or {})
    if re.search(pattern, blob, re.IGNORECASE if p.get("ignorecase", True) else 0):
        return True, "comment/demo mentioning '{}' found".format(p.get("label", p["pattern"]))
    return False, p.get("fail", "no comment demonstrates this requirement")


@check("min_lines")
def _min_lines(tree, src, p):
    n = sum(1 for _ in src.splitlines() if _.strip())
    if n >= p.get("count", 10):
        return True, "{} non-blank lines".format(n)
    return False, "only {} non-blank lines".format(n)
