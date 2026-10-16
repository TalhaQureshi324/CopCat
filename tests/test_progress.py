"""Run-progress callbacks: the web workspace shows live counts during a
run (Reading N submissions -> Comparing i/T pairs -> Grading i/T students),
so the engines must emit (phase, done, total) milestones.
"""

import shutil
from pathlib import Path

from copcat.audit import run_audit
from copcat.models import AuditConfig
from copcat.rubric import run_grade

ROOT = Path(__file__).resolve().parent.parent
RUBRIC = ROOT / "examples" / "rubric_lab02.yaml"

LIVE = (
    "class Employee:\n"
    "    def __init__(self, name, ident, salary):\n"
    "        self.name = name\n        self.ident = ident\n"
    "        self.salary = salary\n"
    "    def pay(self):\n        return self.salary\n"
    "\n"
    "class Manager(Employee):\n"
    "    def __init__(self, name, ident, salary, bonus):\n"
    "        super().__init__(name, ident, salary)\n"
    "        self.bonus = bonus\n"
    "    def pay(self):\n        return super().pay() + self.bonus\n"
    "\n"
    "m = Manager('a', 1, 10, 2)\n"
    "print(m.pay())\n")


def _build(tmp):
    tmp = Path(tmp)
    tmp.mkdir(parents=True, exist_ok=True)
    for name, src in (
            ("t01.py", LIVE),
            ("t02.py", LIVE.replace("Manager", "Lead").replace("bonus", "bns")),
            ("t03.py", "class X:\n    def q(self):\n        return 'q'\n"),
            ("t04.py", "class Y:\n    def w(self):\n        return 'w'\n")):
        (tmp / name).write_text(src, encoding="utf-8")
    return tmp


def test_audit_progress_milestones(tmp_path):
    batch = _build(tmp_path / "batch")
    seen = []
    run_audit(str(batch), AuditConfig(), str(tmp_path / "out"),
              progress=lambda ph, d, t: seen.append((ph, d, t)))
    phases = {ph for ph, _d, _t in seen}
    assert "load" in phases and "pairs" in phases
    load = [t for ph, d, t in seen if ph == "load"][-1]
    assert load == 4
    pair_steps = [(d, t) for ph, d, t in seen if ph == "pairs"]
    assert pair_steps[0] == (0, pair_steps[0][1])     # starts at zero
    assert pair_steps[-1][0] == pair_steps[-1][1]     # completes
    assert pair_steps[-1][1] > 0


def test_grade_progress_milestones(tmp_path):
    batch = _build(tmp_path / "batch")
    seen = []
    run_grade(str(batch), str(RUBRIC), str(tmp_path / "g.csv"),
              progress=lambda ph, d, t: seen.append((ph, d, t)))
    grade_steps = [(d, t) for ph, d, t in seen if ph == "grade"]
    assert grade_steps, "grading emitted no progress"
    assert grade_steps[0] == (0, 4)
    assert grade_steps[-1] == (4, 4)
