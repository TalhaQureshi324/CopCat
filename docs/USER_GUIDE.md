# CopCat — User Guide & Cheatsheet

Deterministic plagiarism audit + rubric grading for programming labs.
No AI tokens, everything runs locally.

---

## 1. Installation & Environment Setup

### Get the code

```bash
git clone https://github.com/TalhaQureshi324/CopCat.git
cd CopCat
```

### Create a virtual environment

**Windows (PowerShell):**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

**Linux / macOS:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### Install (editable, with all extras)

```bash
pip install -e ".[dev,web]"
```

This installs the `copcat` CLI, PyYAML (rubrics), FastAPI + uvicorn (web GUI)
and pytest + httpx (tests). Engine only, no GUI: `pip install -e .`

### Verify the installation

```bash
copcat --help                 # shows subcommands: audit / grade / web
python -c "import copcat; print(copcat.__version__)"
python -m pytest tests/ -q    # optional: full regression suite (35 tests)
```

Requires Python >= 3.9 (developed and CI-tested on 3.12/3.13, Windows + Ubuntu).

---

## 2. Web GUI (FastAPI Dashboard)

### Start the dashboard

```bash
copcat web                    # http://127.0.0.1:8000
copcat web --port 8001        # custom port
copcat web --host 0.0.0.0     # expose to the LAN (careful: no auth)
```

Equivalent without the entrypoint: `python -m copcat web` or
`uvicorn copcat.webapp:app --port 8000`. Health check: `GET /healthz`.

### Browser flow

1. **Upload** — open `http://127.0.0.1:8000/`, drag the submissions file into
   the drop zone. Accepted: a raw LMS `.zip` (Canvas / Google Classroom /
   Moodle exports, nested zips, `.py` and `.ipynb` files) or loose `.py`
   files. Student identities are auto-extracted from roll patterns
   (`bscs25134...`) or LMS folder names (`Alice Khan_221099_assignsubmission_file_`).
2. **Attach a rubric** (optional) — pick a `rubric.yaml`
   (see `examples/rubric_lab02.yaml`). Required only for grading.
3. **Run** — choose *Run audit*, *Run grading*, or *Run both*. Optional:
   paste preserved interface names (`Book,Library,calculate_pay,...`) so
   structural class binding knows the mandated names.
4. **Results** — the dashboard shows:
   - **Flagged pairs** table (per-channel %, flag) with *open dossier* links
   - **Cluster chips** (who clusters with whom)
   - **Gradebook** table with per-task scores and inline deduction notes
   - Downloads: **gradebook CSV**, full **index.html** report (includes the
     D3 cluster graph), **copcat_audit.txt**

---

## 3. Command Line (CLI)

### Plagiarism audit (folder or ZIP)

```bash
copcat audit ./submissions/
copcat audit canvas_export.zip --starter examples/starter_lab02.py
```

### Grading (directory; extract ZIPs first)

```bash
copcat grade ./submissions/ --rubric examples/rubric_lab02.yaml --out grade_report.csv
```

> `audit` accepts a `.zip` directly; `grade` currently reads a folder.
> For an LMS zip: run `copcat audit export.zip ...` once (it does not modify
> the zip) or unzip, then point `grade` at the extracted folder.

### Both, with custom outputs

```bash
copcat audit ./submissions/ --out output/audit
copcat grade ./submissions/ --rubric my_rubric.yaml --out output/grade_report.csv
```

### Useful flags

| Flag | Where | Default | Meaning |
|---|---|---|---|
| `--starter PATH` | audit | none | starter/base code subtracted before scoring (repeatable) |
| `--preserve a,b,c` | audit | builtins+dunders | interface names never canonicalized |
| `--sus 0.60` / `--high 0.80` | audit | 0.60 / 0.80 | flag thresholds |
| `--k 16` / `--window 8` | audit | 16 / 8 | fingerprint granularity |
| `--min-lines 15` | audit | 15 | skip pairs with tiny files |
| `--workers 0` | audit | auto | parallel pair comparison (1 = single process) |
| `--out DIR` | audit | `reports` | output directory |
| `--timeout 10` | grade | 10 s | sandbox budget per submission |
| `--memory 512` | grade | 512 MB | sandbox memory cap |

