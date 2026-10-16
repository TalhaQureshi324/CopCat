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

import hashlib
import hmac
import json
import os
import secrets
import time
import urllib.error
import urllib.request
import uuid

from .models import AuditConfig
from .store import BlobStore, DiskStore, get_store

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

AUTH_CODE_TTL_S = 5 * 60        # access code validity (the owner hands it over)
AUTH_MAX_ATTEMPTS = 5           # wrong-code tries before the code is burned


# --------------------------------------------------------------------------
# access control
# --------------------------------------------------------------------------
def _auth_mode():
    """'code': request -> owner's email -> 5-min code -> session.
    'key': single shared master key.  'open': no gate configured."""
    if os.environ.get("RESEND_API_KEY") and os.environ.get("COPCAT_NOTIFY_EMAIL"):
        return "code"
    if os.environ.get("COPCAT_ACCESS_TOKEN"):
        return "key"
    return "open"


def _secret():
    material = os.environ.get("COPCAT_AUTH_SECRET") or "".join(filter(None, [
        os.environ.get("BLOB_READ_WRITE_TOKEN"),
        os.environ.get("COPCAT_ACCESS_TOKEN")])) or "copcat-insecure-default"
    return hashlib.sha256(material.encode("utf-8")).digest()


def _code_hash(code):
    return hashlib.sha256(_secret() + code.strip().encode("utf-8")).hexdigest()


def _session_token():
    hours = float(os.environ.get("COPCAT_SESSION_HOURS") or 24)
    exp = str(int(time.time() + hours * 3600))
    sig = hmac.new(_secret(), exp.encode("utf-8"), hashlib.sha256).hexdigest()
    return "{}.{}".format(exp, sig)


def _session_ok(token):
    try:
        exp, sig = token.split(".", 1)
        want = hmac.new(_secret(), exp.encode("utf-8"),
                        hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, want) and int(exp) > time.time()
    except Exception:
        return False


