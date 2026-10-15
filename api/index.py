"""Vercel entry point.

The @vercel/python runtime imports this module and serves its ASGI ``app``.

Routing on Vercel: vercel.json rewrites every request to
``/api/index/<original-path>`` — the function receives the *rewritten*
path, not the original one.  So the real CopCat app is mounted under
``/api/index`` and a middleware re-prefixes any request that arrives
unrewritten (covers both routing behaviours).  Locally this file is never
used: ``copcat web`` serves copcat.webapp:app at the root directly.
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from copcat.webapp import app as copcat_app  # noqa: E402
from fastapi import FastAPI  # noqa: E402

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/api/index", copcat_app)


@app.middleware("http")
async def _refix_original_paths(request, call_next):
    path = request.scope.get("path", "/")
    if not path.startswith("/api/index"):
        request.scope["path"] = "/api/index" + (
            path if path.startswith("/") else "/" + path)
    return await call_next(request)
