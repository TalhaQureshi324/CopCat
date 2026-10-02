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

import os
import re

from .canon import parse_lenient
from .checks import get_check
from .sandbox import run_sandboxed

try:
    import yaml
except ImportError:      # pragma: no cover
    yaml = None

_STATIC_TYPES = {"exists_class", "exists_method", "has_attrs", "has_decorator",
                 "calls_super", "base_class", "name_mangled_attr",
                 "forbidden_pattern", "regex_present",
                 "comment_regex_present", "min_lines"}
_DYNAMIC_TYPES = {"runs_clean", "stdout_contains", "stdout_regex"}


class RubricError(Exception):
    pass


def load_rubric(path):
    if yaml is None:
        raise RubricError("PyYAML is required for rubric grading: pip install pyyaml")
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict) or "tasks" not in data:
        raise RubricError("rubric must be a mapping with a 'tasks' list")
    for i, task in enumerate(data["tasks"]):
        if "id" not in task or "weight" not in task:
            raise RubricError("task #{} needs 'id' and 'weight'".format(i + 1))
        for chk in task.get("checks", []):
            if "type" not in chk:
                raise RubricError("check without 'type' in task {}".format(task["id"]))
            if "construct" not in chk:      # probe checks are validated at run time
                get_check(chk["type"])      # raises on unknown static/dynamic types
    data.setdefault("settings", {})
    return data


def _probe_of(check):
    """Functional checks declare construct/call/set_expr + expect."""
    expect = check.get("expect", "ok")
    return {
        "id": check["id"],
        "construct": check["construct"],
        "call": check.get("call"),
        "set_expr": check.get("set_expr"),
        "expect": expect,
        "raises": expect.split(":", 1)[1] if expect.startswith("raises:") else None,
        "raises_any": expect == "raises_any",
    }


def _eval_dynamic_check(check, run_result):
    """(passed, detail) for runs_clean / stdout_contains / stdout_regex."""
    ctype = check["type"]
    if ctype == "runs_clean":
        if run_result["crash"]:
            return False, "crashes: {}".format(run_result["crash"])
        return True, "executes cleanly ({:.1f}s)".format(
            run_result["duration_ms"] / 1000.0)
    if ctype in ("stdout_contains", "stdout_regex"):
        out = run_result["stdout_tail"]
        if run_result["crash"] and not out:
            return False, "no output — crashed ({})".format(run_result["crash"])
        if ctype == "stdout_contains":
            needle = check.get("text", "")
            return (needle in out), "expected '{}' in output".format(needle)
        return (bool(re.search(check["pattern"], out)),
                "expected output /{}/".format(check["pattern"]))
    return False, "unknown dynamic check"


def _eval_probe(check, probe_result):
    expect = check.get("expect", "ok")
    status = probe_result.get("status")
    if status == "error":
        return False, "module could not load for probing"
    if status == "construct_error":
        return False, "could not build {} — {}".format(
            check.get("construct", "object"), probe_result.get("detail", ""))
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


def grade_submission(path, src, rubric):
    """Returns {task_scores: {id: score}, failed: [(task_id, deduct, detail)],
    penalties: [(amount, reason)], final: float, crash: str|None}."""
    settings = rubric.get("settings", {})
    timeout_s = float(settings.get("timeout_s", 15))
    memory_mb = int(settings.get("memory_mb", 512))

    tree, _ok, _failed = parse_lenient(src)

    # ---- one sandbox run carrying every dynamic/functional probe ---------
    probes, dynamic_checks = [], []
    for task in rubric["tasks"]:
        for chk in task.get("checks", []):
            if chk["type"] in _DYNAMIC_TYPES:
                dynamic_checks.append((task["id"], chk))
            elif chk["type"] not in _STATIC_TYPES:
                probes.append(_probe_of(chk))
                dynamic_checks.append((task["id"], chk))

    run_result = {"crash": None, "stdout_tail": "", "duration_ms": 0,
                  "probes": {}}
    if dynamic_checks:
        run_result = run_sandboxed(path, probes, timeout_s, memory_mb)

    # ---- evaluate every check -------------------------------------------
    failed = []          # (task_id, deduct, detail)
    for task in rubric["tasks"]:
        for chk in task.get("checks", []):
            ctype = chk["type"]
            deduct = float(chk.get("deduct", 0))
            try:
                if ctype in _STATIC_TYPES:
                    passed, detail = get_check(ctype)(tree, src, chk)
                elif ctype in _DYNAMIC_TYPES:
                    passed, detail = _eval_dynamic_check(chk, run_result)
                else:
                    probe_result = run_result["probes"].get(
                        chk["id"], {"status": "error", "detail": "probe missing"})
                    passed, detail = _eval_probe(chk, probe_result)
            except Exception as exc:      # a broken check must not kill grading
                passed, detail = False, "check error: {}".format(exc)
            if not passed:
                detail = chk.get("fail", detail)
                failed.append((task["id"], deduct, detail))

    task_scores = {t["id"]: t["weight"] for t in rubric["tasks"]}
    for task_id, deduct, _d in failed:
        task_scores[task_id] = max(0.0, task_scores.get(task_id, 0.0) - deduct)

    return {
        "task_scores": task_scores,
        "failed": failed,
        "final": sum(task_scores.values()),
        "crash": run_result["crash"],
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
            penalties += -2.0
            report_bits.append("multi-file submission ({} files): -2.0".format(
                len(entries)))
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
        })
    return rows


def run_grade(directory, rubric_path, out_csv, timeout_s=None, memory_mb=None):
    """Grade every submission in `directory` against the rubric; write CSV."""
    import csv
    from .ingest import discover, extract_roll

    rubric = load_rubric(rubric_path)
    if timeout_s:
        rubric["settings"]["timeout_s"] = float(timeout_s)
    if memory_mb:
        rubric["settings"]["memory_mb"] = int(memory_mb)

    files_by_roll = {}
    for path in discover(directory):
        fname = os.path.basename(path)
        roll = extract_roll(fname)
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
