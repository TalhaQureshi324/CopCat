"""Universal ingestion: folders, raw LMS ZIP archives (Canvas / Google
Classroom / Moodle), and Jupyter/Colab notebooks.

* ZIP extraction is zip-slip hardened: members with absolute paths or `..`
  traversals are normalized/skipped.
* Identity resolution order per file: explicit roll pattern (bscs12345...)
  -> LMS submission folder/prefix (`<Name>_<id>_assignsubmission_file_`)
  -> nearest parent folder name -> filename stem.
* `.ipynb` files are converted to a plain Python stream (code cells only,
  magics/shell lines stripped); the raw notebook JSON is kept as a
  metadata blob so forensics can still see Colab IDs hidden in notebook
  metadata.
"""

import json
import os
import re
import tempfile
import zipfile

from .forensics import scan_source
from .ingest import extract_roll

_PY_RE = re.compile(r"\.py$", re.IGNORECASE)
IPYNB_RE = re.compile(r"\.ipynb$", re.IGNORECASE)
LMS_SUBMISSION_RE = re.compile(
    r"^(?P<name>.+?)_(?P<id>\d+)_(?:assignsubmission|attempt).*$", re.IGNORECASE)
NAME_ID_RE = re.compile(
    r"^(?P<name>[A-Za-z][A-Za-z .]{1,40})[-_ ]+(?P<id>\d{3,8})[-_ ]?")
MAGIC_RE = re.compile(r"^\s*(?:%|!|get_ipython\(\))")


def _safe_member_name(name):
    """Normalize a zip member path; None if it tries to escape (zip-slip)."""
    name = name.replace("\\", "/")
    if name.startswith("/") or ".." in name.split("/"):
        return None
    drive = os.path.splitdrive(name)[0]
    if drive:
        return None
    return name.lstrip("./")


def notebook_to_python(path):
    """Convert a .ipynb to (python_source, metadata_blob).

    Code cells are concatenated; magics, shell escapes and get_ipython()
    lines are stripped. The full raw JSON text is returned separately so
    forensics can extract Colab IDs from notebook metadata.
    """
    with open(path, encoding="utf-8-sig", errors="replace") as fh:
        raw = fh.read()
    try:
        nb = json.loads(raw)
    except json.JSONDecodeError:
        return "", raw
    cells = []
    for cell in nb.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        src = cell.get("source", "")
        if isinstance(src, list):
            src = "".join(src)
        lines = [ln for ln in src.splitlines() if not MAGIC_RE.match(ln)]
        cells.append("\n".join(lines))
    return "\n\n".join(cells), raw


def resolve_identity(rel_path, explicit_roll):
    """Best-effort student identifier for a submission file.

    Returns (identifier, identifier_kind).
    """
    if explicit_roll:
        return explicit_roll, "roll-pattern"
    parts = [p for p in rel_path.replace("\\", "/").split("/") if p]
    # nearest folders first, then the filename
    for candidate in reversed(parts):
        m = LMS_SUBMISSION_RE.match(candidate)
        if m:
            name = " ".join(m.group("name").split("_")).strip()
            return "{}{}".format(name.replace(" ", ""), m.group("id")), "lms-folder"
        stem = os.path.splitext(candidate)[0]
        m = NAME_ID_RE.match(stem)
        if m:
            return "{}{}".format(m.group("name").replace(" ", ""), m.group("id")), "name-id"
    folder = parts[-2] if len(parts) > 1 else ""
    if folder:
        return folder, "folder-name"
    return os.path.splitext(parts[-1])[0] if parts else "unknown", "filename"


def collect(path):
    """Universal collector: returns [(workdir, identifier, kind, filename,
    source, metadata_blob)] from a directory OR a .zip archive."""
    if os.path.isdir(path):
        return _collect_dir(path)
    if path.lower().endswith(".zip"):
        return _collect_zip(path)
    raise ValueError("unsupported submission source: {}".format(path))


def _collect_dir(root):
    out = []
    for dirpath, _dirs, files in os.walk(root):
        for name in sorted(files):
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root)
            if _PY_RE.search(name):
                with open(full, encoding="utf-8-sig", errors="replace") as fh:
                    src = fh.read()
                roll = extract_roll(name)
                ident, kind = resolve_identity(rel, roll)
                out.append((root, ident, kind, name, src, ""))
            elif IPYNB_RE.search(name):
                src, blob = notebook_to_python(full)
                if not src.strip():
                    continue
                roll = extract_roll(name)
                ident, kind = resolve_identity(rel, roll)
                out.append((root, ident, kind, name + " [notebook]", src, blob))
    return out


def _collect_zip(zip_path):
    out = []
    with zipfile.ZipFile(zip_path) as zf:
        extract_root = tempfile_dir()
        for member in zf.infolist():
            if member.is_dir():
                continue
            safe = _safe_member_name(member.filename)
            if not safe:
                continue
            target = os.path.join(extract_root, safe)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zf.open(member) as src_fh, open(target, "wb") as out_fh:
                out_fh.write(src_fh.read())
        # second pass over extracted tree (handles nested LMS zips too)
        for dirpath, _dirs, files in os.walk(extract_root):
            for name in sorted(files):
                full = os.path.join(dirpath, name)
                rel = os.path.relpath(full, extract_root)
                if name.lower().endswith(".zip"):
                    try:
                        out.extend(_collect_zip(full))
                    except zipfile.BadZipFile:
                        continue
                elif _PY_RE.search(name):
                    with open(full, encoding="utf-8-sig", errors="replace") as fh:
                        src = fh.read()
                    roll = extract_roll(name)
                    ident, kind = resolve_identity(rel, roll)
                    out.append((extract_root, ident, kind, name, src, ""))
                elif IPYNB_RE.search(name):
                    src, blob = notebook_to_python(full)
                    if src.strip():
                        roll = extract_roll(name)
                        ident, kind = resolve_identity(rel, roll)
                        out.append((extract_root, ident, kind,
                                    name + " [notebook]", src, blob))
    return out


def tempfile_dir():
    d = os.path.join(tempfile.gettempdir(), "copcat_ingest")
    os.makedirs(d, exist_ok=True)
    stamp = str(len(os.listdir(d)) + 1)
    d = os.path.join(d, stamp)
    os.makedirs(d, exist_ok=True)
    return d
