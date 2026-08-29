# MPLADS Risk Engine

Anomaly detection and monitoring platform for the Members of Parliament
Local Area Development Scheme. Smart India Hackathon, problem statement
26102 (MoSPI — Data Informatics & Innovation Division).

## What it does

Reads MPLADS works data, runs deterministic checks over every work, MP
and district, produces a 0–100 risk score with a written reason for each
point awarded, and shows officers a list of subjects that need
verification — worst first.

## What it is not

It does not detect fraud. It flags subjects whose numbers deviate from
comparable ones and from scheme rules, so a human can verify them.
A costly road may be a hilly road.

---

## Quickstart

```bash
# one-time
source smart_india_hackathon/bin/activate
pip install sqlalchemy fastapi uvicorn pandas faker python-multipart openpyxl
cd frontend && npm install && cd ..

# build the database from scratch
python -m backend.db                # empty schema: 16 tables, 12 indexes
python -m backend.generate_data     # fills mplads.db, 4000-5000 works
python -m backend.checks            # scores everything, fills alerts
python -m backend.evaluate          # prints recall vs planted anomalies

# run
uvicorn backend.main:app --reload --port 8000
cd frontend && npm run dev          # port 5173
```

The venv is `smart_india_hackathon/`, not `.venv/`. In a shell where it
is not activated, `python` will not resolve — use
`./smart_india_hackathon/bin/python` explicitly.

`init_db()` drops and recreates all tables; `generate_data.py` calls it,
so both are always safe to re-run. `checks.py` deletes and rebuilds the
`scores` and `alerts` tables only.

---

## Stack

| Layer | Choice | Notes |
|---|---|---|
| Database | SQLite (`backend/mplads.db`) | Single file, committed to git |
| Backend | FastAPI + uvicorn | Python 3.11+ |
| DB access | SQLAlchemy 2.x ORM | plus `text()` for analytics — see below |
| Auth | JWT (PyJWT), 12-hour expiry | no server-side session table |
| Data | `faker` + `pandas` | Generated, not scraped |
| Frontend | React (Vite), plain JS | No TypeScript |
| Charts | Recharts | |
| Styling | Plain CSS + variables | `frontend/src/theme.css` |

---

## Folder layout

```
mplads/
├── CLAUDE.md
├── .claude/
│   ├── commands/spec_document_creater.md
│   └── specs/                 ← one spec per build step
├── backend/
│   ├── config.py              ← REFERENCE_DATE, thresholds, point caps
│   ├── models.py              ← the 16 tables; imports no engine
│   ├── db.py                  ← engine, SessionLocal, init_db, FK pragma
│   ├── auth.py                ← JWT issue/decode, scope dependency (step 05)
│   ├── generate_data.py       ← fills mplads.db with planted anomalies
│   ├── checks.py              ← the checks + scoring
│   ├── evaluate.py            ← recall against planted anomalies
│   ├── main.py                ← FastAPI endpoints
│   └── mplads.db
└── frontend/
    └── src/
        ├── theme.css          ← every colour lives here
        ├── api.js             ← every fetch call lives here
        ├── App.jsx
        └── pages/
            ├── AlertList.jsx
            ├── AlertDetail.jsx
            ├── Dashboard.jsx
            └── ReportIssue.jsx
```

---

## Roadmap

Mark a step complete only when its Definition of Done passes.

| Step | Feature | Status |
|---|---|---|
| 01 | Project skeleton, config, database schema | ☑ |
| 02 | Dummy data generator with planted anomalies | ☐ |
| 03 | Detection checks and risk scoring | ☐ |
| 04 | API endpoints | ☐ |
| 05 | Alert list screen | ☐ |
| 06 | Alert detail screen | ☐ |
| 07 | Dashboard screen | ☐ |
| 08 | Accuracy evaluation script | ☐ |
| 09 | Role switching and filters | ☐ |
| 10 | Citizen report screen | ☐ |
| 11 | CSV / Excel upload | ☐ |
| 12 | Demo seed data and polish | ☐ |