def _send_access_code(to, code, note):
    """Email the code to the deployment owner via the Resend REST API.
    Monkeypatched in tests."""
    body = json.dumps({
        "from": os.environ.get("COPCAT_EMAIL_FROM", "onboarding@resend.dev"),
        "to": [to],
        "subject": "CopCat access code: {}".format(code),
        "html": (
            "<p>A visitor requested access to your CopCat deployment.</p>"
            "<p style='font-size:26px;font-weight:700;letter-spacing:4px'>{}</p>"
            "<p>Share this code only with people you trust. It expires in "
            "<b>5 minutes</b>.{}<p><span style='color:#888'>No code was "
            "stored anywhere except a one-way hash on your own deployment."
            "</span></p>".format(
                code, "<p>Visitor note: <i>{}</i></p>".format(note)
                if note else ""))
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.resend.com/emails", data=body, method="POST",
        headers={
            "authorization": "Bearer " + os.environ["RESEND_API_KEY"],
            "content-type": "application/json",
            "accept": "application/json",
            # a real User-Agent is required: api.resend.com sits behind
            # Cloudflare, which 403-blocks the default python-urllib
            # signature with "error code: 1010"
            "user-agent": "CopCat/0.2 (+https://github.com/TalhaQureshi324/CopCat)"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        # surface the actual explanation in the dashboard
        raise RuntimeError("Resend returned {}: {}".format(
            exc.code, detail or exc.reason)) from exc


def _auth(request: Request):
    """Gate: None if allowed, else a 401 naming the auth mode. The master
    key (COPCAT_ACCESS_TOKEN) is accepted in every mode."""
    if _auth_mode() == "open":
        return None
    master = os.environ.get("COPCAT_ACCESS_TOKEN")
    if master and request.headers.get("x-copcat-key") == master:
        return None
    if _auth_mode() == "key":
        return JSONResponse(
            {"error": "unauthorized: access key required", "mode": "key"},
            status_code=401)
    if _session_ok(request.headers.get("x-copcat-session") or ""):
        return None
    return JSONResponse(
        {"error": "unauthorized: access code required", "mode": "code"},
        status_code=401)


@app.get("/api/auth/mode")
async def auth_mode():
    return {"mode": _auth_mode()}


@app.post("/api/auth/request")
async def auth_request(request: Request, note: str = Form("")):
    if _auth_mode() != "code":
        return JSONResponse(
            {"error": "code authentication is not configured on this "
                      "deployment"}, status_code=400)
    store, err = _store_or_error()
    if err:
        return err
    now = time.time()
    pending = store.get_json("challenge")
    if pending and now - pending.get("created", 0) < 60:
        # one email per minute max — no inbox flooding
        return {"sent": True, "retry_after": int(
            pending["created"] + 60 - now)}
    code = "{:06d}".format(secrets.randbelow(1000000))
    try:
        _send_access_code(os.environ["COPCAT_NOTIFY_EMAIL"], code, note)
    except Exception as exc:
        return JSONResponse(
            {"error": "could not send the access email: {}".format(exc)},
            status_code=503)
    # challenge is stored only after a successful send, so a failed email
    # never poisons the 60-second anti-flood window
    store.put_json("challenge", {
        "code_hash": _code_hash(code), "created": now,
        "expires": now + AUTH_CODE_TTL_S, "attempts": 0})
    return {"sent": True}


@app.post("/api/auth/verify")
async def auth_verify(request: Request, code: str = Form("")):
    if _auth_mode() != "code":
        return JSONResponse(
            {"error": "code authentication is not configured"}, status_code=400)
    store, err = _store_or_error()
    if err:
        return err
    ch = store.get_json("challenge")
    if not ch or time.time() > ch.get("expires", 0):
        return JSONResponse(
            {"error": "no active access code — request a new one",
             "mode": "code"}, status_code=401)
    if hmac.compare_digest(_code_hash(code), ch.get("code_hash", "")):
        ch["expires"] = 0                       # burn the code after use
        store.put_json("challenge", ch)
        return {"session": _session_token(), "mode": "code"}
    ch["attempts"] = ch.get("attempts", 0) + 1
    if ch["attempts"] >= AUTH_MAX_ATTEMPTS:
        ch["expires"] = 0                       # too many wrong tries: burn
    store.put_json("challenge", ch)
    left = max(0, AUTH_MAX_ATTEMPTS - ch["attempts"])
    return JSONResponse(
        {"error": "wrong code ({} attempts left)".format(left),
         "mode": "code"}, status_code=401)


def _store_or_error():
    """Store backend, or a 503 explaining the one misconfiguration that
    breaks hosted deployments: no Blob store connected."""
    if not os.environ.get("BLOB_READ_WRITE_TOKEN") and \
            os.environ.get("VERCEL"):
        return None, JSONResponse(
            {"error": "Server storage is not configured. Connect a Vercel "
                      "Blob store to this project (Project -> Storage -> "
                      "Connect), then redeploy so the "
                      "BLOB_READ_WRITE_TOKEN env var is applied."},
            status_code=503)
    try:
        return get_store(), None
    except Exception as exc:
        return None, JSONResponse(
            {"error": "storage init failed: {}".format(exc)},
            status_code=503)


def _meta_view(meta):
    return {"job_id": meta.get("job_id"), "status": meta.get("status"),
            "mode": meta.get("mode"), "created": meta.get("created"),
            "error": meta.get("error"), "summary": meta.get("summary"),
            "runtime_s": meta.get("runtime_s"),
            "progress": meta.get("progress"),
            "stats": meta.get("stats")}


# --------------------------------------------------------------------------
# job execution (synchronous, in a worker thread so the event loop lives)
# --------------------------------------------------------------------------
def _execute(store, meta, mode, preserve):
    job_id = meta["job_id"]
    started = time.time()
    ws = store.workspace(job_id)
    summary = {}
    stats = {"submissions": 0, "pairs": 0, "flagged": 0, "graded": 0}
    last_flush = [0.0]

    def progress(phase, done, total):
        meta["progress"] = {"phase": phase, "done": done, "total": total}
        if phase == "load":
            stats["submissions"] = total
        elif phase == "pairs":
            stats["pairs"] = total
        now = time.time()
        if now - last_flush[0] >= 2.0 or done >= total:
            last_flush[0] = now
            try:
                store.save_meta(meta)
            except Exception:
                pass                # progress persistence is best-effort

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
            pairs = run_audit(paths["submissions"], cfg, out_dir, workers=1,
                              progress=progress)
            summary["pairs"] = [
                {"a": p.roll_a, "b": p.roll_b,
                 "blended": round(100 * p.blended, 1), "flag": p.flag,
                 "evasion": round(100 * p.evasion, 1) if p.evasion else None}
                for p in pairs if p.flag != "CLEAN"]
            stats["flagged"] = len(summary["pairs"])
            stats["pairs"] = len(pairs) or stats["pairs"]
        if mode in ("grade", "both"):
            if not paths.get("rubric"):
                summary["gradebook"] = []
            else:
                from .rubric import run_grade
                rows = run_grade(paths["submissions"], paths["rubric"],
                                 os.path.join(out_dir, "grade_report.csv"),
                                 progress=progress)
                summary["gradebook"] = [
                    {"roll": r["roll"], "filename": r["filename"],
                     "final": round(r["final"], 2), "report": r["report"],
                     "task_scores": {k: round(v, 2)
                                     for k, v in r["task_scores"].items()}}
                    for r in rows]
            stats["graded"] = len(summary["gradebook"]) or stats["graded"]
        runtime = round(time.time() - started, 1)
        meta["result_urls"] = store.persist_results(job_id, out_dir)
        meta["status"], meta["summary"] = "done", summary
        meta["runtime_s"] = runtime
        meta["stats"] = stats
        meta["progress"] = None
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
    store, err = _store_or_error()
    if err:
        return err
    job_id = uuid.uuid4().hex[:12]
    try:
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
        store.save_meta({"job_id": job_id, "status": "uploaded",
                         "mode": None,
                         "created": time.strftime("%Y-%m-%d %H:%M:%S"),
                         "uploads": uploads, "preserve": "",
                         "summary": None, "runtime_s": None, "error": None,
                         "result_urls": {}})
    except Exception as exc:
        return JSONResponse(
            {"error": "upload failed — {}: {}".format(
                type(exc).__name__, exc)},
            status_code=500)
    return {"job_id": job_id}


@app.post("/api/jobs/{job_id}/run")
async def run_job(job_id: str, request: Request,
                  mode: str = Form("both"), preserve: str = Form("")):
    denied = _auth(request)
    if denied:
        return denied
    store, err = _store_or_error()
    if err:
        return err
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


@app.get("/api/stats")
async def stats(request: Request):
    """Aggregate workspace counters for the overview cards."""
    denied = _auth(request)
    if denied:
        return denied
    store, err = _store_or_error()
    if err:
        return err
    try:
        jobs = store.list_jobs()
    except Exception:
        jobs = []
    agg = {"jobs": len(jobs), "submissions": 0, "needs_review": 0,
           "graded": 0}
    for m in jobs:
        st = m.get("stats") or {}
        agg["submissions"] += st.get("submissions") or 0
        agg["needs_review"] += st.get("flagged") or 0
        agg["graded"] += st.get("graded") or 0
    return agg


@app.get("/api/jobs")
async def list_jobs(request: Request):
    denied = _auth(request)
    if denied:
        return denied
    store, err = _store_or_error()
    if err:
        return err
    try:
        rows = [_meta_view(m) for m in store.list_jobs()]
    except Exception as exc:
        return JSONResponse(
            {"error": "listing jobs failed — {}: {}".format(
                type(exc).__name__, exc)},
            status_code=500)
    rows.sort(key=lambda m: m.get("created") or "", reverse=True)
    return {"jobs": rows}


@app.get("/api/jobs/{job_id}")
async def job_status(job_id: str, request: Request):
    denied = _auth(request)
    if denied:
        return denied
    store, err = _store_or_error()
    if err:
        return err
    meta = store.get_meta(job_id)
    if not meta:
        return JSONResponse({"error": "unknown job"}, status_code=404)
    return _meta_view(meta)


@app.delete("/api/jobs/{job_id}")
async def delete_job(job_id: str, request: Request):
    denied = _auth(request)
    if denied:
        return denied
    store, err = _store_or_error()
    if err:
        return err
    if not store.get_meta(job_id):
        return JSONResponse({"error": "unknown job"}, status_code=404)
    store.delete_job(job_id)
    return {"deleted": job_id}


@app.get("/api/jobs/{job_id}/gradebook.csv")
async def gradebook(job_id: str, request: Request):
    denied = _auth(request)
    if denied:
        return denied
    store, err = _store_or_error()
    if err:
        return err
    data = store.open_result(job_id, "grade_report.csv")
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
    store, err = _store_or_error()
    if err:
        return err
    data = store.open_result(job_id, name)
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
    store, err = _store_or_error()
    if err:
        return err
    name = "dossiers/dossier_{}__vs__{}.html".format(roll_a, roll_b)
    data = store.open_result(job_id, name)
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
