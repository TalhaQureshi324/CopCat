"""Web dashboard tests: upload -> run audit -> status -> dossier served."""

import io
import zipfile

from fastapi.testclient import TestClient

from copcat.webapp import app

client = TestClient(app)


def _zip_bytes():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("g01_clean_a.py",
                    "class Stack:\n    def push(self): pass\n")
        zf.writestr("g02_clean_b.py",
                    "class Pile:\n    def add(self): pass\n")
        # an identical copy pair (substantial) -> must be flagged
        body = ("class Employee:\n"
                "    def __init__(self, name, ident, salary):\n"
                "        self.name = name\n        self.ident = ident\n"
                "        self.salary = salary\n"
                "    def pay(self):\n        return self.salary\n"
                "\n"
                "class Manager(Employee):\n"
                "    def __init__(self, name, ident, salary, bonus):\n"
                "        super().__init__(name, ident, salary)\n"
                "        self.bonus = bonus\n"
                "    def pay(self):\n"
                "        return super().pay() + self.bonus\n"
                "\n"
                "class Developer(Employee):\n"
                "    def __init__(self, name, ident, salary, hours, rate):\n"
                "        super().__init__(name, ident, salary)\n"
                "        self.hours = hours\n        self.rate = rate\n"
                "    def pay(self):\n"
                "        return super().pay() + self.hours * self.rate\n"
                "\n"
                "staff = [Manager('a', 1, 10, 2), Developer('b', 2, 10, 3, 4)]\n"
                "for m in staff:\n    print(m.name, m.pay())\n")
        zf.writestr("g03_copy_a.py", body)
        zf.writestr("g04_copy_b.py", body + "\n# twin\n")
    buf.seek(0)
    return buf


def test_full_flow_upload_audit_dossier(tmp_path):
    r = client.post("/api/jobs", files={
        "submissions": ("subs.zip", _zip_bytes(), "application/zip")})
    assert r.status_code == 200
    job_id = r.json()["job_id"]

    r = client.post(f"/api/jobs/{job_id}/run", data={"mode": "audit"})
    assert r.status_code == 200

    # poll to completion
    import time
    for _ in range(120):
        d = client.get(f"/api/jobs/{job_id}").json()
        if d["status"] in ("done", "error"):
            break
        time.sleep(0.5)
    assert d["status"] == "done", d
    flagged = d["summary"]["pairs"]
    assert len(flagged) >= 1
    pair = flagged[0]

    # the dossier endpoint serves the generated packet
    r = client.get(f"/api/jobs/{job_id}/dossier/{pair['a']}/{pair['b']}")
    assert r.status_code == 200
    assert "Evidence dossier" in r.text

    # raw report files are served
    r = client.get(f"/api/jobs/{job_id}/report/copcat_audit.txt")
    assert r.status_code == 200

    # unknown job -> 404
    assert client.get("/api/jobs/nope").status_code == 404


def test_index_page_served():
    r = client.get("/")
    assert r.status_code == 200
    assert "CopCat" in r.text
