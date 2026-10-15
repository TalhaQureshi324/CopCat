"""Vercel entry point.

The @vercel/python runtime imports this module and serves its ASGI ``app``
for every request (see ``rewrites`` in vercel.json).  CopCat's FastAPI app
runs unchanged; state goes to Vercel Blob because serverless functions
have no persistent disk (see copcat/store.py).
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from copcat.webapp import app  # noqa: E402
