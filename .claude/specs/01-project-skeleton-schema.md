# Spec: Project Skeleton Config And Database Schema

## Overview

This step lays the foundation every later step reads from: the folder
layout described in CLAUDE.md, a single `config.py` holding
`REFERENCE_DATE` together with every threshold and point cap, and
`db.py` holding the complete SQLite schema plus connection and query
helpers. Nothing is detected and nothing is served over HTTP yet — the
deliverable is an empty, correctly-shaped `mplads.db` that step 02 can
fill and step 03 can score. It comes first because both the data
generator and the checks depend on exact column names, the
`COALESCE(final_cost, estimated_cost)` convention, and the pinned
reference date. Changing any of those once data exists means
regenerating everything.

## Depends on

Nothing. This is the first roadmap step.

## API endpoints

No API changes. `backend/main.py` arrives in step 04.

## Database changes

This step creates the entire schema from nothing. `backend/db.py` does
not exist yet, so there is nothing to verify against — this spec defines
what it will contain, transcribed from the Database schema section of
CLAUDE.md.

**Tables:**

- `works` — 20 columns, `work_id INTEGER PRIMARY KEY`. Includes
  `planted_anomaly TEXT` (ground truth, NULL for clean rows).
- `vendors` — `vendor_id PK · name · district · registered_on`
- `allocations` — one row per MP per FY:
  `mp_name · fy · entitlement · released · spent`
- `alerts` — `alert_id PK · subject_type · subject_id · risk_score ·
  severity · reasons_json · status · verdict · created_at`
- `complaints` — `complaint_id PK · work_id · text · photo_path ·
  lat · lon · reporter_hash · verified · created_at`

**Indexes:**

```sql
CREATE INDEX idx_works_peer  ON works(work_type, district, terrain);
CREATE INDEX idx_works_mp    ON works(mp_name, fy);
CREATE INDEX idx_alerts_subj ON alerts(subject_type, subject_id);
```

**Constraints to enforce in the schema:**

- `works.status` limited to `recommended / sanctioned / in_progress /
  completed`
- `works.terrain` limited to `plain / hilly / coastal`
- `works.unit` limited to `km / count / sqm`
- `works.is_sc_area` and `works.is_st_area` limited to 0 or 1
- `alerts.subject_type` limited to `work / mp / district`
- `alerts.severity` limited to `critical / high / medium`
- `alerts.status` limited to `open / acknowledged / escalated / resolved`
- `alerts.risk_score` limited to 0–100
- `complaints.verified` limited to 0 or 1
- `complaints` unique on `(work_id, reporter_hash)` — one complaint per
  reporter per work, which is what makes C6's distinct-reporter count
  meaningful
- `works.vendor_id` foreign key to `vendors.vendor_id`
- `complaints.work_id` foreign key to `works.work_id`

SC and ST spend are deliberately **not** columns on `allocations`. They
are derived by summing `works` where `is_sc_area = 1` or
`is_st_area = 1`. Do not add them.

## Detection logic

No detection logic. Checks are step 03. This step only defines the
thresholds and point caps in `config.py` that step 03 will read.

## Frontend

No frontend changes. The React app arrives in step 05.

## Files to change

- `CLAUDE.md` — tick step 01 in the roadmap table once the Definition of
  Done passes.

## Files to create

- `backend/__init__.py` — empty, so `python -m backend.generate_data`
  works.
- `backend/config.py` — `REFERENCE_DATE`, all thresholds, all point
  caps, the permitted and not-permitted work category lists, the
  work_type→unit map, and the peer-group fallback ladder.
- `backend/db.py` — `CREATE TABLE` statements, indexes, a
  `get_connection()` returning a `sqlite3.Connection` with
  `row_factory = sqlite3.Row` and `PRAGMA foreign_keys = ON`, an
  `init_db()` that drops and recreates every table, and thin query
  helpers for later steps.
- `.claude/specs/01-project-skeleton-schema.md` — this file.

**Directory rename required.** A `Backend/` directory (capital B)
currently holds two empty files, `Authentication.PY` and
`Authorization.py`. Neither belongs to the layout CLAUDE.md defines, and
`.PY` breaks imports on case-sensitive filesystems. Delete both with
`git rm`, then rename the directory to lowercase `backend/`. macOS is
case-insensitive, so git needs an explicit two-step move
(`git mv Backend backend2 && git mv backend2 backend`) or the rename
will not be recorded.

