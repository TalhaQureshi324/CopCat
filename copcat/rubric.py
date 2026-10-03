"""Rubric engine: load a YAML rubric, run static + sandboxed checks per
submission, compute partial credit and evidence-backed deduction reports.

Rubric shape (see examples/rubric_lab02.yaml):

    lab: ai_lab02
    settings: {timeout_s: 15, memory_mb: 512}
    tasks:
      - id: T3
        weight: 1.5
        checks:
          - { id: mangled, type: name_mangled_attr, class: BankAccount,
              attr: balance, deduct: 0.4 }
          - { id: demo, type: comment_regex_present, pattern: "balance\\s*=",
              near: "mangl|attribute", deduct: 0.2 }

Check categories:
* static (no execution): exists_class, exists_method, has_attrs,
  has_decorator, calls_super, base_class, name_mangled_attr,
  forbidden_pattern, regex_present, comment_regex_present, min_lines
* dynamic (one sandboxed run per file): runs_clean, stdout_contains,
  stdout_regex
* functional (probes inside the same sandboxed run): the probe spec comes
  from `construct` / `call` / `set_expr` params and `expect` is
  "raises_any" | "raises:<Name>" | "ok"
"""

import ast
import json
import os
import re
import tempfile
import zipfile

from .canon import parse_lenient
from .checks import get_check
from .sandbox import run_sandboxed

try:
    import yaml
except ImportError:      # pragma: no cover
    yaml = None

_STATIC_TYPES = {"exists_class", "exists_method", "method_exists",
                 "class_exists", "has_attrs", "instance_attrs",
                 "has_decorator", "calls_super", "base_class",
                 "name_mangled_attr", "forbidden_pattern",
                 "forbidden_import_or_usage", "forbidden_instance_attrs",
                 "regex_present", "comment_regex_present", "min_lines",
                 "exception_hierarchy", "ast_uses_class"}
_STATIC_ALIASES = {"instance_attrs": "has_attrs"}
_DYNAMIC_TYPES = {"runs_clean", "stdout_contains", "stdout_regex",
                  "stdout_contains_pattern", "dynamic_execution"}
_PROBE_TYPES = {"functional", "functional_call_raises",
                "functional_call_returns", "functional_property_test"}


class RubricError(Exception):
    pass


def _known_check_types():
    import difflib
    from .checks import _REGISTRY
    known = (set(_REGISTRY) | set(_DYNAMIC_TYPES) | set(_PROBE_TYPES)
             | set(_STATIC_ALIASES))
    def suggest(name):
        close = difflib.get_close_matches(name, sorted(known), n=3)
        hint = " — did you mean: {}?".format(", ".join(close)) if close else                " — available types: {}".format(", ".join(sorted(known)))
        return hint
    return known, suggest


def load_rubric(path):
    if yaml is None:
        raise RubricError("PyYAML is required for rubric grading: pip install pyyaml")
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict) or "tasks" not in data:
        raise RubricError("rubric must be a mapping with a 'tasks' list")
    known, suggest = _known_check_types()
    for i, task in enumerate(data["tasks"]):
        if "id" not in task or "weight" not in task:
            raise RubricError("task #{} needs 'id' and 'weight'".format(i + 1))
        for chk in task.get("checks", []):
            if "type" not in chk:
                raise RubricError("check without 'type' in task {}".format(task["id"]))
            if "construct" not in chk and chk["type"] not in known:
                raise RubricError("unknown check type '{}' in task {}{}".format(
                    chk["type"], task.get("id", i + 1), suggest(chk["type"])))
    settings = data.setdefault("settings", {})
    # Lab 03 dialect: a dynamic_runner section maps onto engine settings
    dr = data.get("dynamic_runner") or {}
    if dr.get("timeout_seconds"):
        settings.setdefault("timeout_s", dr["timeout_seconds"])
    if dr.get("ignore_case_in_stdout"):
        settings["stdout_ignorecase"] = True
    # multi-file penalty from global_rules
    gr = data.get("global_rules") or {}
    if gr.get("multi_file_deduction") is not None:
        settings["multi_file_deduction"] = abs(float(gr["multi_file_deduction"]))
    return data


