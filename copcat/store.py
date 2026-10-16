"""Pluggable persistence for the web dashboard.

Vercel functions have no persistent disk and no shared memory between
requests, so the dashboard cannot keep job state in RAM or write to the
working directory there.  Two backends, selected automatically:

* ``DiskStore``  - local runs (``copcat web``).  Everything lives under
  ``$COPCAT_RESULTS_DIR`` (default ``./copcat_results``).  The job
  registry is a folder of small JSON files, so history survives server
  restarts and dashboard refreshes.
* ``BlobStore``  - serverless hosting (Vercel).  Uploads, generated
  artifacts and the registry live in **Vercel Blob**, accessed through
  its REST API with the stdlib only (urllib - no SDK dependency).
  Selected automatically when ``BLOB_READ_WRITE_TOKEN`` is set.

Storage layout (identical prefixes on both backends)::

    meta/<job_id>.json        registry entry: status + summary + upload map
    <job_id>/uploads/...      uploaded submissions.zip / rubric.yaml / starter.py
    <job_id>/output/...       generated artifacts (audit, dossiers, gradebook)

Blob URLs are never exposed to the browser; every download is streamed
through the API.
"""

import json
import os
import shutil
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request

_META_DIR = "meta"
_MAX_FILE_BYTES = 8 * 1024 * 1024      # skip absurd artifacts, not real ones
_MAX_RESULT_FILES = 300

_CT = {".html": "text/html", ".csv": "text/csv", ".txt": "text/plain",
       ".json": "application/json", ".py": "text/x-python",
       ".yaml": "text/yaml", ".yml": "text/yaml", ".zip": "application/zip"}


def _content_type(name):
    return _CT.get(os.path.splitext(name)[1].lower(), "application/octet-stream")


class DiskStore:
    """Local filesystem backend (default for ``copcat web``)."""

    def __init__(self, root=None):
        self.root = root or os.environ.get("COPCAT_RESULTS_DIR") or \
            os.path.join(os.getcwd(), "copcat_results")
        # directories are created lazily by write operations, so read-only
        # filesystems can still serve reads (empty history)

    # -- uploads ----------------------------------------------------------
    def save_upload(self, job_id, kind, name, data):
        up = os.path.join(self.root, job_id, "uploads")
        os.makedirs(up, exist_ok=True)
        path = os.path.join(up, kind + os.path.splitext(name)[1].lower())
        with open(path, "wb") as fh:
            fh.write(data)
        return {"name": name, "path": path}

    def materialize(self, job_id, ws, uploads_meta):
        """Return {kind: local_path}; disk uploads are already local."""
        paths = {}
        for kind, info in (uploads_meta or {}).items():
            if info.get("path") and os.path.isfile(info["path"]):
                paths[kind] = info["path"]
        return paths

    # -- job registry -----------------------------------------------------
    def _meta_path(self, job_id):
        return os.path.join(self.root, _META_DIR, job_id + ".json")

    def save_meta(self, meta):
        os.makedirs(os.path.join(self.root, _META_DIR), exist_ok=True)
        path = self._meta_path(meta["job_id"])
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(meta, fh)
        os.replace(tmp, path)     # atomic: progress polls never read half a file

    def get_meta(self, job_id):
        path = self._meta_path(job_id)
        if not os.path.isfile(path):
            return None
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def list_jobs(self):
        meta_dir = os.path.join(self.root, _META_DIR)
        out = []
        try:
            names = os.listdir(meta_dir)
        except OSError:
            return out
        for name in names:
            if not name.endswith(".json"):
                continue
            try:
                with open(os.path.join(meta_dir, name),
                          encoding="utf-8") as fh:
                    out.append(json.load(fh))
            except (OSError, ValueError):
                continue
        return out

    # -- results ----------------------------------------------------------
    def workspace(self, job_id):
        ws = os.path.join(self.root, job_id)
        os.makedirs(ws, exist_ok=True)
        return ws

    def persist_results(self, job_id, out_dir):
        """No-op: the engine already wrote into the permanent job dir."""
        return {}

    def open_result(self, job_id, name):
        base = os.path.join(self.root, job_id, "output")
        target = os.path.normpath(os.path.join(base, name))
        if not target.startswith(base) or not os.path.isfile(target):
            return None
        with open(target, "rb") as fh:
            return fh.read()

    def cleanup(self, ws):
        pass                      # the workspace IS the permanent store

    def delete_job(self, job_id):
        shutil.rmtree(os.path.join(self.root, job_id), ignore_errors=True)
        try:
            os.remove(self._meta_path(job_id))
        except OSError:
            pass

    # -- small JSON documents (used for auth challenges) -------------------
    def put_json(self, name, obj):
        d = os.path.join(self.root, "_auth")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, name + ".json"), "w", encoding="utf-8") as fh:
            json.dump(obj, fh)

    def get_json(self, name):
        path = os.path.join(self.root, "_auth", name + ".json")
        if not os.path.isfile(path):
            return None
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return None


