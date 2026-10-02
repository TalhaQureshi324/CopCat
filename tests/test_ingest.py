"""Ingestion tests: LMS zips, identity extraction, notebook conversion."""

import json
import os
import zipfile

from copcat.loader import collect, notebook_to_python, resolve_identity
from copcat.forensics import scan_source


def _make_lms_zip(tmp_path, layout):
    """layout: {member_name: bytes}"""
    zip_path = tmp_path / "submissions.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for name, content in layout.items():
            zf.writestr(name, content)
    return str(zip_path)


NOTEBOOK = {
    "cells": [
        {"cell_type": "markdown",
         "source": ["# My solution"]},
        {"cell_type": "code",
         "source": ["class MyLib:\n", "    def __init__(self):\n",
                    "        self.books = []\n"]},
        {"cell_type": "code",
         "source": "get_ipython().run_line_magic('matplotlib', 'inline')\nprint('done')"},
    ],
    "metadata": {"colab": {"provenance": [],
                           "notebookId": "1AbCdEfGhIjKlMnOpQrStUvWx"}},
}


def test_zip_with_canvas_folders(tmp_path):
    zip_path = _make_lms_zip(tmp_path, {
        "Alice Khan_221099_assignsubmission_file_/sol.py":
            b"class Book:\n    pass\n",
        "Bob Ray_221044_assignsubmission_file_/sol.py":
            b"class Book:\n    def __str__(self): return 'b'\n",
    })
    entries = collect(zip_path)
    assert len(entries) == 2
    ids = sorted(e[1] for e in entries)
    assert ids == ["AliceKhan221099", "BobRay221044"]
    assert all(e[2] == "lms-folder" for e in entries)


def test_zip_with_rollnumber_files(tmp_path):
    zip_path = _make_lms_zip(tmp_path, {
        "bscs25001_lab.py": b"x = 1\n",
        "bscs25002_lab.py": b"y = 2\n",
    })
    entries = collect(zip_path)
    assert sorted(e[1] for e in entries) == ["BSCS25001", "BSCS25002"]
    assert all(e[2] == "roll-pattern" for e in entries)


def test_notebook_conversion_and_metadata_forensics(tmp_path):
    zip_path = _make_lms_zip(tmp_path, {
        "Carol_Danvers_9911_assignsubmission_file_/work.ipynb":
            json.dumps(NOTEBOOK).encode(),
    })
    entries = collect(zip_path)
    assert len(entries) == 1
    _root, ident, kind, fname, src, blob = entries[0]
    assert ident == "CarolDanvers9911"
    assert "[notebook]" in fname
    # code cells joined, magic stripped
    assert "class MyLib:" in src and "print('done')" in src
    assert "get_ipython" not in src and "My solution" not in src
    # metadata blob keeps the Colab notebook id visible to forensics
    info = scan_source(src + "\n" + blob)
    assert info["colab_ids"] == ["1AbCdEfGhIjKlMnOpQrStUvWx"]


def test_nested_zip(tmp_path):
    inner = tmp_path / "inner.zip"
    with zipfile.ZipFile(inner, "w") as zf:
        zf.writestr("deep.py", b"z = 9\n")
    outer = _make_lms_zip(tmp_path, {"batch.zip": open(inner, "rb").read()})
    entries = collect(outer)
    assert len(entries) == 1 and entries[0][4].strip() == "z = 9"


def test_zip_slip_members_are_dropped(tmp_path):
    zip_path = _make_lms_zip(tmp_path, {
        "../escaped.py": b"evil = True\n",
        "safe.py": b"safe = True\n",
    })
    entries = collect(zip_path)
    assert len(entries) == 1
    assert entries[0][4].strip() == "safe = True"
    assert not os.path.exists(os.path.join(tmp_path, "escaped.py"))


def test_identity_fallbacks():
    assert resolve_identity("sol.py", "BSCS25001") == ("BSCS25001", "roll-pattern")
    assert resolve_identity("Ali Khan_12345_assignsubmission_file_/a.py",
                            "")[0] == "AliKhan12345"
    assert resolve_identity("Ali Khan_12345.py", "")[0] == "AliKhan12345"
    assert resolve_identity("submissions/alice/a.py", "")[1] == "folder-name"