def _probe_of(check):
    """Build worker probe(s) from a functional check. Returns a list —
    some checks expand into one probe per method."""
    ctype = check["type"]
    cid = check["id"]
    expect = check.get("expect", "ok")

    def std_probe(pid, construct, call=None, set_expr=None, kind=None,
                  args=None, steps=None, target=None):
        pr = {"id": pid, "construct": construct, "call": call,
              "set_expr": set_expr, "expect": expect,
              "raises": expect.split(":", 1)[1] if expect.startswith("raises:") else None,
              "raises_any": expect == "raises_any"}
        if kind:
            pr["kind"] = kind
        if args is not None:
            pr["args"] = args
        if steps is not None:
            pr["steps"] = steps
        if target is not None:
            pr["target"] = target
        return pr

    if ctype == "functional_call_raises":
        target = check.get("target")
        exc = check.get("expected_exception", "Exception")
        return [std_probe("{}::{}".format(cid, m), "{}()".format(target),
                          call="obj.{}()".format(m))
                for m in check.get("methods", [])]
    if ctype == "functional_call_returns":
        return [std_probe(cid, check["function"], args=check.get("args", []),
                          kind="call_args")]
    if ctype == "functional_property_test":
        return [std_probe(cid, check.get("target"),
                          steps=check.get("sequence", []),
                          kind="sequence")]
    return [std_probe(cid, check.get("construct"), call=check.get("call"),
                      set_expr=check.get("set_expr"))]


def _eval_dynamic_check(check, run_result):
    """(passed, detail) for runs_clean / stdout_contains / stdout_regex /
    stdout_contains_pattern / dynamic_execution."""
    ctype = check["type"]
    flags = re.IGNORECASE if check.get("stdout_ignorecase") else 0
    if ctype == "runs_clean":
        if run_result["crash"]:
            return False, "crashes: {}".format(run_result["crash"])
        return True, "executes cleanly ({:.1f}s)".format(
            run_result["duration_ms"] / 1000.0)
    if ctype in ("stdout_contains",):
        out = run_result["stdout_tail"]
        if run_result["crash"] and not out:
            return False, "no output — crashed ({})".format(run_result["crash"])
        needle = check.get("text", "")
        return (needle in out), "expected '{}' in output".format(needle)
    if ctype in ("stdout_regex", "stdout_contains_pattern"):
        out = run_result["stdout_tail"]
        if run_result["crash"] and not out:
            return False, "no output — crashed ({})".format(run_result["crash"])
        ok = bool(re.search(check["pattern"], out, flags))
        return ok, ("pattern matched" if ok else
                    "expected output /{}/ not found in simulation log".format(
                        check["pattern"]))
    if ctype == "dynamic_execution":
        seq = check.get("expected_action_sequence") or []
        if check.get("stdout_ignorecase"):
            seq = [t.lower() for t in seq]
        out = run_result["stdout_tail"]
        if check.get("stdout_ignorecase"):
            out = out.lower()
        if run_result["crash"] and not out:
            return False, "no output — crashed ({})".format(run_result["crash"])
        pos = 0
        for token in seq:
            i = out.find(token, pos)
            if i < 0:
                return False, (
                    "expected action '{}' not found in order in the printed "
                    "simulation log (from position {})".format(token, pos))
            pos = i + len(token)
        return True, "expected action sequence found in order in the log"
    return False, "unknown dynamic check"


