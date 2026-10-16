"""Multi-language ingestion: the audit pipeline accepts C/C++ submissions
alongside Python; grading discovery stays Python-only."""

import os
import zipfile

from copcat.langs import lang_of, is_source
from copcat.ingest import discover
from copcat.loader import collect

CPP_SRC = ("#include <iostream>\n"
           "int main() {\n"
           "    std::cout << \"hello\";\n"
           "    return 0;\n"
           "}\n")


def _build(tmp_path):
    (tmp_path / "ali_bscs25101_lab.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "sara_bscs25102_task1.cpp").write_text(CPP_SRC, encoding="utf-8")
    (tmp_path / "omar_bscs25103_task2.CPP").write_text(CPP_SRC, encoding="utf-8")
    (tmp_path / "notes.txt").write_text("not source", encoding="utf-8")
    return tmp_path


def test_lang_detection():
    assert lang_of("a.cpp") == "cpp"
    assert lang_of("a.CPP") == "cpp"
    assert lang_of("b.cc") == "cpp"
    assert lang_of("c.hxx") == "cpp"
    assert lang_of("c.h") == "cpp"
    assert lang_of("d.py") == "python"
    assert is_source("x.cpp") and is_source("x.py")
    assert not is_source("x.txt")


def test_collect_dir_mixed_languages(tmp_path):
    rows = collect(str(_build(tmp_path)))
    names = sorted(os.path.basename(r[3]) for r in rows)
    assert names == ["ali_bscs25101_lab.py", "omar_bscs25103_task2.CPP",
                     "sara_bscs25102_task1.cpp"]
    for _wd, _ident, _kind, fname, src, _blob in rows:
        assert lang_of(fname) == ("cpp" if fname.lower().endswith(".cpp")
                                  else "python")
        assert src.strip()


def test_collect_zip_mixed_languages(tmp_path):
    zpath = tmp_path / "mix.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("ali_bscs25101_lab.py", "y = 2\n")
        zf.writestr("sara_bscs25102_task1.cpp", CPP_SRC)
    rows = collect(str(zpath))
    exts = sorted(os.path.basename(r[3]).lower().endswith((".py", ".cpp"))
                  for r in rows)
    assert exts == [True, True]
    cpp_rows = [r for r in rows if r[3].lower().endswith(".cpp")]
    assert len(cpp_rows) == 1 and "iostream" in cpp_rows[0][4]


def test_grading_discovery_stays_python_only(tmp_path):
    _build(tmp_path)
    py = discover(str(tmp_path))
    assert len(py) == 1 and py[0].endswith(".py")