**Steps 01–08 are the minimum viable prototype.** 09–12 are additive.
Step 08 moved ahead of the extras deliberately — the accuracy number is
worth more than any additional screen.

---

## Critical: the reference date

Every date calculation reads `REFERENCE_DATE` from `backend/config.py`.

```python
REFERENCE_DATE = date(2026, 9, 15)   # pin this, never move it
```

**Never call `date.today()` anywhere in `checks.py` or
`generate_data.py`.** If you do, delay scores drift every day, your
demo changes overnight, and the recall number on your slide stops
matching what the app shows. Pin it once and leave it.

---

## Database schema

Defined in `backend/models.py`. **Sixteen tables in five groups.**
`.claude/specs/01-project-skeleton-schema.md` is the authoritative
version; do not change a column without updating both in the same
commit.

Two conventions run through every table:

- **Dates are ISO-8601 strings** typed `String`, never `Date` or
  `DateTime`. SQLite has no date type, SQLAlchemy's date types add
  silent conversion, and ISO text sorts and compares correctly in both
  Python and SQL.
- **Money is `Integer` rupees.** No `Float` or `Numeric` for currency.

### Group A — reference data

Geography and people, referenced by ID everywhere else. Storing
`district` as free text on every work makes filtering and role scoping
unreliable the first time a name is spelled two ways.

`states` · `districts` · `constituencies` · `mps` · `agencies` ·
`vendors`

- `districts.is_hill_district` and `districts.default_area_type` are
  **generation hints only.** They seed a new work's `terrain` and
  `area_type`; the values that matter for detection live on the work.
  **Nothing in `checks.py` may read either** — doing so would excuse a
  flat road in a hill district as expensive-by-terrain.
- `mps.term_start` / `term_end` are not decoration: a work recommended
  outside an MP's term is a data-integrity flag in C3.
- `vendors.pan_hash` is a hash, never a real or realistic PAN.

### Group B — accounts and access

`users` — everyone who can log in, **including citizens**. A citizen
login is what makes the one-complaint-per-person rule enforceable.
Still separate from `mps`: an MP is a person in the scheme, a user is a
login.

`scope_type` + `scope_id` decide which **rows** are visible. `role`
decides which **actions** are allowed. Keeping the two separate is what
stops the role system becoming unmaintainable.

**Only District and State officers act on alerts.** MPs and the Ministry
are view-only. Under the scheme an MP *recommends* works while the
District Authority sanctions, executes and verifies them — a platform
letting an MP close an alert on their own constituency's work would
invert the accountability the scheme is built on.

There is **no `sessions` table.** Login issues a JWT carrying `sub`
(user_id, as a **string** — PyJWT rejects an integer `sub`), `role`,
`scope_type`, `scope_id` and `exp` (12 hours). The signing secret comes
from the `JWT_SECRET` environment variable, is at least 32 bytes, and
never appears in the repository.

The honest cost: a stateless token cannot be revoked, so logout only
deletes the client's copy and `is_active = 0` does not bite until the
token expires. Mitigate by checking `users.is_active` on state-changing
actions while skipping it on plain reads.

**The login screen may show a role selector, but the server must ignore
it** and read `role` from the database. A client that declares its own
role has no access control at all.

### Group C — the scheme's core records

`allocations` — one row per MP per financial year, `UNIQUE(mp_id, fy)`.
**No SC/ST spend columns:** those are derived by summing `works` where
`is_sc_area = 1` / `is_st_area = 1`. Storing them alongside the derived
sum guarantees the two disagree.

`works` — the central table, **27 columns**. Beyond the obvious ones:

| Column | Why it exists |
|---|---|
| `area_type` | metro / urban / semi_urban / rural. Urbanisation, independent of terrain — Mumbai is coastal *and* metro. A metro road legitimately costs several times a rural one. |
| `recommended_on` | Separate from `sanctioned_on`; the gap is the District Authority's sanction lag, a distinct signal from execution delay. |
| `expected_completion_on` | Stored, not computed — set at sanction as `sanctioned_on + EXPECTED_DURATION_DAYS[(work_type, area_type)]`. Derived in two places, the citizen page and `checks.py` would eventually disagree about what "overdue" means. |
| `progress_pct` | For the payment-versus-progress gap. May be zero or stale; checks must handle that. |
| `last_updated_on` | When the record was last touched at all — the fallback that works on incomplete data. |
| `planted_anomaly` | Ground truth, **last column**. Never read by `checks.py`, never returned by the API. |

**Cost convention:** always `COALESCE(final_cost, estimated_cost)`.
Never `final_cost` alone — it is NULL for every unfinished work, which
would silently exclude exactly the works most likely to be problems.

`payments` — one row per tranche, `UNIQUE(work_id, tranche_no)`. Without
it there is no payment-versus-progress gap.

`progress_updates` — the *history* of the progress field. A number that
jumped from 20 to 90 in a day, or whose whole history was entered on one
afternoon, is visible here and nowhere else.

`evidence` — photos and documents. **The absence of rows is itself the
signal:** a work marked complete with no evidence row is exactly what
needs verification. `photo_hash` is a perceptual hash, so a reused photo
is a self-join.

### Group D — output of the system

**`scores` and `alerts` are separate tables, deliberately.** A score is
a *measurement* — every work, MP and district has one, including clean
subjects scoring 3. An alert is a *workflow item*, created only when
`total_score >= 25` and carrying status, assignee and verdict. Jamming
them together leaves clean works with no score anywhere, which breaks the
citizen-facing project listing.

`scores` — 15 columns, `UNIQUE(subject_type, subject_id)`. Seven
`*_points` columns sit alongside `reasons_json` because they are
**queryable**: "which districts have a delay problem specifically" is a
`GROUP BY`, not JSON parsing in Python. `reasons_json` carries the
sentences the UI prints; the columns carry the numbers.

`checks_skipped` implements graceful degradation. A check whose required
fields are absent records *why* rather than silently scoring zero, so the
alert page can say "3 of 8 checks ran".

`reasons_json` is a JSON array; every entry has exactly these keys:

```json
[
  {
    "check": "C1",
    "points": 31,
    "reason": "Cost per km is ₹8.4 lakh against a metro-hilly median of ₹2.0 lakh (4.2×).",
    "evidence": { "value": 840000, "median": 200000, "ratio": 4.2,
                  "peer_count": 47, "peer_level": "work_type+terrain+area_type" }
  }
]
```

`reason` is what the UI prints. `evidence` is what charts read. The
frontend must never recompute a number that is not in `evidence`.

`alerts` — 10 columns, `score_id` FK **unique**: one alert per score.
`verdict` and `resolution_note` are not optional decoration — an officer
must not be able to clear a ₹31 lakh alert with a bare "visited" button.
Both are required when `status` moves to `resolved`, enforced in the API
at step 04 rather than in the schema so the constraint stays readable.
`snoozed_until` is the honest alternative to a dismiss button: the alert
returns instead of disappearing.

`complaints` — filed by a logged-in citizen, `UNIQUE(work_id, user_id)`.
That constraint is what makes C6's distinct-reporter count meaningful and
stops one person inflating a score. **Never store a raw phone number or
device ID anywhere.**

### Group E — accountability

`audit_log` — every state-changing action. **Append-only: nothing in the
codebase may UPDATE or DELETE from it.**

### Polymorphic columns

`users.scope_id`, `scores.subject_id` and `audit_log.subject_id` are
**deliberately not ForeignKeys** — their target table depends on a
sibling column. All three are commented in `models.py` so a later reader
does not "fix" them.