def _eval_probe(check, probe_result):
    expect = check.get("expect", "ok")
    status = probe_result.get("status")
    if status == "error":
        return False, "module could not load for probing"
    if status == "construct_error":
        return False, "could not build {} — {}".format(
            check.get("construct", "object"), probe_result.get("detail", ""))
    if probe_result.get("kind") == "sequence":
        if status == "ok":
            return True, "property sequence held"
        return False, probe_result.get("detail", "sequence failed")
    if probe_result.get("kind") == "call_args":
        if status == "raised":
            return False, "unexpected exception {}: {}".format(
                probe_result.get("exc"), probe_result.get("detail", ""))
        val = probe_result.get("value")
        em = check.get("expected_match") or {}
        if em:
            idx = em.get("index")
            got = val[idx] if isinstance(val, list) and idx < len(val) else None
            want = em.get("value")
            if isinstance(want, bool):
                if not (isinstance(got, bool) and got == want):
                    return False, "result[{}] = {!r}, expected {!r}".format(idx, got, want)
            elif got != want:
                return False, "result[{}] = {!r}, expected {!r}".format(idx, got, want)
        reasons = check.get("expected_reason_contains") or []
        if reasons:
            blob = json.dumps(val).lower() if not isinstance(val, str) else val.lower()
            if not any(str(r).lower() in blob for r in reasons):
                return False, "reason string did not contain any of {}".format(list(reasons))
        return True, "ok"
    if expect == "raises_any":
        if status == "raised":
            return True, "raised {} as expected".format(probe_result.get("exc"))
        return False, "expected an exception, got {}".format(
            probe_result.get("result", "no exception"))
    if expect.startswith("raises:"):
        want = expect.split(":", 1)[1]
        if status == "raised" and probe_result.get("exc") == want:
            return True, "raised {} as expected".format(want)
        if status == "raised":
            return False, "raised {} instead of {}".format(probe_result.get("exc"), want)
        return False, "no exception raised (expected {}); got {}".format(
            want, probe_result.get("result", "nothing"))
    if expect == "truthy":
        if status != "ok":
            return False, "unexpected exception {}: {}".format(
                probe_result.get("exc"), probe_result.get("detail", ""))
        if probe_result.get("result") == "True":
            return True, "condition held"
        return False, "condition was {}".format(probe_result.get("result"))
    if status == "raised":
        return False, "unexpected exception {}: {}".format(
            probe_result.get("exc"), probe_result.get("detail", ""))
    return True, "ok"


def _required_interface(rubric):
    """{class: {"methods": set, "attrs": set}} expected by the rubric."""
    req = {}
    for task in rubric["tasks"]:
        for chk in task.get("checks", []):
            cls = chk.get("class")
            if not cls and chk["type"] == "exists_class":
                cls = chk.get("name")      # exists_class uses name:
            if not cls:
                continue
            entry = req.setdefault(cls, {"methods": set(), "attrs": set()})
            if chk["type"] in ("exists_method", "calls_super"):
                entry["methods"].add(chk["method"])
            elif chk["type"] == "has_decorator" and chk.get("method"):
                entry["methods"].add(chk["method"])
            elif chk["type"] == "has_attrs":
                entry["attrs"].update(chk.get("attrs", []))

    # functional probes: construct's leading identifier = required class;
    # operators/functions in the call imply the dunders it must implement
    for task in rubric["tasks"]:
        for chk in task.get("checks", []):
            if "construct" not in chk:
                continue
            construct = chk["construct"]
            if isinstance(construct, list):
                construct = construct[0] if construct else ""
            m = re.match(r"^\s*([A-Za-z_]\w*)\s*\(", construct or "")
            if not m:
                continue
            entry = req.setdefault(m.group(1),
                                   {"methods": set(), "attrs": set()})
            call = chk.get("call", "") or ""
            # strip string literals and numeric literals (incl. negatives)
            # so `withdraw(-5)` is not mistaken for `a - b`
            clean = re.sub(r"'[^']*'|\"[^\"]*\"", " ", call)
            clean = re.sub(r"(?<![\w.])-?\d+(?:\.\d+)?", " ", clean)
            tokens = set(re.findall(r"==|[+\-*/%]", clean))
            if "+" in tokens:
                entry["methods"].add("__add__")
            if "-" in tokens:
                entry["methods"].add("__sub__")
            if "*" in tokens:
                entry["methods"].add("__mul__")
            if "%" in tokens:
                entry["methods"].add("__mod__")
            if "==" in tokens:
                entry["methods"].add("__eq__")
            for fn, dunder in (("abs(", "__abs__"), ("str(", "__str__"),
                               ("len(", "__len__")):
                if fn in call:
                    entry["methods"].add(dunder)
    return req


def _class_structures(tree):
    import ast
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            methods = set()
            super_methods = set()
            attrs = set()
            for item in node.body:
                if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                methods.add(item.name)
                for sub in ast.walk(item):
                    if (isinstance(sub, ast.Call)
                            and isinstance(sub.func, ast.Attribute)
                            and isinstance(sub.func.value, ast.Call)
                            and isinstance(sub.func.value.func, ast.Name)
                            and sub.func.value.func.id == "super"):
                        super_methods.add(item.name)
            for n in ast.walk(node):
                if (isinstance(n, ast.Attribute)
                        and isinstance(n.value, ast.Name)
                        and n.value.id in ("self", "cls")):
                    attrs.add(n.attr)
            out[node.name] = {"methods": methods, "attrs": attrs,
                              "super_methods": super_methods}
    return out