Examples:

```bash
# strict audit of a big batch, skipping starter code, fast
copcat audit ./batch/ --starter ./starter/ --workers 8 --sus 0.55 --out rep1/

# gentle grading sandbox for slow interactive submissions
copcat grade ./submissions/ --rubric r.yaml --timeout 30 --memory 1024
```

---

## 4. Expected Outputs & Locations

After `copcat audit ./subs/ --out reports/`:

```
reports/
├── copcat_audit.csv     # every pair: per-channel % + flag
├── copcat_audit.txt     # ranked audit: evidence, clusters, forensics, notes
├── index.html           # dashboard: D3 cluster graph + flagged pairs table
├── diffs/               # side-by-side diff page per flagged pair
└── dossiers/            # printable misconduct evidence packet per pair
    └── dossier_<A>__vs__<B>.html
```

After `copcat grade ... --out grade_report.csv`:

```
grade_report.csv        # Roll_Number, Filename, Task_1..N, Penalties,
                        # Final_Score, Deduction_Report
```

In the web GUI everything lands under the job's `output/` folder (temp dir)
and is served through the dashboard buttons/links — use *Export gradebook
CSV* and the dossier links; nothing is sent off-machine.

### Dossier -> PDF for a hearing

1. Open `reports/dossiers/dossier_<A>__vs__<B>.html` in any browser.
2. `Ctrl+P` (Cmd+P on macOS) -> destination *Save as PDF*.
3. Print CSS is built in: A4 page breaks, no cut-off tables, header/footer
   optional. The dossier contains the executive summary, channel table,
   renamed-identifier table, shared literals, side-by-side diff and a
   methodology appendix.

---

## 5. Troubleshooting & Common Scenarios

**Port 8000 already in use**
```bash
copcat web --port 8001
# or find the blocker:
#   Windows:  netstat -ano | findstr :8000   then  taskkill /PID <pid> /F
#   Linux:    ss -ltnp | grep 8000           then  kill <pid>
```

**Malformed / broken submissions** — a syntax error in one task does not
zero the rest (chunk parser); a top-level crash mid-file keeps earlier
classes gradeable (partial-namespace salvage); interactive `input()` menus
are neutralized (EOFError) and infinite loops hit the sandbox timeout. A
submission that is mostly commented-out code is scored on the folded
comment stream for *similarity*, but earns no *grading* marks from comments.

**Empty or tiny files** — files under `--min-lines` (15) non-blank lines are
excluded from pair scoring; empty `.py` files are ignored; notebooks whose
code cells are all empty are skipped.

**"pip install copcat[web]" extras missing** — the web GUI needs
`pip install -e ".[web]"`; the CLI audit/grade only needs `pyyaml`.

**Port / venv gotchas (Windows)** — use `.\.venv\Scripts\Activate.ps1`
(set-execution policy if needed: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`).

**Verify before a live batch**
```bash
python -m pytest tests/ -q     # expect: 35 passed
```
CI runs the same suite on Ubuntu + Windows at every push.

**Thresholds** — defaults are calibrated on a 47-file hand-audited batch
(SUS > 60%, HIGH > 80%, evasion shadow >= 12% with >= 400 folded tokens).
For a small section, re-tune with `--sus/--high` against known pairs before
acting on flags.

**Privacy** — never commit real student submissions or generated reports to
the repo (`reports*/` is git-ignored on purpose).

---

## Cheatsheet (TL;DR)

```bash
# setup
git clone https://github.com/TalhaQureshi324/CopCat.git && cd CopCat
python -m venv .venv && .venv\Scripts\Activate.ps1   # or source .venv/bin/activate
pip install -e ".[dev,web]"
copcat --help

# web dashboard
copcat web                       # -> http://127.0.0.1:8000

# audit (folder or LMS zip)
copcat audit ./submissions/ --starter starter.py --out reports/

# grade
copcat grade ./submissions/ --rubric examples/rubric_lab02.yaml --out grade.csv

# regression check
python -m pytest tests/ -q       # 35 passed
```
