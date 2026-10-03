"""Sandbox worker: runs INSIDE the isolated child process (never in the
grader). Reads a JSON spec on stdin, imports the student submission,
executes functional probes, prints a JSON result.

Hostile-input defenses applied here:
* builtins.input is monkeypatched to raise EOFError (interactive menu
  submissions can't hang the grader waiting for text)
* stdin is /dev/null, cwd is a throwaway temp dir
* the parent additionally enforces timeout + memory via a Windows Job
  Object / POSIX rlimits (see sandbox.py)
"""

import builtins
import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import time
import traceback


def _blocked_input(prompt="", /):
    raise EOFError("input() is disabled inside the CopCat sandbox")


def main():
    spec = json.loads(sys.stdin.read())
    result = {"crash": None, "stdout_tail": "", "duration_ms": 0, "probes": {}}

    builtins.input = _blocked_input
    sys.stdin = open(os.devnull, "r")
    os.chdir(tempfile.mkdtemp(prefix="copcat_sbx_"))

    workdir = spec["workdir"]
    mod_ns = {}
    buf = io.StringIO()
    t0 = time.perf_counter()
    mod = None
    try:
        spec_obj = importlib.util.spec_from_file_location("submission", workdir)
        mod = importlib.util.module_from_spec(spec_obj)
        sys.modules["submission"] = mod
        with contextlib.redirect_stdout(buf):
            spec_obj.loader.exec_module(mod)
    except BaseException as exc:  # student code may raise anything
        result["crash"] = "{}: {}".format(type(exc).__name__, str(exc)[:300])
        if os.environ.get("COPCAT_DEBUG"):
            traceback.print_exc(file=sys.stderr)
    # salvage: classes/functions defined before a crash still support probes
    if mod is not None:
        mod_ns = {k: v for k, v in vars(mod).items() if k != "__builtins__"}
    # structural interface binding: expose the student's class under the
    # rubric-required name so probes can construct it
    for required, student in (spec.get("aliases") or {}).items():
        if student in mod_ns:
            mod_ns[required] = mod_ns[student]
    result["duration_ms"] = int((time.perf_counter() - t0) * 1000)
    result["stdout_tail"] = buf.getvalue()[-4000:]

    def _jsonsafe(v):
        if isinstance(v, tuple):
            return [_jsonsafe(x) for x in v]
        if isinstance(v, list):
            return [_jsonsafe(x) for x in v]
        if isinstance(v, dict):
            return {str(k): _jsonsafe(x) for k, x in v.items()}
        if isinstance(v, (str, int, float, bool)) or v is None:
            return v
        return repr(v)

    for probe in spec.get("probes", []):
        pid = probe["id"]
        if not mod_ns:
            result["probes"][pid] = {"status": "error",
                                     "detail": "module failed to load"}
            continue

        # ---- sequence probes (lifecycle / property scripts) ---------------
        if probe.get("kind") == "sequence":
            probe_out = io.StringIO()
            try:
                with contextlib.redirect_stdout(probe_out):
                    obj = eval(probe["target"] + "()", dict(mod_ns))  # noqa: S307
                    failures = _run_sequence(obj, probe.get("steps", []))
                if failures:
                    result["probes"][pid] = {"status": "fail",
                                             "detail": "; ".join(failures[:5])}
                else:
                    result["probes"][pid] = {"status": "ok",
                                             "result": "sequence held"}
            except BaseException as exc:
                result["probes"][pid] = {"status": "raised",
                                         "exc": type(exc).__name__,
                                         "detail": str(exc)[:200]}
            continue

        # ---- call_args probes (function + plain JSON args) ----------------
        if probe.get("kind") == "call_args":
            probe_out = io.StringIO()
            try:
                with contextlib.redirect_stdout(probe_out):
                    fn = eval(probe["construct"], dict(mod_ns))       # noqa: S307
                    if not callable(fn):
                        raise TypeError("construct is not callable")
                    val = fn(*probe.get("args", []))
                result["probes"][pid] = {"status": "ok",
                                         "value": _jsonsafe(val)}
            except BaseException as exc:
                result["probes"][pid] = {"status": "raised",
                                         "exc": type(exc).__name__,
                                         "detail": str(exc)[:200]}
            continue

        constructs = probe["construct"]
        if not isinstance(constructs, list):
            constructs = [constructs]
        obj = None
        last_err = None
        construct_out = io.StringIO()
        try:
            with contextlib.redirect_stdout(construct_out):
                # student __init__/__new__ prints must not corrupt the JSON
                for c in constructs:           # rubric may offer alternate
                    scope = dict(mod_ns)       # constructor signatures
                    try:
                        obj = eval(c, scope)   # noqa: S307 - sandboxed
                        last_err = None
                        break
                    except BaseException as exc:
                        last_err = exc
        except BaseException as exc:
            last_err = exc
        if last_err is not None or obj is None:
            # construct failing (missing class, bad __init__) is NOT the same
            # as the call raising the expected custom exception
            result["probes"][pid] = {"status": "construct_error",
                                     "exc": type(last_err).__name__,
                                     "detail": str(last_err)[:200]}
            continue
        try:
            scope["obj"] = obj
            probe_out = io.StringIO()
            with contextlib.redirect_stdout(probe_out):
                if probe.get("set_expr"):
                    exec(probe["set_expr"], scope)    # noqa: S307 - sandboxed
                if probe.get("call"):
                    val = eval(probe["call"], scope)  # noqa: S307 - sandboxed
                    result["probes"][pid] = {"status": "ok",
                                             "result": repr(val)[:200]}
                else:
                    result["probes"][pid] = {"status": "ok",
                                             "result": "constructed"}
            # student __str__/__repr__ prints must never corrupt the JSON
            extra = construct_out.getvalue() + probe_out.getvalue()
            if extra:
                result["probes"][pid]["detail"] = extra[:200]
        except BaseException as exc:
            result["probes"][pid] = {"status": "raised",
                                     "exc": type(exc).__name__,
                                     "detail": str(exc)[:200]}

    json.dump(result, sys.stdout)