def _expected_children(rubric):
    """{parent_class: set(child_class)} from base_class checks."""
    out = {}
    for task in rubric["tasks"]:
        for chk in task.get("checks", []):
            if chk["type"] == "base_class" and chk.get("base"):
                out.setdefault(chk["base"], set()).add(chk["class"])
    return out


def resolve_class_aliases(tree, rubric):
    """Structural interface binding: if a rubric-required class is missing by
    name, find the student's class that implements it.

    Binding signals, in order:
    1. method/attribute overlap with the rubric's expectations for that
       class (>= structural_threshold), greedy with unique assignment;
       abstract-base requirements prefer subclassed candidates
    2. base-relation propagation: base_class checks say X inherits Y — once
       X is bound, the student class X-bound inherits under its real base
       name, which binds Y; and a parent with the expected number of
       student subclasses binds directly

    Returns (aliases, bindings): aliases maps required-name -> student-name.
    """
    import ast
    settings = rubric.get("settings", {})
    threshold = float(settings.get("structural_threshold", 0.8))
    req = _required_interface(rubric)
    children = _expected_children(rubric)
    structures = _class_structures(tree)
    subclasses = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                name = getattr(base, "id", None) or getattr(base, "attr", None)
                if name:
                    subclasses.setdefault(name, []).append(node.name)

    aliases = {}          # required -> student
    used_students = set(structures) & set()  # (placeholder; tracked below)
    used_students = set()
    bindings = []

    def subclass_count(student_name):
        return len(subclasses.get(student_name, []))

    # ---- phase 1: structural evidence ------------------------------------
    triples = []
    for required in sorted(req):
        if required in structures:
            continue
        need_m, need_a = req[required]["methods"], req[required]["attrs"]
        super_expect = {m for t in rubric["tasks"] for c in t.get("checks", [])
                        if c.get("class") == required
                        and c["type"] == "calls_super"
                        for m in [c.get("method")]}
        is_parent = required in children
        need = len(need_m) + len(need_a)
        if need == 0:
            continue
        abstract = any(
            c.get("decorator") == "abstractmethod"
            for t in rubric["tasks"] for c in t.get("checks", [])
            if c.get("class") == required)
        for cand, st in structures.items():
            if cand in req:
                continue
            hits = len(st["methods"] & need_m) + len(st["attrs"] & need_a)
            score = hits / need
            if score < threshold:
                continue
            # super-call evidence: a required super() in an overridden method
            # must exist in the candidate
            if super_expect and not (st["super_methods"] & super_expect):
                continue
            # tie-breaks: abstract bases and hierarchy parents should map to
            # subclassed candidates; leaf requirements to unsubclassed ones
            sub_pref = subclass_count(cand)
            tie = -sub_pref if (abstract or is_parent) else sub_pref
            # requirements carrying a super() expectation are the most
            # constrained — assign them before looser ones steal candidates
            constrained = 0 if super_expect else 1
            triples.append((score, constrained, tie, -len(st["methods"]),
                            required, cand))
    triples.sort(key=lambda t: (-t[0], t[1], t[2], t[3], t[4], t[5]))
    for score, _con, _tie, _nm, required, cand in triples:
        if required in aliases or cand in used_students:
            continue
        aliases[required] = cand
        used_students.add(cand)
        bindings.append((required, cand, score))

    # ---- phase 1.5: parent count-signature -------------------------------
    # a required parent whose expected children all lack independent
    # evidence still binds if exactly n student subclasses exist
    for parent_req, child_reqs in children.items():
        if parent_req in aliases or parent_req in structures:
            continue
        # children already present by name need no binding at all
        unbound_children = [c for c in sorted(child_reqs)
                            if c not in aliases and c not in structures]
        if not unbound_children:
            continue
        matches = [name for name, n in subclasses.items()
                   if len(n) == len(unbound_children)
                   and name not in used_students
                   and name not in aliases.values()
                   and name != parent_req]
        if len(matches) == 1:
            aliases[parent_req] = matches[0]
            used_students.add(matches[0])
            bindings.append((parent_req, matches[0], 1.0))

    # ---- phase 2: base-relation propagation ------------------------------
    changed = True
    while changed:
        changed = False
        for parent_req, child_reqs in children.items():
            # (a) child bound -> its student base name binds the parent
            for child_req in child_reqs:
                if child_req in aliases and parent_req not in aliases \
                        and parent_req not in structures:
                    child_student = aliases[child_req]
                    for node in ast.walk(tree):
                        if (isinstance(node, ast.ClassDef)
                                and node.name == child_student
                                and node.bases):
                            base_name = (getattr(node.bases[0], "id", None)
                                         or getattr(node.bases[0], "attr", ""))
                            if (base_name not in used_students
                                    and base_name not in req
                                    and base_name in structures):
                                aliases[parent_req] = base_name
                                used_students.add(base_name)
                                bindings.append((parent_req, base_name, 1.0))
                                changed = True
                                break
            # (b) parent bound -> unbound required children bind to the
            #     student subclasses of the parent's student name
            parent_student = aliases.get(parent_req)
            if parent_student:
                kids = [c for c in subclasses.get(parent_student, [])
                        if c not in used_students and c not in aliases.values()
                        and c not in structures]
                for child_req in sorted(child_reqs):
                    if child_req in aliases or not kids:
                        continue
                    cand = kids.pop(0)
                    aliases[child_req] = cand
                    used_students.add(cand)
                    bindings.append((child_req, cand, 1.0))
                    changed = True

    return aliases, bindings


