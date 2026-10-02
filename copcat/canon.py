"""AST canonicalization: fault-tolerant parsing + scope-aware renaming.

Gap fixes implemented here:
* parse_lenient(): if full-file ast.parse() fails, split into top-level
  blocks (class/def/import/assignment) and parse each independently so one
  syntax error can't zero out the whole file.
* CanonRenamer(): scope-aware canonical renaming with a preserved symbol
  table (builtins + dunders + self/cls + rubric interface names). Only
  locals, helpers, params and non-interface attributes are canonicalized,
  so `len`, `range`, `math.sqrt` and mandated names like `calculate_pay`
  survive; student-chosen names collapse to V1/V2/.../C1/f1/a1.
"""

import ast
import builtins
import re

DUNDERS = {
    "__init__", "__str__", "__repr__", "__eq__", "__ne__", "__lt__", "__le__",
    "__gt__", "__ge__", "__add__", "__sub__", "__mul__", "__truediv__",
    "__floordiv__", "__mod__", "__pow__", "__neg__", "__abs__", "__len__",
    "__hash__", "__iter__", "__next__", "__call__", "__getitem__",
    "__setitem__", "__delitem__", "__contains__", "__enter__", "__exit__",
    "__main__", "__name__", "__doc__", "__class__", "__dict__",
}

BASE_PRESERVED = set(dir(builtins)) | {"self", "cls"} | DUNDERS

_TOP_START_RE = re.compile(
    r"^(?:class\s|def\s|async\s+def\s|@|[A-Za-z_][\w.\[\]]*(?:\s*,\s*"
    r"[A-Za-z_][\w.\[\]]*)*\s*=[^=]|import\s|from\s)")


def parse_lenient(src):
    """Parse full file; on SyntaxError, parse top-level chunks independently.

    Returns (module_or_None, chunks_ok, chunks_failed).
    """
    try:
        return ast.parse(src), 1, 0
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        pass
    lines = src.splitlines()
    starts = [i for i, l in enumerate(lines) if _TOP_START_RE.match(l)]
    if not starts:
        return None, 0, 1
    bounds = starts + [len(lines)]
    bodies, ok, failed = [], 0, 0
    for a, b in zip(bounds, bounds[1:]):
        chunk = "\n".join(lines[a:b]).rstrip()
        if not chunk.strip():
            continue
        try:
            bodies.append(ast.parse(chunk).body)
            ok += 1
            continue
        except (SyntaxError, ValueError):
            pass
        # last resort: accumulate lines until they parse (recovers the
        # well-formed prefix of a broken block)
        recovered = False
        buf = []
        for ln in lines[a:b]:
            buf.append(ln)
            try:
                bodies.append(ast.parse("\n".join(buf)).body)
                ok += 1
                recovered = True
                buf = []
            except (SyntaxError, ValueError):
                continue
        if not recovered:
            failed += 1
    if not bodies:
        return None, ok, failed
    flat = [stmt for body in bodies for stmt in body]
    return ast.Module(body=flat, type_ignores=[]), ok, failed


def _strip_docstrings(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef,
                             ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if body:
                first = body[0]
                if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                        and isinstance(first.value.value, str)):
                    node.body = body[1:] or [ast.Pass()]


class CanonRenamer(ast.NodeTransformer):
    """Scope-aware identifier canonicalizer."""

    def __init__(self, preserved=()):
        self.preserved = BASE_PRESERVED | set(preserved)
        self.scopes = [{}]        # scopes[0] = module scope
        self.counters = [0]
        self.attrs = {}           # attribute/keyword names -> aN
        self.acount = 0

    # -- scope helpers ----------------------------------------------------
    def _push(self):
        self.scopes.append({})
        self.counters.append(0)

    def _pop(self):
        self.scopes.pop()
        self.counters.pop()

    def _map(self, name, kind="v"):
        if name in self.preserved:
            return name
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        self.counters[-1] += 1
        canon = "{}{}".format(kind, self.counters[-1])
        self.scopes[-1][name] = canon
        return canon

    def _map_attr(self, name):
        if name in self.preserved:
            return name
        if name not in self.attrs:
            self.acount += 1
            self.attrs[name] = "a{}".format(self.acount)
        return self.attrs[name]

    # -- visitors ----------------------------------------------------------
    def visit_ClassDef(self, node):
        node.name = self._map(node.name, "C")
        self._push()
        self.generic_visit(node)
        self._pop()
        return node

    def _visit_function(self, node):
        node.name = self._map(node.name, "f")
        self._push()
        args = node.args
        for a in (list(getattr(args, "posonlyargs", []) or []) + list(args.args)
                  + list(args.kwonlyargs or [])):
            a.arg = self._map(a.arg)
        if args.vararg:
            args.vararg.arg = self._map(args.vararg.arg)
        if args.kwarg:
            args.kwarg.arg = self._map(args.kwarg.arg)
        self.generic_visit(node)
        self._pop()
        return node

    def visit_FunctionDef(self, node):
        return self._visit_function(node)

    def visit_AsyncFunctionDef(self, node):
        return self._visit_function(node)

    def visit_Lambda(self, node):
        self._push()
        for a in node.args.args:
            a.arg = self._map(a.arg)
        self.generic_visit(node)
        self._pop()
        return node

    def visit_Name(self, node):
        node.id = self._map(node.id)
        return node

    def visit_Attribute(self, node):
        self.generic_visit(node)
        node.attr = self._map_attr(node.attr)
        return node

    def visit_keyword(self, node):
        self.generic_visit(node)
        if node.arg:
            node.arg = self._map_attr(node.arg)
        return node

    def visit_ExceptHandler(self, node):
        self.generic_visit(node)
        if node.name:
            node.name = self._map(node.name)
        return node

    def visit_Import(self, node):
        for alias in node.names:
            target = self._map(alias.asname or alias.name.split(".")[0])
            alias.asname = target
        return node

    def visit_ImportFrom(self, node):
        for alias in node.names:
            if alias.name == "*":
                continue
            target = self._map(alias.asname or alias.name)
            alias.asname = target
        return node

    def visit_Constant(self, node):
        v = node.value
        if isinstance(v, str):
            node.value = "<S>"
        elif isinstance(v, (int, float, complex)) and not isinstance(v, bool):
            node.value = 0
        return node


_NUM_RE = re.compile(r"\d+")


def canonical_tokens(src, preserved=()):
    """(canonical token stream, parse_ok, chunks_failed)."""
    tree, ok, failed = parse_lenient(src)
    if tree is None:
        return [], False, failed
    _strip_docstrings(tree)
    try:
        tree = CanonRenamer(preserved).visit(tree)
        text = ast.unparse(tree)
    except Exception:
        return [], ok, failed
    toks = re.findall(r"[A-Za-z_]\w*|\S", text)
    out = []
    for t in toks:
        if "<S>" in t:
            t = "S"
        out.append(t)
    return out, ok, failed
