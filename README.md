# CopCat

Deterministic lab grading + multi-channel plagiarism detection for programming
courses. **Zero AI tokens at grading time.**

```bash
# 1. Plagiarism audit over a folder of submissions (zero configuration)
python -m copcat audit ./submissions/ --starter ./manual_starter.py

# 2. Grade against a YAML rubric (sandboxed, zero AI tokens)
python -m copcat grade ./submissions/ --rubric examples/rubric_lab02.yaml --out grade_report.csv
```

## Why not MOSS

| Gap in MOSS | CopCat |
|---|---|
| Ignores comments — students comment code out to evade it | **Shadow channel**: comment blocks are parsed; code-like ones are folded back into a fingerprint stream. A fully-commented copy *matches* the live original instead of hiding. Evasion candidates (files that are mostly commented-out code) are surfaced automatically |
| Variable renaming hides copying | **AST-canonical channel**: scope-aware renaming to canonical names with a *preserved symbol table* (builtins + dunders + rubric interface names). Renamed copies collapse to near-identical fingerprints |
| One opaque percentage | **6 channels** (source, token, AST, comment-prose, string-literals, shadow) reported per pair — copied comments, copied demo data, and copied logic are visible separately |
| Misses "one solution circulating through the batch" | **Batch damper** (fingerprints present in ≥30% of files removed), **starter-code subtraction** (`--starter`, MOSS `-b` equivalent), and **clustering** (connected components of flagged pairs → the source-to-copies tree) |
| No submission forensics | Evasion indicators, mostly-commented-file detection, chunk-parse diagnostics (a syntax error in Task 6 no longer zeroes Tasks 1–5) |

## Validation

Built and calibrated against a real ground truth: 47 Python submissions for an
OOP lab that had been fully hand-graded and hand-audited. The engine reproduces
**8/8** known plagiarism flags — 7 circulated-solution pairs (scores within
0.1–0.4 points of the manual audit) plus the fully-commented-file evasion pair,
caught by the shadow channel — while every known-clean pair stays clean
(next-highest band: 49–56% vs flag threshold 60%). Full batch of 47 files,
1081 pairs: ~2 minutes on a laptop, single process.

## Channels

| Channel | Method | Catches |
|---|---|---|
| source | char-ratio (difflib, default settings) of comment-stripped stream and raw file; max of the two | direct copy/paste, reformatted copies |
| token | k-gram (k=16) + winnowing fingerprints over code tokens, batch-damped | restructured copies |
| ast | fingerprints over scope-aware canonically-renamed AST | renamed-variable copies |
| comment | word-5-gram shingles over comments + docstrings | copied explanations/comments |
| string | word shingles over all string literals (incl. inside folded comments) | shared demo data, shared error messages |
| shadow | folded commented-out code vs the other file's live code | commented-out-file evasion |

Blended score = max(source, token, ast, shadow). Defaults: `>60%` SUSPICIOUS,
`>80%` HIGH_PROBABILITY_PLAGIARISM, tunable via `--sus/--high`.
**Evasion rule**: a mostly-commented file whose folded shadow (≥400 tokens)
aligns ≥15% with another student's live code flags automatically (unrelated
pairs sit at ~1–8%); ≥25% escalates to HIGH.

## Outputs

- `copcat_audit.csv` — one row per pair, per-channel percentages + flag
- `copcat_audit.txt` — ranked pairs with matched code blocks, evasion
  indicators, clusters, method notes and caveats

## Documentation

Full install/run guide and cheatsheet: [docs/USER_GUIDE.md](docs/USER_GUIDE.md)

## Web dashboard

```bash
pip install "copcat[web]"
copcat web                # http://localhost:8000
```

Drag-and-drop a submissions ZIP (+ optional rubric/starter), run the audit
and/or grading, browse flagged pairs with evidence dossiers, export the
gradebook CSV. Job history persists across page refreshes and server
restarts (registry of JSON files, not RAM).

Optional environment variables:

| Variable | Effect |
|---|---|
| `COPCAT_RESULTS_DIR` | where jobs/artifacts live (default `./copcat_results`) |
| `COPCAT_ACCESS_TOKEN` | if set, the API requires this key (`x-copcat-key` header; the dashboard prompts for it) |
| `BLOB_READ_WRITE_TOKEN` | switches storage from local disk to Vercel Blob (set automatically by Vercel — this is what makes the hosted deployment work) |

## Deploy to Vercel (free)

CopCat runs on Vercel's free Hobby plan. Jobs execute **synchronously**
inside the request (serverless kills background threads), and uploads +
results persist in **Vercel Blob** — so history survives refreshes and
redeploys. One request handles the whole run.

1. Push this repo to GitHub (already done) and open
   [vercel.com/new](https://vercel.com/new) → import the repo. Vercel
   auto-detects `api/index.py` + `vercel.json`; no build settings needed.
2. In the project: **Storage → Create Database → Blob** (free tier) →
   connect it to the project. This sets `BLOB_READ_WRITE_TOKEN` for you.
3. Optional: add env var `COPCAT_ACCESS_TOKEN` (any secret string) so only
   people with the key can use your deployment — recommended, the URL is
   public otherwise.
4. Deploy. Dashboard refresh shows **Job history** — every past upload and
   its results stay re-openable.

Free-tier limits to know:

- request body ≤ **4.5 MB** → keep the submissions ZIP small (plain `.py`
  files zip tiny); upload loose-file batches in one zip
- one run must finish within **5 minutes** (Fluid compute `maxDuration`
  300 s) → for classes of ~50+, run **Audit** and **Grading** as two
  separate runs instead of "Run both"
- Hobby plan terms are **non-commercial** — fine for coursework; a paid
  plan is required when this becomes a product


## Layout

```
copcat/
  cli.py audit.py models.py ingest.py
  lexing.py      # tokens / comments / docstrings / strings (never raises)
  normal.py      # k-grams, winnowing, shingles, containment/jaccard
  canon.py       # fault-tolerant chunk parser + scope-aware canonical renamer
  shadow.py      # commented-out-code folding
  channels.py    # channel building, starter subtraction, batch damper
  compare.py cluster.py report.py
```

## Roadmap

- **M2**: forensics (Colab notebook-ID matching), multiprocessing for large batches
- **M3 (done)**: Diff Explainer + D3 cluster graph — see `copcat/webreport.py`; audit now also writes `index.html` + per-pair diff pages
- **M4**: rubric engine — YAML rubric → ~25 check types (static AST / sandboxed
  dynamic with Job-Object isolation + mocked stdin / functional property tests),
  auto-generated evidence-based deduction reports
- **M5**: AI rubric-compiler (one LLM call per lab, zero per student), tree-sitter multi-language

## Caveats

Raw whole-file similarity cannot by itself distinguish collusion from a
circulating shared base — always read flags with the per-channel breakdown,
evasion indicators, and clusters. Recalibrate thresholds (`--sus/--high`)
against your own ground truth before disciplinary action.