class _AliasTransformer(ast.NodeTransformer):
    """Rewrite the tree so required interface names point at the student's
    bound classes (ClassDef names and every reference)."""

    def __init__(self, required_to_student):
        self.mapping = required_to_student

    def visit_ClassDef(self, node):
        self.generic_visit(node)
        if node.name in self.mapping:
            node.name = self.mapping[node.name]
        return node

    def visit_Name(self, node):
        if node.id in self.mapping:
            node.id = self.mapping[node.id]
        return node


def _eval_probe_group(check, probe_results):
    """Evaluate a check that expanded into one or more probes: every probe
    must pass. Expected exception names accept the structurally bound
    student name as well as the required name."""
    aliases = check.get("aliases") or {}
    for pr in probe_results:
        status = pr.get("status")
        if status == "error":
            return False, "module could not load for probing"
        if status == "construct_error":
            return False, "could not build {} — {}".format(
                check.get("target") or check.get("construct", "object"),
                pr.get("detail", ""))
        if check["type"] == "functional_call_raises":
            want = check.get("expected_exception", "Exception")
            exc = pr.get("exc")
            if status != "raised":
                return False, check.get("fail", "no exception raised (method did not guard this case)")
            if exc not in (want, aliases.get(want)):
                return False, "raised {} instead of {}".format(exc, want)
        elif check["type"] == "functional_property_test":
            if status != "ok":
                return False, pr.get("detail", "property sequence failed")
        elif check["type"] == "functional_call_returns":
            if status == "raised":
                return False, "unexpected exception {}: {}".format(
                    pr.get("exc"), pr.get("detail", ""))
            val = pr.get("value")
            em = check.get("expected_match") or {}
            if em:
                idx = em.get("index")
                got = val[idx] if isinstance(val, list) and idx < len(val) else None
                want = em.get("value")
                if isinstance(want, bool):
                    if not (isinstance(got, bool) and got == want):
                        return False, "result[{}] = {!r}, expected {!r}".format(idx, got, want)
                elif got != want:
                    return False, "result[{}] = {!r}, expected {!r}".format(idx, got, want)
            reasons = check.get("expected_reason_contains") or []
            if reasons:
                blob = json.dumps(val).lower()
                if not any(str(r).lower() in blob for r in reasons):
                    return False, "reason did not contain any of {}".format(list(reasons))
    return True, "all probes passed"


