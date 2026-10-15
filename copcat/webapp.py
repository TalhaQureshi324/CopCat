"""CopCat web GUI: dashboard for non-technical users.

Flow: upload a submissions ZIP (or loose files) + optional rubric YAML ->
run Audit / Grading / Both -> interactive gradebook, cluster view, per-pair
dossiers and diffs, one-click CSV export.

Execution is **synchronous**: the run request does the work and returns
the final summary in its own response.  This is what makes serverless
hosting (Vercel) possible — background threads die when the handler
returns there.  Locally the same synchronous flow works unchanged.

State is never kept in RAM: every upload, artifact and registry entry
goes through :mod:`copcat.store` (local disk, or Vercel Blob when
hosted), so job history survives page refreshes and server restarts.

Run locally:  copcat web   (or: uvicorn copcat.webapp:app --port 8000)
"""

import os
import time
import uuid

from .models import AuditConfig
from .store import get_store

try:
    from fastapi import FastAPI, File, Form, Request, UploadFile
    from fastapi.responses import (FileResponse, HTMLResponse,
                                   JSONResponse, PlainTextResponse, Response)
    from starlette.concurrency import run_in_threadpool
except ImportError:      # pragma: no cover
    raise SystemExit("web extras missing: pip install copcat[web]")

app = FastAPI(title="CopCat", docs_url=None, redoc_url=None)

WEB_ROOT = os.path.dirname(os.path.abspath(__file__))
_STALE_RUN_S = 15 * 60          # a "running" job older than this is retryable


def _auth(request: Request):
    """Optional shared-key gate. Set COPCAT_ACCESS_TOKEN to require it."""
    token = os.environ.get("COPCAT_ACCESS_TOKEN")
    if token and request.headers.get("x-copcat-key") != token:
        return JSONResponse({"error": "unauthorized: access key required"},
                            status_code=401)
    return None


def _meta_view(meta):
    return {"job_id": meta.get("job_id"), "status": meta.get("status"),
            "mode": meta.get("mode"), "created": meta.get("created"),
            "error": meta.get("error"), "summary": meta.get("summary"),
            "runtime_s": meta.get("runtime_s")}


# --------------------------------------------------------------------------
# job execution (synchronous, in a worker thread so the event loop lives)
# --------------------------------------------------------------------------
def _execute(store, meta, mode, preserve):
    job_id = meta["job_id"]
    started = time.time()
    ws = store.workspace(job_id)
    summary = {}
    try:
        paths = store.materialize(job_id, ws, meta.get("uploads"))
        preserved = tuple(x.strip() for x in (preserve or "").split(",")
                          if x.strip())
        cfg = AuditConfig(preserved=preserved)
        if paths.get("starter"):
            cfg.starters = (paths["starter"],)
        out_dir = os.path.join(ws, "output")
        if mode in ("audit", "both"):
            from .audit import run_audit
            pairs = run_audit(paths["submissions"], cfg, out_dir, workers=1)
            summary["pairs"] = [
                {"a": p.roll_a, "b": p.roll_b,
                 "blended": round(100 * p.blended, 1), "flag": p.flag}
                for p in pairs if p.flag != "CLEAN"]
        if mode in ("grade", "both"):
            if not paths.get("rubric"):
                summary["gradebook"] = []
            else:
                from .rubric import run_grade
                rows = run_grade(paths["submissions"], paths["rubric"],
                                 os.path.join(out_dir, "grade_report.csv"))
                summary["gradebook"] = [
                    {"roll": r["roll"], "filename": r["filename"],
                     "final": round(r["final"], 2), "report": r["report"],
                     "task_scores": {k: round(v, 2)
                                     for k, v in r["task_scores"].items()}}
                    for r in rows]
        runtime = round(time.time() - started, 1)
        meta["result_urls"] = store.persist_results(job_id, out_dir)
        meta["status"], meta["summary"] = "done", summary
        meta["runtime_s"] = runtime
        meta["error"] = None
        store.save_meta(meta)
        return {"job_id": job_id, "status": "done", "summary": summary,
                "runtime_s": runtime, "error": None}
    except Exception as exc:          # surface engine errors in the dashboard
        meta["status"] = "error"
        meta["error"] = "{}: {}".format(type(exc).__name__, exc)
        meta["runtime_s"] = round(time.time() - started, 1)
        store.save_meta(meta)
        return {"job_id": job_id, "status": "error", "summary": None,
                "runtime_s": meta["runtime_s"], "error": meta["error"]}
    finally:
        store.cleanup(ws)


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------
@app.post("/api/jobs")
async def create_job(request: Request,
                     submissions: UploadFile = File(...),
                     rubric: UploadFile = File(None),
                     starter: UploadFile = File(None)):
    denied = _auth(request)
    if denied:
        return denied
    store = get_store()
    job_id = uuid.uuid4().hex[:12]
    uploads = {"submissions": store.save_upload(
        job_id, "submissions", submissions.filename or "submissions.zip",
        await submissions.read())}
    if rubric and rubric.filename:
        uploads["rubric"] = store.save_upload(job_id, "rubric",
                                              rubric.filename,
                                              await rubric.read())
    if starter and starter.filename:
        uploads["starter"] = store.save_upload(job_id, "starter",
                                               starter.filename,
                                               await starter.read())
    store.save_meta({"job_id": job_id, "status": "uploaded", "mode": None,
                     "created": time.strftime("%Y-%m-%d %H:%M:%S"),
                     "uploads": uploads, "preserve": "",
                     "summary": None, "runtime_s": None, "error": None,
                     "result_urls": {}})
    return {"job_id": job_id}


