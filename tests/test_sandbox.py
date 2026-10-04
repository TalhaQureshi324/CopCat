"""Sandbox containment tests: student code must never escape or hang the
grader. These run on both Windows (Job Object) and POSIX (rlimits) in CI.

input() is mocked (returns sequential numeric strings then "") so top-level
input() calls don't crash the module — submissions run to completion and
functional probes can reach all functions."""

import os

from copcat.sandbox import run_sandboxed


def _write(tmp, name, code):
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(code)
    return path


def test_custom_exception_probes(tmp_path):
    p = _write(tmp_path, "ok.py", (
        "class BankError(Exception): pass\n"
        "class Acc:\n"
        "    def __init__(self, bal): self.bal = bal\n"
        "    def withdraw(self, amt):\n"
        "        if amt <= 0: raise BankError('bad amount')\n"
        "        if amt > self.bal: raise BankError('insufficient')\n"
        "        self.bal -= amt\n"))
    r = run_sandboxed(p, [
        {"id": "neg", "construct": "Acc(100)", "call": "obj.withdraw(-5)",
         "expect": "raises_any"},
        {"id": "named", "construct": "Acc(100)", "call": "obj.withdraw(-5)",
         "expect": "raises:BankError"},
    ], timeout_s=10)
    assert r["crash"] is None
    assert r["probes"]["neg"]["exc"] == "BankError"
    assert r["probes"]["named"]["exc"] == "BankError"


def test_construct_error_is_not_raises(tmp_path):
    p = _write(tmp_path, "partial.py", "class A:\n    pass\n")
    r = run_sandboxed(p, [{"id": "x", "construct": "Missing(1)",
                           "call": "obj.go()", "expect": "raises_any"}],
                      timeout_s=10)
    assert r["probes"]["x"]["status"] == "construct_error"


def test_input_bomb_no_longer_crashes(tmp_path):
    """input() returns mock values — the module imports cleanly and all
    functions are defined, so probes work."""
    p = _write(tmp_path, "menu.py",
               "name = input('name: ')\n"
               "def greet():\n    return 'hello ' + name\n")
    r = run_sandboxed(p, [{"id": "g", "construct": "greet()",
                           "expect": "ok"}], timeout_s=10)
    assert r["crash"] is None
    assert r["probes"]["g"]["status"] == "ok"


def test_catchall_menu_loop_killed_by_timeout(tmp_path):
    """A catch-all while-True loop that swallows exceptions runs forever —
    the parent's hard timeout is the backstop."""
    p = _write(tmp_path, "menu2.py",
               "while True:\n"
               "    try:\n"
               "        c = input('> ')\n"
               "        print(c)\n"
               "    except Exception:\n"
               "        pass\n")
    r = run_sandboxed(p, [], timeout_s=5)
    assert r["crash"] and "timeout" in r["crash"]


def test_partial_namespace_full_salvage(tmp_path):
    """With mock inputs, the module imports cleanly — no partial salvage
    needed. All functions are available for probing."""
    p = _write(tmp_path, "ordered.py",
               "def factorial(n):\n"
               "    if n <= 1: return 1\n"
               "    return n * factorial(n-1)\n"
               "\n"
               "x = int(input('n: '))\n"
               "print(factorial(x))\n")
    r = run_sandboxed(p, [{"id": "f", "construct": "factorial(5)",
                           "call": "factorial(5) == 120", "expect": "truthy"}],
                      timeout_s=10)
    assert r["crash"] is None
    assert r["probes"]["f"]["status"] == "ok"


def test_runaway_loop_contained(tmp_path):
    p = _write(tmp_path, "bomb.py",
               "import os\nwhile True:\n    os.system('echo boom')\n")
    r = run_sandboxed(p, [], timeout_s=5)
    assert r["crash"] and "timeout" in r["crash"]


def test_student_prints_do_not_corrupt_results(tmp_path):
    p = _write(tmp_path, "chatty.py", (
        "class C:\n"
        "    def __init__(self): print('constructing!')\n"
        "    def __str__(self): print('printing!'); return 'C()'\n"))
    r = run_sandboxed(p, [{"id": "s", "construct": "C()",
                           "call": "str(obj)", "expect": "ok"}], timeout_s=10)
    assert r["probes"]["s"]["status"] == "ok"
    assert "constructing" in r["probes"]["s"].get("detail", "")