**Never join on `subject_id` without first filtering `subject_type`.**
This trap fails silently rather than erroring — a district-level score
with `subject_id = 3` will happily match `work_id = 3`, and an officer
sees an alert about MP #1 rendered as work #1. Put the filter and the
join in a single shared helper so the two can never be separated.

### Indexes

Twelve, declared in each model's `__table_args__`:

```
idx_works_peer          works(work_type, terrain, area_type, district_id)
idx_works_mp            works(mp_id, fy)
idx_works_district      works(district_id, status)
idx_works_constituency  works(constituency_id)
idx_payments_work       payments(work_id)
idx_progress_work       progress_updates(work_id, reported_on)
idx_evidence_work       evidence(work_id, kind)
idx_evidence_hash       evidence(photo_hash)
idx_scores_subj         scores(subject_type, subject_id)
idx_scores_total        scores(subject_type, total_score)
idx_alerts_open         alerts(status, severity)
idx_complaints_work     complaints(work_id, verified)
```

Three are load-bearing: `idx_works_peer` (its column order matches the
peer-group ladder, so each rung is a prefix), `idx_scores_total` (the
worklist sort) and `idx_evidence_hash` (the reused-photo self-join).

## Permitted work categories

C3 checks `work_type` and `description` against these. Taken from the
MPLADS guidelines — **re-verify before final submission.**

**Permitted:** drinking water, education, electricity, health, sanitation,
roads and pathways, bridges, irrigation, community centres, public
libraries, sports facilities, non-conventional energy, urban development,
animal husbandry.

**Not permitted (these are what C3 actually flags):** office or
residential buildings for government bodies, memorials and statues,
places of religious worship, land acquisition, assets for individual
benefit, works on private land, grants to commercial organisations.

---

## Scoring

Each check returns a list of `{check, points, reason, evidence}`.
Points are summed per subject and clamped to 0–100.

**Every subject gets a `scores` row**, including clean ones scoring 3.
An `alerts` row is written only at 25 and above. Per-check totals go in
the `*_points` columns as well as `reasons_json`, so the dashboard's
flags-by-type chart is a `GROUP BY` rather than JSON parsing.

**Checks run at three levels. Do not mix them.** Awarding an MP's quota
shortfall to each of their individual works would flag every work that
MP ever recommended — a false-positive machine, and the fastest way to
lose credibility in a demo.

### Work-level checks — subject_type = `work`

| Check | Max | Rule |
|---|---|---|
| **C1 cost outlier** | 35 | Unit cost = `COALESCE(final_cost, estimated_cost) / quantity`. Compare against the median unit cost of its peer group. Points scale with distance past the upper IQR fence (Q3 + 1.5·IQR): at the fence → 10, at 2× median → 20, at 3× → 28, at 4×+ → 35. |
| **C2 delay** | 25 | `REFERENCE_DATE − sanctioned_on` while `status != completed`. 180–364 days → 10, 365–539 → 18, 540+ → 25. |
| **C3 work compliance** | 15 | `completed_on` earlier than `sanctioned_on` → 15. `work_type` or description matching the not-permitted list → 15. `sanctioned_on` in the future → 15. Take the highest, do not stack. |
| **C5 duplicate** | 20 | Another work with same district, same work_type, unit cost within 10%, sanctioned within 60 days. Creates an alert on **both** works, each naming the other. |
| **C6 citizen reports** | 15 | Count of `verified = 1` complaints, one per citizen per work by constraint. 1 → 5, 2–3 → 10, 4+ → 15. Hard cap. |
| **C7 evidence gap** | 20 | Money paid against a work with no `evidence` rows, or `progress_pct` far below the share of cost already disbursed. |

### Peer group for C1

Defined as `PEER_GROUP_LADDER` in `config.py`. Try in this order and stop
at the first group with **at least 8 rows**:

1. `work_type + terrain + area_type + district_id`
2. `work_type + terrain + area_type + state_id`
3. `work_type + terrain + area_type`
4. `work_type + area_type`
5. `work_type`

`area_type` is given up **after** district deliberately: urbanisation
explains more cost variance than geography does, so it is worth keeping
longer.

If even the last rung has fewer than 8 rows, **skip C1, award zero, and
record it in `scores.checks_skipped`** — do not guess. Record the rung
used in `evidence.peer_level` so the UI can say "compared against 47
hilly metro roads".

**Dataset-size consequence:** three dimensions plus district makes rung 1
small. With 2,000 works across 8 work types, 3 terrains and 4 area types
the first rung averages a handful of rows — not a median. **Step 02 must
generate 4,000–5,000 works**, and most comparisons will land on rung 3.

### MP-level checks — subject_type = `mp`

| Check | Max | Rule |
|---|---|---|
| **C3-MP quota** | 25 | SC-area spend below 15% of that MP's released funds for the year → up to 15 points, scaled by the size of the shortfall. ST-area spend below 7.5% → up to 10. These stack with each other. |

### District-level checks — subject_type = `district`

| Check | Max | Rule |
|---|---|---|
| **C4 utilisation** | 15 | `spent / released < 50%` for the year → 10. More than 60% of the year's spend falling in Jan–Mar → 8. Stack, cap at 15. |

### Severity bands

| Score | Severity | Token |
|---|---|---|
| 70–100 | critical | `--sev-critical` |
| 45–69 | high | `--sev-high` |
| 25–44 | medium | `--sev-medium` |
| 0–24 | — | no alert row written |

---

## Planted anomalies

`generate_data.py` plants these, writing the label into
`planted_anomaly`. `evaluate.py` measures recall per label.

| Label | How many | What it looks like |
|---|---|---|
| `cost_overrun` | 60 | Unit cost 3–6× the peer median |
| `long_delay` | 80 | Sanctioned 400–700 days ago, still unfinished |
| `impossible_date` | 20 | `completed_on` before `sanctioned_on` |
| `ineligible_work` | 20 | work_type from the not-permitted list |
| `duplicate_pair` | 40 (20 pairs) | Near-identical twin within 60 days |
| `quota_shortfall` | 4 MPs | SC spend forced under 15% |

Total ~220 planted rows out of ~2000. Everything else must be clean —
if the clean rows also trip checks, your false-positive rate is real and
you need to loosen thresholds, not hide it.

`evaluate.py` must report, per label: planted, caught, recall. Plus one
overall false-positive rate: clean works that received an alert.

---

## Frontend

### CSS variables — `theme.css`

No hex value may appear in any component. The full token set:

```
--bg  --surface  --surface-2  --border
--text  --text-muted  --text-faint
--accent  --accent-soft
--sev-critical  --sev-critical-bg
--sev-high      --sev-high-bg
--sev-medium    --sev-medium-bg
--ok  --ok-bg
--radius  --shadow
```

Define light values on `:root`, dark under both
`@media (prefers-color-scheme: dark)` and `[data-theme="dark"]`.

### Rules

- The alert list is the **home screen**. Not a tab, not a subpage.
- **Every score is shown with its reasons.** A bare number is never
  displayed alone — not in a table cell, not in a tooltip.
- All fetch calls live in `api.js`. No `fetch()` inside a component.
- Loading and empty states are required on every page. "No alerts in
  this district" is a real state, not a bug.

---

## Rules

### Data and detection
- **SQLAlchemy 2.x ORM** for schema, CRUD, auth and serialisation;
  **`text()` with bound parameters** for the analytical queries in
  `checks.py`, where peer-group aggregates read more clearly as SQL. No
  other data-access style. `alembic` is not used — `drop_all` +
  `create_all` is the migration strategy while the database is rebuilt
  from scratch on every run.
- **No string-formatted SQL, ever.** Named parameters in `text()`; never
  f-strings, never `%` formatting, never concatenation.