def grade_submission(path, src, rubric):
    """Returns {task_scores: {id: score}, failed: [(task_id, deduct, detail)],
    penalties: [(amount, reason)], final: float, crash: str|None,
    aliases: {required: student}}."""
    settings = rubric.get("settings", {})
    timeout_s = float(settings.get("timeout_s", 15))
    memory_mb = int(settings.get("memory_mb", 512))
    naming_deduct = float(settings.get("naming_deduct", 0.1))

    tree, _ok, _failed = parse_lenient(src)

    # ---- structural interface binding (rename tolerance) -----------------
    aliases, bindings = {}, []
    sandbox_aliases = {}
    if tree is not None:
        aliases, bindings = resolve_class_aliases(tree, rubric)
        if aliases:
            # transformer speaks student-name -> required-name
            tree = _AliasTransformer({s: r for r, s in aliases.items()}).visit(tree)
            sandbox_aliases = dict(aliases)   # worker: ns[req] = ns[student]

    # ---- one sandbox run carrying every dynamic/functional probe ---------
    probes, dynamic_checks = [], []
    probe_owner = {}     # probe id -> (task_id, chk)
    for task in rubric["tasks"]:
        for chk in task.get("checks", []):
            ctype = chk["type"]
            if ctype in _DYNAMIC_TYPES:
                dynamic_checks.append((task["id"], chk))
            elif ctype in _PROBE_TYPES:
                for pr in _probe_of(chk):
                    probes.append(pr)
                    probe_owner[pr["id"]] = (task["id"], chk)
                dynamic_checks.append((task["id"], chk))

    run_result = {"crash": None, "stdout_tail": "", "duration_ms": 0,
                  "probes": {}}
    if dynamic_checks:
        run_result = run_sandboxed(path, probes, timeout_s, memory_mb,
                                   aliases=sandbox_aliases)

    # ---- evaluate every check -------------------------------------------
    failed = []          # (task_id, deduct, detail)
    for task in rubric["tasks"]:
        for chk in task.get("checks", []):
            ctype = chk["type"]
            if ctype in _STATIC_ALIASES:
                ctype = _STATIC_ALIASES[ctype]
                chk = {**chk, "type": ctype}
            deduct = float(chk.get("deduct", 0))
            try:
                if aliases and ctype in ("regex_present", "forbidden_pattern",
                                         "comment_regex_present"):
                    chk = {**chk, "aliases": aliases}
                if chk.get("stdout_ignorecase") is None:
                    chk = {**chk, "stdout_ignorecase":
                           bool(settings.get("stdout_ignorecase"))}
                if ctype in _STATIC_TYPES:
                    passed, detail = get_check(ctype)(tree, src, chk)
                elif ctype in _DYNAMIC_TYPES:
                    passed, detail = _eval_dynamic_check(chk, run_result)
                elif ctype in _PROBE_TYPES:
                    probe_results = [run_result["probes"].get(
                        pid, {"status": "error", "detail": "probe missing"})
                        for pid in sorted(pr["id"] for pr in probes
                                          if pr["id"].startswith(chk["id"] + "::")
                                          or pr["id"] == chk["id"])]
                    passed, detail = _eval_probe_group(chk, probe_results)
                else:
                    passed, detail = False, "unknown check type '{}'".format(ctype)
            except Exception as exc:      # a broken check must not kill grading
                passed, detail = False, "check error: {}".format(exc)
            if not passed:
                detail = chk.get("fail", detail)
                failed.append((task["id"], deduct, detail))

    # naming-convention deduction for each structurally bound class: the
    # logic earns its marks, the non-standard name costs a small, explicit
    # amount instead of wiping out the task
    for required, candidate, score in bindings:
        task_id = next((t["id"] for t in rubric["tasks"]
                        for c in t.get("checks", [])
                        if c.get("class") == required),
                       rubric["tasks"][0]["id"])
        failed.append((task_id, naming_deduct,
                       "class '{}' accepted for '{}' (structural match "
                       "{:.0%}); non-standard naming".format(
                           candidate, required, score)))

    task_scores = {t["id"]: t["weight"] for t in rubric["tasks"]}
    for task_id, deduct, _d in failed:
        task_scores[task_id] = max(0.0, task_scores.get(task_id, 0.0) - deduct)

    return {
        "task_scores": task_scores,
        "failed": failed,
        "final": sum(task_scores.values()),
        "crash": run_result["crash"],
        "aliases": aliases,
    }