class BlobStore:
    """Vercel Blob backend for serverless hosting (stdlib REST client)."""

    BASE = "https://blob.vercel-storage.com"

    def __init__(self, token):
        self.token = token

    # -- REST plumbing ------------------------------------------------------
    def _req(self, method, url, data=None, headers=None):
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("authorization", "Bearer " + self.token)
        for key, val in (headers or {}).items():
            req.add_header(key, val)
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read()[:300].decode("utf-8", "replace")
            except Exception:
                pass
            raise RuntimeError("Vercel Blob {} {} failed: {} {}".format(
                method, urllib.parse.urlsplit(url).path, exc.code,
                detail)) from exc

    @staticmethod
    def _q(pathname):
        return "/".join(urllib.parse.quote(part, safe="")
                        for part in pathname.split("/"))

    def _put(self, pathname, data, content_type):
        url = self.BASE + "/" + self._q(pathname)
        # stores are created as public or private; declare the matching
        # access and self-heal by retrying the other mode on a 400 mismatch
        last_exc = None
        for access in ("private", "public"):
            try:
                body = self._req("PUT", url, data=data, headers={
                    "x-add-random-suffix": "0",
                    "x-allow-overwrite": "1",
                    "x-vercel-blob-access": access,
                    "x-content-type": content_type})
                return json.loads(body)["url"]
            except RuntimeError as exc:
                last_exc = exc
                if "access" not in str(exc):
                    raise
        raise last_exc

    def _get(self, url):
        return self._req("GET", url)

    def _list(self, prefix, limit=1000):
        blobs, cursor = [], None
        while True:
            qs = {"mode": "expanded", "prefix": prefix, "limit": str(limit)}
            if cursor:
                qs["cursor"] = cursor
            body = self._req("GET", self.BASE + "?" +
                             urllib.parse.urlencode(qs))
            page = json.loads(body)
            blobs.extend(page.get("blobs", []))
            cursor = page.get("cursor")
            if not page.get("hasMore") or not cursor:
                return blobs

    def _delete(self, urls):
        if not urls:
            return
        payload = json.dumps({"urls": urls}).encode("utf-8")
        headers = {"content-type": "application/json"}
        try:
            self._req("DELETE", self.BASE + "/delete", data=payload,
                      headers=headers)
        except RuntimeError:
            self._req("POST", self.BASE + "/delete", data=payload,
                      headers=headers)

    # -- uploads ----------------------------------------------------------
    def save_upload(self, job_id, kind, name, data):
        url = self._put("{}/uploads/{}".format(job_id, kind), data,
                        _content_type(name))
        return {"name": name, "url": url}

    def materialize(self, job_id, ws, uploads_meta):
        up = os.path.join(ws, "uploads")
        os.makedirs(up, exist_ok=True)
        paths = {}
        for kind, info in (uploads_meta or {}).items():
            dest = os.path.join(up, kind + os.path.splitext(
                info.get("name") or kind)[1].lower())
            if not (info.get("path") and os.path.isfile(info["path"])):
                with open(dest, "wb") as fh:
                    fh.write(self._get(info["url"]))
            paths[kind] = dest
        return paths

    # -- job registry -------------------------------------------------------
    def _meta_url(self, job_id):
        blobs = self._list(_META_DIR + "/" + job_id + ".json", limit=1)
        return blobs[0]["url"] if blobs else None

    def save_meta(self, meta):
        data = json.dumps(meta).encode("utf-8")
        self._put("{}/{}.json".format(_META_DIR, meta["job_id"]), data,
                  "application/json")

    def get_meta(self, job_id):
        url = self._meta_url(job_id)
        if not url:
            return None
        return json.loads(self._get(url))

    def list_jobs(self):
        out = []
        for blob in self._list(_META_DIR + "/"):
            try:
                out.append(json.loads(self._get(blob["url"])))
            except (RuntimeError, ValueError):
                continue
        return out

    # -- results ------------------------------------------------------------
    def workspace(self, job_id):
        return tempfile.mkdtemp(prefix="copcat-")

    def persist_results(self, job_id, out_dir):
        urls, count = {}, 0
        for dirpath, _dirs, files in os.walk(out_dir):
            for fname in files:
                if count >= _MAX_RESULT_FILES:
                    break
                path = os.path.join(dirpath, fname)
                rel = os.path.relpath(path, out_dir).replace("\\", "/")
                if os.path.getsize(path) > _MAX_FILE_BYTES:
                    continue
                with open(path, "rb") as fh:
                    data = fh.read()
                urls[rel] = self._put("{}/output/{}".format(job_id, rel),
                                      data, _content_type(rel))
                count += 1
        return urls

    def open_result(self, job_id, name):
        meta = self.get_meta(job_id)
        url = (meta.get("result_urls") or {}).get(name) if meta else None
        if not url:
            return None
        return self._get(url)

    def cleanup(self, ws):
        shutil.rmtree(ws, ignore_errors=True)

    def delete_job(self, job_id):
        urls = [b["url"] for b in self._list(job_id + "/")]
        meta = self._meta_url(job_id)
        if meta:
            urls.append(meta)
        self._delete(urls)

    def put_json(self, name, obj):
        data = json.dumps(obj).encode("utf-8")
        self._put("_auth/" + name, data, "application/json")

    def get_json(self, name):
        blobs = self._list("_auth/" + name, limit=1)
        if not blobs:
            return None
        try:
            return json.loads(self._get(blobs[0]["url"]))
        except (RuntimeError, ValueError):
            return None


def get_store():
    """Backend selection: Blob when a Blob token exists, disk otherwise."""
    token = os.environ.get("BLOB_READ_WRITE_TOKEN")
    if token:
        return BlobStore(token)
    return DiskStore()