- **No machine-learning libraries in the prototype.** Detection is
  median, IQR, date arithmetic and rules. No scikit-learn, no model
  files, no LLM calls in the scoring path.
- **Determinism.** Running `checks.py` twice on the same database must
  produce byte-identical `scores` and `alerts`. That means:
  `REFERENCE_DATE`, a fixed random seed in `generate_data.py`, and never
  reading the system clock for the current date.
- A check that cannot produce a human-readable `reason` string may not
  award points.
- **A check that cannot run must say so** in `scores.checks_skipped`,
  with a reason. Never silently score zero.
- **The server never trusts a client-supplied role or scope.** Both come
  from the verified JWT, which was built from `users`.
- **Scope filtering is one shared dependency, never per-route.** Never
  filter by scope in the frontend, and never accept a district, state or
  constituency id from the client — a route taking `?district_id=` lets
  an officer type someone else's.
- `checks.py` must never read `planted_anomaly`. The API must never
  return it.
- Thresholds and point caps live in `config.py`, never inline in
  `checks.py`.

### Language
- Never write "fraud", "scam", or "corrupt" in code, comments, or UI
  copy. Use "flagged", "needs verification", "risk indicator".
- The system scores works, MPs' *compliance*, and districts'
  *utilisation*. There is **no MP risk leaderboard** and no ranking of
  Members of Parliament by suspicion.

### Git
- One feature branch per roadmap step: `feature/<slug>`.
- Commit `mplads.db` so the whole team sees identical data.
- Never commit to `main` directly.

---

## How to verify your work

Before marking any step complete:

```bash
python -m backend.generate_data && python -m backend.checks
python -m backend.checks          # run twice
```
The second run must produce the same alert count and the same top-10
scores. If not, something is non-deterministic.

Schema-only changes can be checked without generating data:

```bash
python -m backend.db && python -m backend.db      # idempotent
sqlite3 backend/mplads.db ".tables"               # 16, no `sessions`
sqlite3 backend/mplads.db ".indexes" | tr ' ' '\n' | grep -c '^idx_'   # 12
```

```bash
python -m backend.evaluate
```
Recall must not drop below the previous step's number. Record the
number in the spec's Definition of Done.

Then open the app and click the top alert. If you cannot explain out
loud why it scored what it scored, using only what is on screen, the
step is not done.

---

## Common mistakes to avoid

| Mistake | Why it hurts |
|---|---|
| Using `final_cost` without COALESCE | Silently drops every unfinished work — the risky ones |
| Reading the system clock instead of `REFERENCE_DATE` | Demo drifts, slide number stops matching the app |
| MP quota shortfall applied to each work | Flags every work that MP recommended |
| Peer group with 3 rows | A median of 3 is noise; one outlier defines "normal" |
| Joining on `subject_id` without filtering `subject_type` | Fails silently: an alert about MP #1 renders as work #1 |
| Forgetting the `foreign_keys` pragma listener | Every FK becomes decorative; SQLite has them off by default |
| Reading `districts.is_hill_district` in checks | Excuses a flat road in a hill district as expensive-by-terrain |
| Reading `planted_anomaly` in checks | Your accuracy number becomes fake and a judge can catch it |
| Bare score in the UI | Kills the explainability story the whole project rests on |
| Word "scam" on screen | A hilly road legitimately costs more; you just accused someone |

---

## Before final submission

Re-verify against the current official MPLADS guidelines:

- ₹5 crore annual entitlement per MP. **Since 1 April 2023 this is
  released as a single annual instalment, not two of ₹2.5 crore** —
  model years either side of that change correctly if the dataset spans
  them
- 15% Scheduled Caste and 7.5% Scheduled Tribe area floors
- The permitted and not-permitted work category lists
- Treatment of interest earned on unspent funds

The 2023 revision changed several provisions. A rule engine citing a
superseded clause is worse than no rule engine.