def grade_batch(files_by_roll, rubric):
    """files_by_roll: {roll: [(filename, path, source), ...]}.
    Returns rows (one per roll) applying the multi-file penalty (-2.0 when a
    student submitted more than one file; their best file counts)."""
    rows = []
    for roll in sorted(files_by_roll):
        entries = files_by_roll[roll]
        graded = []
        for fname, path, src in entries:
            g = grade_submission(path, src, rubric)
            graded.append((g, fname))
        graded.sort(key=lambda t: -t[0]["final"])
        best, best_name = graded[0]
        penalties = 0.0
        report_bits = []
        for task_id, deduct, detail in best["failed"]:
            report_bits.append("{}: -{} ({})".format(task_id, deduct, detail))
        if len(entries) > 1:
            mf = abs(float(rubric.get("settings", {}).get(
                "multi_file_deduction", 2.0)))
            penalties += -mf
            report_bits.append("multi-file submission ({} files): -{:.1f}".format(
                len(entries), mf))
        if best["crash"]:
            report_bits.append("runtime: {}".format(best["crash"]))
        final = max(0.0, best["final"] + penalties)
        rows.append({
            "roll": roll,
            "filename": best_name,
            "task_scores": best["task_scores"],
            "penalties": penalties,
            "final": final,
            "report": "; ".join(report_bits) or "None",
            "other_files": [f for f, _p, _s in entries[1:]],
            "aliases": best.get("aliases", {}),
        })
    return rows


def run_grade(directory, rubric_path, out_csv, timeout_s=None, memory_mb=None):
    """Grade every submission in `directory` (or ZIP) against the rubric."""
    import csv
    from .ingest import discover, extract_roll

    rubric = load_rubric(rubric_path)
    if timeout_s:
        rubric["settings"]["timeout_s"] = float(timeout_s)
    if memory_mb:
        rubric["settings"]["memory_mb"] = int(memory_mb)

    # if given a zip, extract to a temp dir first so sandbox has real paths
    if directory.lower().endswith(".zip"):
        tmp = tempfile.mkdtemp(prefix="copcat_grade_")
        from .loader import _safe_member_name
        with zipfile.ZipFile(directory) as zf:
            for member in zf.infolist():
                if member.is_dir():
                    continue
                safe = _safe_member_name(member.filename)
                if not safe:
                    continue
                target = os.path.join(tmp, safe)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with zf.open(member) as src_fh, open(target, "wb") as dst_fh:
                    dst_fh.write(src_fh.read())
        directory = tmp

    files_by_roll = {}
    for path in discover(directory):
        fname = os.path.basename(path)
        stem = os.path.splitext(fname)[0]
        roll = extract_roll(fname) or re.split(r"[_\-\s]+", stem.strip())[0].upper()
        with open(path, encoding="utf-8-sig", errors="replace") as fh:
            src = fh.read()
        files_by_roll.setdefault(roll, []).append((fname, path, src))

    task_ids = [t["id"] for t in rubric["tasks"]]
    rows = grade_batch(files_by_roll, rubric)

    out_dir = os.path.dirname(os.path.abspath(out_csv))
    os.makedirs(out_dir, exist_ok=True)
    with open(out_csv, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, quoting=csv.QUOTE_MINIMAL)
        writer.writerow(["Roll_Number", "Filename"] +
                        ["Task_{}".format(i + 1) for i in range(len(task_ids))] +
                        ["Penalties", "Final_Score", "Deduction_Report"])
        for r in rows:
            writer.writerow(
                [r["roll"], r["filename"]] +
                ["{:.2f}".format(r["task_scores"].get(t, 0.0)) for t in task_ids] +
                ["{:.2f}".format(r["penalties"]), "{:.2f}".format(r["final"]),
                r["report"]])

    n = len(rows)
    if n:
        avg = sum(r["final"] for r in rows) / n
        best = max(rows, key=lambda r: r["final"])
        worst = min(rows, key=lambda r: r["final"])
        print("Graded {} submissions against '{}'".format(
            n, rubric.get("lab", "?")))
        print("Average: {:.2f} | Top: {} ({:.2f}) | Lowest: {} ({:.2f})".format(
            avg, best["roll"], best["final"], worst["roll"], worst["final"]))
    print("Wrote {}".format(out_csv))
    return rows