def _run_sequence(obj, steps):
    """Generic step runner supporting two dialects.

    1. method-call steps: {method: args-list-or-scalar} calls obj.method;
       {assert_attr: expected} asserts obj.attr() == expected
    2. lifecycle steps (model-based agents):
       {initial_model: {...}}                       -> obj.model = {...}
       {step_N_percept: [...]}                      -> obj.update_state(...)
       {step_N_action: "Suck"}                      -> obj.act(percept) == value
       {expected_model_step_N: {...}}               -> subset of obj.model
    Returns a list of failure strings (empty = pass).
    """
    import re as _re
    failures, percepts = [], {}
    for step in steps:
        if not isinstance(step, dict) or len(step) != 1:
            continue
        key, val = next(iter(step.items()))

        m = _re.match(r"^step_(\d+)_percept$", key)
        if m:
            percepts[m.group(1)] = val
            updater = getattr(obj, "update_state", None)
            if updater:
                updater(val)
            continue
        m = _re.match(r"^step_(\d+)_action$", key)
        if m:
            percept = percepts.get(m.group(1))
            actual = obj.act(percept) if hasattr(obj, "act") else None
            if actual != val:
                failures.append("step {}: action {!r} != expected {!r}".format(
                    m.group(1), actual, val))
            continue
        m = _re.match(r"^expected_(\w+)_step_(\d+)$", key)
        if m:
            attr = m.group(1)
            model = getattr(obj, attr, {})
            for k2, v2 in (val or {}).items():
                if not isinstance(model, dict) or model.get(k2) != v2:
                    failures.append("{}.{} = {!r}, expected {!r}".format(
                        attr, k2, model.get(k2) if isinstance(model, dict) else "?", v2))
            continue
        m = _re.match(r"^initial_(\w+)$", key)
        if m:
            setattr(obj, m.group(1), val)
            continue
        m = _re.match(r"^assert_(\w+)$", key)
        if m:
            actual = getattr(obj, m.group(1))()
            if actual != val:
                failures.append("{}() = {!r}, expected {!r}".format(
                    m.group(1), actual, val))
            continue
        args = val if isinstance(val, list) else [val]
        getattr(obj, key)(*args)
    return failures


if __name__ == "__main__":
    main()
