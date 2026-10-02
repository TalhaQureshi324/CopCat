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
    result["duration_ms"] = int((time.perf_counter() - t0) * 1000)
    result["stdout_tail"] = buf.getvalue()[-4000:]

    for probe in spec.get("probes", []):
        pid = probe["id"]
        if not mod_ns:
            result["probes"][pid] = {"status": "error",
                                     "detail": "module failed to load"}
            continue
        constructs = probe["construct"]
        if not isinstance(constructs, list):
            constructs = [constructs]
        obj = None
        last_err = None
        try:
            for c in constructs:               # rubric may offer alternate
                scope = dict(mod_ns)           # constructor signatures
                try:
                    obj = eval(c, scope)       # noqa: S307 - sandboxed
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
            extra = probe_out.getvalue()
            if extra:
                result["probes"][pid]["detail"] = extra[:200]
        except BaseException as exc:
            result["probes"][pid] = {"status": "raised",
                                     "exc": type(exc).__name__,
                                     "detail": str(exc)[:200]}

    json.dump(result, sys.stdout)


if __name__ == "__main__":
    main()
