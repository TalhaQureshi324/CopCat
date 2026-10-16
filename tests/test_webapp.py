"""Web dashboard tests: upload -> run -> results, job history, deletion.

Runs execute synchronously (the design that makes Vercel hosting work),
so POST .../run returns the final summary in its own response.
"""

import io
import os
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from copcat.store import BlobStore, DiskStore, get_store
from copcat.webapp import app

RUBRIC = Path(__file__).resolve().parent.parent / "examples" / "rubric_lab02.yaml"

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


def test_full_flow_upload_audit_dossier(tmp_path, monkeypatch):
    monkeypatch.setenv("COPCAT_RESULTS_DIR", str(tmp_path))
    r = client.post("/api/jobs", files={
        "submissions": ("subs.zip", _zip_bytes(), "application/zip")})
    assert r.status_code == 200
    job_id = r.json()["job_id"]

    r = client.post(f"/api/jobs/{job_id}/run", data={"mode": "audit"})
    assert r.status_code == 200
    assert r.json()["status"] == "done"       # synchronous completion

    d = client.get(f"/api/jobs/{job_id}").json()
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


def test_history_gradebook_delete_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("COPCAT_RESULTS_DIR", str(tmp_path))
    r = client.post("/api/jobs", files={
        "submissions": ("subs.zip", _zip_bytes(), "application/zip"),
        "rubric": ("rubric_lab02.yaml", RUBRIC.read_bytes(), "text/yaml")})
    assert r.status_code == 200
    job_id = r.json()["job_id"]

    r = client.post(f"/api/jobs/{job_id}/run", data={"mode": "grade"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "done", d.get("error")
    assert len(d["summary"]["gradebook"]) == 4

    # gradebook artifact is downloadable
    r = client.get(f"/api/jobs/{job_id}/gradebook.csv")
    assert r.status_code == 200
    assert b"roll" in r.content.lower()

    # job history lists it (so a dashboard refresh can find it again)
    r = client.get("/api/jobs")
    assert any(j["job_id"] == job_id and j["status"] == "done"
               for j in r.json()["jobs"])

    # a fresh store instance (server restart) still sees the job
    fresh = DiskStore(str(tmp_path))
    assert fresh.get_meta(job_id)["status"] == "done"

    # delete removes registry + artifacts
    assert client.delete(f"/api/jobs/{job_id}").status_code == 200
    assert client.get(f"/api/jobs/{job_id}").status_code == 404
    assert fresh.get_meta(job_id) is None


def test_aggregate_stats_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("COPCAT_RESULTS_DIR", str(tmp_path))
    before = client.get("/api/stats").json()
    r = client.post("/api/jobs", files={
        "submissions": ("subs.zip", _zip_bytes(), "application/zip")})
    job_id = r.json()["job_id"]
    client.post(f"/api/jobs/{job_id}/run", data={"mode": "audit"})
    after = client.get("/api/stats").json()
    assert after["jobs"] == before["jobs"] + 1
    assert after["submissions"] >= before["submissions"] + 4
    assert after["needs_review"] >= before["needs_review"] + 1


def test_store_backend_selection(monkeypatch):
    monkeypatch.delenv("BLOB_READ_WRITE_TOKEN", raising=False)
    assert isinstance(get_store(), DiskStore)
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "vercel_blob_rw_test")
    assert isinstance(get_store(), BlobStore)


def test_report_traversal_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("COPCAT_RESULTS_DIR", str(tmp_path))
    assert client.get("/api/jobs/abc/report/..%5C..%5Csecret").status_code == 404
    assert client.get("/api/jobs/abc/report/nope.txt").status_code == 404
