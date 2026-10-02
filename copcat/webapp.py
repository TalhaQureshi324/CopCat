"""CopCat web GUI: local FastAPI dashboard for non-technical users.

Flow: upload a submissions ZIP (or loose files) + optional rubric YAML ->
run Audit / Grading / Both -> interactive gradebook, cluster view, per-pair
dossiers and diffs, one-click CSV export.

Run:  copcat web  (or: uvicorn copcat.webapp:app --port 8000)
"""

import json
import os
import shutil
import tempfile
import threading
import time
import uuid

from .models import AuditConfig

try:
    from fastapi import FastAPI, File, Form, UploadFile
    from fastapi.responses import (FileResponse, HTMLResponse,
                                   JSONResponse, PlainTextResponse)
except ImportError:      # pragma: no cover
    raise SystemExit("web extras missing: pip install copcat[web]")

app = FastAPI(title="CopCat", docs_url=None, redoc_url=None)

JOBS = {}                    # job_id -> state dict
JOBS_LOCK = threading.Lock()
WEB_ROOT = os.path.dirname(os.path.abspath(__file__))


def _job_dir(job_id):
    root = os.path.join(tempfile.gettempdir(), "copcat_web")
    return os.path.join(root, job_id)


# --------------------------------------------------------------------------
# job execution (background thread)
# --------------------------------------------------------------------------
def _run_job_sync(job_id, mode, preserve):
    with JOBS_LOCK:
        job = JOBS[job_id]
    jdir = job["dir"]
    out_dir = os.path.join(jdir, "output")
    preserved = tuple(x.strip() for x in (preserve or "").split(",") if x.strip())
    cfg = AuditConfig(preserved=preserved)
    started = time.time()
    summary = {}
    try:
        if mode in ("audit", "both"):
            from .audit import run_audit
            pairs = run_audit(job["submissions"], cfg, out_dir, workers=1)
            summary["pairs"] = [
                {"a": p.roll_a, "b": p.roll_b,
                 "blended": round(100 * p.blended, 1), "flag": p.flag}
                for p in pairs if p.flag != "CLEAN"]
        if mode in ("grade", "both"):
            if not job["rubric"]:
                summary["gradebook"] = []
            else:
                from .rubric import run_grade
                rows = run_grade(job["submissions"], job["rubric"],
                                 os.path.join(out_dir, "grade_report.csv"))
                summary["gradebook"] = [
                    {"roll": r["roll"], "filename": r["filename"],
                     "final": round(r["final"], 2), "report": r["report"],
                     "task_scores": {k: round(v, 2)
                                     for k, v in r["task_scores"].items()}}
                    for r in rows]
        job["summary"] = summary
        job["runtime_s"] = round(time.time() - started, 1)
        job["status"] = "done"
    except Exception as exc:          # surface engine errors in the dashboard
        job["status"] = "error"
        job["error"] = "{}: {}".format(type(exc).__name__, exc)


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------
@app.post("/api/jobs")
async def create_job(submissions: UploadFile = File(...),
                     rubric: UploadFile = File(None)):
    job_id = uuid.uuid4().hex[:12]
    jdir = _job_dir(job_id)
    sub_dir = os.path.join(jdir, "submissions")
    os.makedirs(sub_dir, exist_ok=True)
    target = os.path.join(sub_dir, submissions.filename or "submissions.zip")
    with open(target, "wb") as fh:
        fh.write(await submissions.read())
    rubric_path = None
    if rubric and rubric.filename:
        rubric_path = os.path.join(jdir, "rubric.yaml")
        with open(rubric_path, "wb") as fh:
            fh.write(await rubric.read())
    with JOBS_LOCK:
        JOBS[job_id] = {"status": "uploaded", "dir": jdir,
                        "submissions": target, "rubric": rubric_path,
                        "mode": None, "error": None, "summary": None}
    return {"job_id": job_id}


@app.post("/api/jobs/{job_id}/run")
async def run_job(job_id: str, mode: str = Form("both"),
                  preserve: str = Form("")):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return JSONResponse({"error": "unknown job"}, status_code=404)
        if job["status"] == "running":
            return JSONResponse({"error": "already running"}, status_code=409)
        job["status"], job["mode"], job["error"] = "running", mode, None
    threading.Thread(target=_run_job_sync, args=(job_id, mode, preserve),
                     daemon=True).start()
    return {"job_id": job_id, "status": "running"}


@app.get("/api/jobs/{job_id}")
async def job_status(job_id: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return JSONResponse({"error": "unknown job"}, status_code=404)
        return {"status": job["status"], "mode": job["mode"],
                "error": job["error"], "summary": job.get("summary"),
                "runtime_s": job.get("runtime_s")}


@app.get("/api/jobs/{job_id}/gradebook.csv")
async def gradebook(job_id: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    path = os.path.join(job["dir"], "output", "grade_report.csv")
    if not os.path.exists(path):
        return JSONResponse({"error": "no gradebook"}, status_code=404)
    return FileResponse(path, media_type="text/csv",
                        filename="grade_report.csv")


@app.get("/api/jobs/{job_id}/report/{name}")
async def job_report_file(job_id: str, name: str):
    """Serve generated artifacts: index.html, copcat_audit.csv/txt,
    diffs/*.html, dossiers/*.html"""
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    base = os.path.join(job["dir"], "output")
    target = os.path.normpath(os.path.join(base, name))
    if not target.startswith(base) or not os.path.isfile(target):
        return JSONResponse({"error": "not found"}, status_code=404)
    media = "text/html" if name.endswith(".html") else "text/plain"
    if name.endswith(".csv"):
        media = "text/csv"
    return FileResponse(target, media_type=media)


@app.get("/api/jobs/{job_id}/dossier/{roll_a}/{roll_b}")
async def dossier(job_id: str, roll_a: str, roll_b: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    path = os.path.join(job["dir"], "output", "dossiers",
                        "dossier_{}__vs__{}.html".format(roll_a, roll_b))
    if not os.path.isfile(path):
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(path, media_type="text/html")


@app.get("/healthz")
async def healthz():
    return PlainTextResponse("ok")


@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = os.path.join(WEB_ROOT, "webapp.html")
    with open(html_path, encoding="utf-8") as fh:
        return HTMLResponse(fh.read())