@app.post("/api/jobs/{job_id}/run")
async def run_job(job_id: str, request: Request,
                  mode: str = Form("both"), preserve: str = Form("")):
    denied = _auth(request)
    if denied:
        return denied
    store = get_store()
    meta = store.get_meta(job_id)
    if not meta:
        return JSONResponse({"error": "unknown job"}, status_code=404)
    if meta.get("status") == "running":
        started = meta.get("run_started") or 0
        if time.time() - started < _STALE_RUN_S:
            return JSONResponse({"error": "already running"},
                                status_code=409)
    meta["status"], meta["mode"] = "running", mode
    meta["preserve"], meta["error"] = preserve, None
    meta["run_started"] = time.time()
    store.save_meta(meta)

    result = await run_in_threadpool(_execute, store, meta, mode, preserve)
    status = 200 if result["status"] == "done" else 500
    return JSONResponse(result, status_code=status)


@app.get("/api/jobs")
async def list_jobs(request: Request):
    denied = _auth(request)
    if denied:
        return denied
    rows = [_meta_view(m) for m in get_store().list_jobs()]
    rows.sort(key=lambda m: m.get("created") or "", reverse=True)
    return {"jobs": rows}


@app.get("/api/jobs/{job_id}")
async def job_status(job_id: str, request: Request):
    denied = _auth(request)
    if denied:
        return denied
    meta = get_store().get_meta(job_id)
    if not meta:
        return JSONResponse({"error": "unknown job"}, status_code=404)
    return _meta_view(meta)


@app.delete("/api/jobs/{job_id}")
async def delete_job(job_id: str, request: Request):
    denied = _auth(request)
    if denied:
        return denied
    store = get_store()
    if not store.get_meta(job_id):
        return JSONResponse({"error": "unknown job"}, status_code=404)
    store.delete_job(job_id)
    return {"deleted": job_id}


@app.get("/api/jobs/{job_id}/gradebook.csv")
async def gradebook(job_id: str, request: Request):
    denied = _auth(request)
    if denied:
        return denied
    data = get_store().open_result(job_id, "grade_report.csv")
    if data is None:
        return JSONResponse({"error": "no gradebook"}, status_code=404)
    return Response(content=data, media_type="text/csv",
                    headers={"content-disposition":
                             'attachment; filename="grade_report.csv"'})


@app.get("/api/jobs/{job_id}/report/{name}")
async def job_report_file(job_id: str, name: str, request: Request):
    """Serve generated artifacts: index.html, copcat_audit.csv/txt."""
    denied = _auth(request)
    if denied:
        return denied
    if "/" in name or "\\" in name or ".." in name or name.startswith("."):
        return JSONResponse({"error": "not found"}, status_code=404)
    data = get_store().open_result(job_id, name)
    if data is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    media = "text/html" if name.endswith(".html") else "text/plain"
    if name.endswith(".csv"):
        media = "text/csv"
    return Response(content=data, media_type=media)


@app.get("/api/jobs/{job_id}/dossier/{roll_a}/{roll_b}")
async def dossier(job_id: str, roll_a: str, roll_b: str, request: Request):
    denied = _auth(request)
    if denied:
        return denied
    name = "dossiers/dossier_{}__vs__{}.html".format(roll_a, roll_b)
    data = get_store().open_result(job_id, name)
    if data is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return Response(content=data, media_type="text/html")


@app.get("/healthz")
async def healthz():
    return PlainTextResponse("ok")


@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = os.path.join(WEB_ROOT, "webapp.html")
    with open(html_path, encoding="utf-8") as fh:
        return HTMLResponse(fh.read())