## New dependencies

No new dependencies. `fastapi` and `uvicorn` are already installed;
`sqlite3` ships with the standard library.

Two notes on what is already installed:

- **SQLAlchemy should be uninstalled.** It was installed earlier in this
  project, but CLAUDE.md forbids an ORM. Leaving it importable invites a
  later step to use it.
- `pandas`, `faker`, `python-multipart` and `openpyxl` appear in the
  CLAUDE.md quickstart but are not needed until steps 02 and 11.
  Install them when those steps arrive.

## Rules for implementation

- **No ORM.** Raw `sqlite3` only — no SQLAlchemy, no Prisma.
- **Parameterised queries only.** Never build SQL with f-strings.
- **No ML libraries in the prototype.** Detection is pure statistics and
  rules — median, IQR, date arithmetic, if/else. No scikit-learn, no
  model files, no LLM calls in the scoring path.
- **Every flag must be explainable.** A check that cannot produce a
  human-readable reason string is not allowed to add points.
- **Wording.** Never output the words "fraud", "scam", or "corrupt" in
  code, UI copy, or comments. Use "flagged", "needs verification",
  "risk indicator".
- **Never rank or score Members of Parliament.** Score works and
  transactions only.
- **CSS variables only** — never hardcode hex values in components. All
  colours come from `frontend/src/theme.css`.
- **Scoring is capped.** No single check may exceed the point cap
  defined in CLAUDE.md, and `risk_score` is clamped to 0–100.
- **Determinism.** Running the checks twice on the same data must
  produce identical scores.

Step-specific:

- **`REFERENCE_DATE = date(2026, 9, 15)`, pinned.** `config.py` must not
  import or call `date.today()`, and neither may anything reading it.
- **Every threshold and point cap lives in `config.py`.** Step 03 must
  be able to retune C1's fence multipliers or C2's day bands without
  editing `checks.py`. Name them explicitly, e.g. `C1_MAX_POINTS = 35`,
  `C2_DELAY_BANDS`, `PEER_GROUP_MIN_ROWS = 8`.
- **`init_db()` drops and recreates.** It must be safe to re-run at any
  time, matching the CLAUDE.md promise that `generate_data.py` is always
  safe to re-run.
- **No `SELECT *` in helpers.** Name columns, so a later schema change
  fails loudly instead of silently reordering a tuple.
- **Do not add SC/ST spend columns to `allocations`.** Storing them
  alongside the derived sum guarantees the two disagree.
- **`db.py` defines schema only — it inserts no rows.** All data comes
  from step 02.

## Definition of done

- [ ] `python -c "import backend.db"` succeeds from the project root.
- [ ] `python -m backend.db` (or an equivalent documented one-liner
      calling `init_db()`) creates `backend/mplads.db` with no errors.
- [ ] `sqlite3 backend/mplads.db ".tables"` lists exactly: `alerts`,
      `allocations`, `complaints`, `vendors`, `works`.
- [ ] `sqlite3 backend/mplads.db ".indexes"` includes `idx_works_peer`,
      `idx_works_mp`, and `idx_alerts_subj`.
- [ ] `sqlite3 backend/mplads.db "PRAGMA table_info(works)"` returns 20
      columns whose names and order match the CLAUDE.md schema table
      exactly, including `planted_anomaly`.
- [ ] Running `init_db()` twice in a row succeeds and leaves five empty
      tables — proving the drop-and-recreate path works.
- [ ] Inserting two `complaints` rows sharing a
      `(work_id, reporter_hash)` raises `IntegrityError`.
- [ ] Inserting an `alerts` row with `risk_score = 101` or
      `subject_type = 'vendor'` raises `IntegrityError`.
- [ ] `grep -rn "date.today\|datetime.now" backend/` returns nothing.
- [ ] `grep -rni "sqlalchemy\|fraud\|scam\|corrupt" backend/` returns
      nothing.
- [ ] `python -c "from backend.config import REFERENCE_DATE; print(REFERENCE_DATE)"`
      prints `2026-09-15`.
- [ ] The `Backend/` directory no longer exists, and `git log --follow`
      shows the rename to `backend/` was recorded.
- [ ] No recall check applies at this step — there is no data and no
      scoring yet. The first recall baseline is established in step 03
      and measured by `evaluate.py` in step 08.
