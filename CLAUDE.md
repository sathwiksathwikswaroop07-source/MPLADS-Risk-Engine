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
python -m venv .venv && source .venv/bin/activate
pip install fastapi uvicorn pandas faker werkzeug python-multipart openpyxl
cd frontend && npm install && cd ..

# build the database from scratch
python -m backend.db                # creates empty mplads.db
python -m backend.generate_data     # fills it, ~2000 works
python -m backend.checks            # scores everything, fills alerts
python -m backend.evaluate          # prints recall vs planted anomalies

# run
uvicorn backend.main:app --reload --port 8000
cd frontend && npm run dev          # port 5173
```

`generate_data.py` drops and recreates all tables. Always safe to
re-run. `checks.py` rebuilds the `alerts` table only.

---

## Stack

| Layer | Choice | Notes |
|---|---|---|
| Database | **SQLite** (`backend/mplads.db`) | Single file, committed to git |
| Backend | FastAPI + uvicorn | Python 3.11+ |
| DB access | Raw `sqlite3` | No ORM, ever |
| Auth | Server-side session table | Not JWT |
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
│   ├── commands/spec.md
│   └── specs/                 ← one spec per build step
├── backend/
│   ├── __init__.py
│   ├── config.py              ← REFERENCE_DATE, thresholds, point caps
│   ├── db.py                  ← schema + connection + query helpers
│   ├── generate_data.py       ← builds mplads.db with planted anomalies
│   ├── checks.py              ← the checks + scoring
│   ├── auth.py                ← login, sessions, scope enforcement
│   ├── evaluate.py            ← recall against planted anomalies
│   ├── main.py                ← FastAPI endpoints
│   └── mplads.db
└── frontend/
    └── src/
        ├── theme.css          ← every colour lives here
        ├── api.js             ← every fetch call lives here
        ├── App.jsx
        └── pages/
            ├── Login.jsx
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
| 01 | Project skeleton, config, database schema | ☐ |
| 02 | Dummy data generator with planted anomalies | ☐ |
| 03 | Detection checks and risk scoring | ☐ |
| 04 | API endpoints | ☐ |
| 05 | Login, sessions, scope enforcement | ☐ |
| 06 | Alert list screen | ☐ |
| 07 | Alert detail screen | ☐ |
| 08 | Accuracy evaluation script | ☐ |
| 09 | Dashboard screen | ☐ |
| 10 | Citizen report screen | ☐ |
| 11 | CSV / Excel upload | ☐ |
| 12 | Demo seed data and polish | ☐ |

**Steps 01–08 are the minimum viable prototype.** 09–12 are additive.
Step 08 sits ahead of the extra screens deliberately — the accuracy
number is worth more than another page.

---

## Critical: the reference date

Every date calculation reads `REFERENCE_DATE` from `backend/config.py`.

```python
REFERENCE_DATE = date(2026, 9, 15)   # pin this, never move it
```

**Never call `date.today()` or `datetime.now()` anywhere in `backend/`.**
If you do, delay scores drift every day, the demo changes overnight, and
the recall number on your slide stops matching what the app shows.

---

## Database schema

Sixteen tables. Defined in `backend/db.py`. Column order is normative.
Do not change a column without updating this section in the same commit.

Full rationale for each table is in
`.claude/specs/01-project-skeleton-schema.md`.

### Conventions

- **Dates are ISO-8601 TEXT** — `YYYY-MM-DD`, or `YYYY-MM-DDTHH:MM:SS`
  for datetimes. SQLite has no date type; ISO text sorts and compares
  correctly, other formats do not.
- **Money is INTEGER rupees.** No floats for currency, anywhere.
- **Booleans are INTEGER 0/1** with a CHECK constraint.
- **No real identity data.** PANs and reporter identifiers are hashes.
- `get_connection()` must set `row_factory = sqlite3.Row` and run
  `PRAGMA foreign_keys = ON` — SQLite ignores foreign keys without it.

### Group A — Reference data

**`states`** — `state_id PK · name · code`

**`districts`** — `district_id PK · state_id FK · name ·
is_hill_district` · UNIQUE(state_id, name)

**`constituencies`** — `constituency_id PK · state_id FK · name ·
house` · UNIQUE(state_id, name, house)

**`mps`** — `mp_id PK · full_name · house · constituency_id FK ·
state_id FK · term_start · term_end · is_active`

`term_start` / `term_end` are used by C3 — a work recommended outside an
MP's term is a data-integrity flag.

**`agencies`** — `agency_id PK · name · agency_type · district_id FK`

**`vendors`** — `vendor_id PK · name · district_id FK · pan_hash ·
address · registered_on · is_active`

### Group B — Accounts and access

**`users`** — `user_id PK · username · password_hash · full_name ·
role · scope_type · scope_id · mp_id FK · is_active · created_at ·
last_login_at`

An MP is a *person in the scheme* (`mps`); a user is *a login*. Keep
them separate. `role` decides which actions are allowed; `scope_type` +
`scope_id` decides which rows are visible. Never conflate the two.

**Citizens are not users.** The public report page is unauthenticated.

**`sessions`** — `token PK · user_id FK · created_at · expires_at`

Deliberately not JWT — a server-side table makes logout and revocation
trivial and avoids refresh-token bugs.

### Group C — Scheme records

**`allocations`** — `allocation_id PK · mp_id FK · fy · entitlement ·
released · spent · released_on` · UNIQUE(mp_id, fy)

SC/ST spend are **not** columns here. They are derived by summing
`works` where `is_sc_area = 1` / `is_st_area = 1`. Storing them twice
guarantees they disagree.

**`works`** — 25 columns, in this order:

| # | Column | Notes |
|---|---|---|
| 1 | work_id | PK |
| 2 | mp_id | FK mps |
| 3 | constituency_id | FK |
| 4 | district_id | FK |
| 5 | agency_id | FK, nullable pre-sanction |
| 6 | vendor_id | FK, nullable pre-award |
| 7 | fy | "2024-25" |
| 8 | work_type | see permitted list |
| 9 | description | free text, messy on purpose |
| 10 | terrain | plain / hilly / coastal |
| 11 | quantity | see unit map |
| 12 | unit | km / count / sqm |
| 13 | estimated_cost | INTEGER rupees |
| 14 | final_cost | NULL until completed |
| 15 | recommended_on | ISO date |
| 16 | sanctioned_on | ISO date, nullable |
| 17 | completed_on | ISO date, nullable |
| 18 | status | recommended / sanctioned / in_progress / completed |
| 19 | progress_pct | 0–100, may be stale |
| 20 | last_updated_on | ISO date — staleness signal |
| 21 | lat | |
| 22 | lon | |
| 23 | is_sc_area | 0/1 |
| 24 | is_st_area | 0/1 |
| 25 | planted_anomaly | ground truth, NULL for clean rows |

**Cost convention:** always `COALESCE(final_cost, estimated_cost)`.
Never `final_cost` alone — it is NULL for every unfinished work, which
would silently exclude exactly the works most likely to be problems.

**Units by work_type** — a peer group is always one work_type, so units
never mix:

| work_type | unit | quantity means |
|---|---|---|
| road | km | length |
| drain | km | length |
| borewell | count | number sunk |
| streetlight | count | poles installed |
| community_hall | sqm | built-up area |
| school_wall | sqm | wall area |

`planted_anomaly` exists only so `evaluate.py` can measure recall. It
must never be read by `checks.py` and never returned by the API.

**`payments`** — `payment_id PK · work_id FK · vendor_id FK ·
tranche_no · amount · paid_on · progress_pct_at_payment · voucher_ref` ·
UNIQUE(work_id, tranche_no)

**`progress_updates`** — `update_id PK · work_id FK · progress_pct ·
reported_on · reported_by · note`

The *history*, not just the current value. A falsified progress number
is hard to spot; a jump from 20 to 90 in one day, or a whole history
entered on one afternoon, is not.

**`evidence`** — `evidence_id PK · work_id FK · kind · file_path ·
photo_hash · exif_lat · exif_lon · stage · captured_at · uploaded_at`

`kind`: photo / completion_cert / handover / utilisation_cert.
**The absence of rows here is itself the signal.**

### Group D — System output

**`alerts`** — `alert_id PK · subject_type · subject_id · risk_score ·
severity · reasons_json · status · verdict · assigned_to FK ·
created_at · resolved_at`

`subject_type`: work / mp / district. `subject_id` is an INTEGER —
work_id, mp_id, or district_id. Never assume it is a work.

`reasons_json` shape, fixed:

```json
[
  {
    "check": "C1",
    "points": 31,
    "reason": "Cost per km is ₹8.4 lakh against a district median of ₹2.0 lakh for hilly roads (4.2×).",
    "evidence": { "value": 840000, "median": 200000, "ratio": 4.2, "peer_count": 47, "peer_level": "district" }
  }
]
```

`reason` is what the UI prints. `evidence` is what charts read. The
frontend must never recompute a number that is not in `evidence`.

**`complaints`** — `complaint_id PK · work_id FK · reporter_hash ·
text · photo_path · lat · lon · verified · verified_by FK ·
created_at` · UNIQUE(work_id, reporter_hash)

That unique constraint is what makes C6's distinct-reporter count
meaningful and stops one person inflating a score. Never store a raw
phone number, name, or device ID — hash on the way in.

### Group E — Accountability

**`audit_log`** — `log_id PK · user_id FK · action · subject_type ·
subject_id · detail · created_at`

Append-only. Nothing may UPDATE or DELETE from it.

### Indexes

```sql
CREATE INDEX idx_works_peer     ON works(work_type, district_id, terrain);
CREATE INDEX idx_works_mp       ON works(mp_id, fy);
CREATE INDEX idx_works_district ON works(district_id, status);
CREATE INDEX idx_payments_work  ON payments(work_id);
CREATE INDEX idx_progress_work  ON progress_updates(work_id, reported_on);
CREATE INDEX idx_evidence_work  ON evidence(work_id, kind);
CREATE INDEX idx_alerts_subj    ON alerts(subject_type, subject_id);
CREATE INDEX idx_alerts_open    ON alerts(status, risk_score DESC);
CREATE INDEX idx_sessions_user  ON sessions(user_id);
```

`idx_alerts_open` is what makes the worklist fast — it is the query the
officer's home screen runs on every page load.

---

## Permitted work categories

C3 checks `work_type` and `description` against these lists.
**Re-verify against the current guidelines before final submission.**

**Permitted:** drinking water, education, electricity, health,
sanitation, roads and pathways, bridges, irrigation, community centres,
public libraries, sports facilities, non-conventional energy, urban
development, animal husbandry.

**Not permitted — this is what C3 flags:** office or residential
buildings for government bodies, memorials and statues, places of
religious worship, land acquisition, assets for individual benefit,
works on private land, grants to commercial organisations.

---

## Scoring

Each check returns `{check, points, reason, evidence}`. Points are
summed per subject and clamped to 0–100.

**Checks run at three levels. Do not mix them.** Awarding an MP's quota
shortfall to each of their individual works would flag every work that
MP ever recommended — a false-positive machine, and the fastest way to
lose credibility in a demo.

### Work-level — `subject_type = 'work'`

| Check | Max | Rule |
|---|---|---|
| **C1 cost outlier** | 35 | Unit cost = `COALESCE(final_cost, estimated_cost) / quantity`, compared against the peer-group median. Points scale past the upper IQR fence (Q3 + 1.5·IQR): at the fence → 10, 2× median → 20, 3× → 28, 4×+ → 35. |
| **C2 delay** | 25 | `REFERENCE_DATE − sanctioned_on` while `status != completed`. 180–364 days → 10, 365–539 → 18, 540+ → 25. |
| **C2b predicted stall** | 8 | Not yet late, but on track to be: `progress_pct` below expected-for-elapsed-time and no update in 90 days. This is the "early warning" the PS asks for. |
| **C3 work compliance** | 15 | Highest of: `completed_on` before `sanctioned_on`; `sanctioned_on` before `recommended_on`; either date in the future; work outside the MP's term; work_type or description in the not-permitted list. Do not stack. |
| **C5 duplicate** | 20 | Another work with same district, same work_type, unit cost within 10%, sanctioned within 60 days. Creates an alert on **both** works, each naming the other. |
| **C6 citizen reports** | 15 | Count of `verified = 1` complaints with distinct `reporter_hash`. 1 → 5, 2–3 → 10, 4+ → 15. Hard cap. |
| **C7 ghost asset risk** | 35 | Sum, capped: payment ratio exceeds progress ratio by >0.20 → 10, >0.35 → 18, >0.50 → 25. Marked completed with zero `evidence` rows → 15. No `last_updated_on` change in 180 days while payment ratio > 0.5 → 12. Completion implausibly fast for the work type → 12. `photo_hash` matching another work's evidence → 20. |

### MP-level — `subject_type = 'mp'`

| Check | Max | Rule |
|---|---|---|
| **C3-MP quota** | 25 | SC-area spend below 15% of that MP's released funds for the year → up to 15, scaled by shortfall. ST-area spend below 7.5% → up to 10. These stack. |

### District-level — `subject_type = 'district'`

| Check | Max | Rule |
|---|---|---|
| **C4 utilisation** | 15 | `spent / released` behind where the calendar says it should be for the year elapsed → 10. More than 60% of the year's spend falling in Jan–Mar → 8. Stack, cap at 15. |

Measure utilisation against the calendar, not raw unspent balance. Under
the single-annual-release model funds sit in a nodal account and are
drawn down as needed, so a low spend early in the year is normal.

### Peer group for C1

Try in order, stop at the first group with at least
`PEER_GROUP_MIN_ROWS` (8) rows:

1. `work_type + district_id + terrain`
2. `work_type + state_id + terrain`
3. `work_type + terrain`
4. `work_type`

If even the last has fewer than 8 rows, **skip C1 and award zero** — do
not guess. Record which level was used in `evidence.peer_level` so the
UI can say "compared against 47 hilly roads in this district".

### Graceful degradation

Every check declares the fields it needs. If a field is absent, the
check **skips and says so** — it must not crash and must not silently
score zero.

```python
CHECKS = [
  {"id": "C1", "needs": ["estimated_cost", "quantity"], "tier": "public"},
  {"id": "C2", "needs": ["sanctioned_on", "status"],    "tier": "public"},
  {"id": "C4", "needs": ["released", "spent"],          "tier": "public"},
  {"id": "C7", "needs": ["payments", "progress_pct"],   "tier": "internal"},
]
```

The alert page then shows: *"3 of 8 checks ran. Payment-progress and
evidence checks require authenticated eSAKSHI data."* That line tells a
judge you know exactly what your system needs and that it degrades
honestly.

### Severity bands

| Score | Severity | Token |
|---|---|---|
| 70–100 | critical | `--sev-critical` |
| 45–69 | high | `--sev-high` |
| 25–44 | medium | `--sev-medium` |
| 0–24 | — | no alert row written |

---

## Roles and scope

Every query is filtered by the logged-in user's scope **on the backend**.
The frontend is never trusted to filter. Changing a URL parameter must
produce 403, not another district's data.

| Role | scope_type | Sees | May act on alerts |
|---|---|---|---|
| mp | constituency | Own constituency | No — view only |
| district_officer | district | Own district | Acknowledge / escalate / resolve |
| state_officer | state | All districts in state | Acknowledge / escalate / resolve |
| ministry | national | Everything | No — view only |

An MP views; they do not investigate. Under the scheme MPs recommend
works while District Authorities execute and verify — the permission
matrix should reflect that.

---

## Planted anomalies

`generate_data.py` plants these, writing the label into
`planted_anomaly`. `evaluate.py` measures recall per label.

| Label | Count | What it looks like |
|---|---|---|
| `cost_overrun` | 60 | Unit cost 3–6× the peer median |
| `long_delay` | 80 | Sanctioned 400–700 days ago, still unfinished |
| `impossible_date` | 20 | `completed_on` before `sanctioned_on` |
| `ineligible_work` | 20 | work_type from the not-permitted list |
| `duplicate_pair` | 40 (20 pairs) | Near-identical twin within 60 days |
| `payment_ahead_of_work` | 40 | Payment ratio 0.75–0.95, progress 0.10–0.30 |
| `ghost_asset` | 30 | Marked complete, no evidence rows, fully paid |
| `quota_shortfall` | 4 MPs | SC spend forced under 15% |

Roughly 290 planted rows out of ~2000. Everything else must be clean —
if clean rows also trip checks, your false-positive rate is real and you
loosen thresholds rather than hide it.

Generate some works with `progress_pct = 0` and empty
`progress_updates` on purpose, so the graceful-degradation path is
exercised by the data, not just by intention.

`evaluate.py` reports per label: planted, caught, recall — plus one
overall false-positive rate (clean works that received an alert).

---

## Frontend

### CSS variables — `theme.css`

No hex value may appear in any component. The token set:

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
- No ORM. Raw `sqlite3`, parameterised queries only. Never build SQL
  with f-strings or concatenation.
- **No machine-learning libraries in the prototype.** Detection is
  median, IQR, date arithmetic and rules. No scikit-learn, no model
  files, no LLM calls in the scoring path.
- **Determinism.** Running `checks.py` twice on the same database must
  produce identical `alerts`. That means `REFERENCE_DATE`, a fixed
  random seed in `generate_data.py`, and no `date.today()`.
- A check that cannot produce a human-readable `reason` may not award
  points.
- `checks.py` must never read `planted_anomaly`. The API must never
  return it.
- Thresholds and point caps live in `config.py`, never inline in
  `checks.py`.
- No `SELECT *` — name columns, so a schema change fails loudly.

### Language
- Never write "fraud", "scam", or "corrupt" in code, comments, or UI
  copy. Use "flagged", "needs verification", "risk indicator".
- The system scores works, MPs' *compliance*, and districts'
  *utilisation*. There is **no MP risk leaderboard** and no ranking of
  Members of Parliament by suspicion.

### Data access boundary
- Scrape only the public eSAKSHI dashboard, rate-limited, cached, with
  an identifiable user agent.
- **Never attempt to access the authenticated portion of eSAKSHI** — not
  with borrowed credentials, not by guessing endpoints. Unauthorised
  access to a government system is an offence.
- Work-level payments, progress and evidence are not public. The
  prototype demonstrates the logic on generated data; a deployment reads
  the Ministry's own.

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

```bash
python -m backend.evaluate
```
Recall must not drop below the previous step's number. Record it in the
spec's Definition of Done.

```bash
grep -rn "date.today\|datetime.now" backend/     # must be empty
grep -rni "sqlalchemy\|fraud\|scam\|corrupt" backend/   # must be empty
grep -rn "SELECT \*" backend/                    # must be empty
```

Then open the app and click the top alert. If you cannot explain out
loud why it scored what it scored, using only what is on screen, the
step is not done.

---

## Common mistakes to avoid

| Mistake | Why it hurts |
|---|---|
| Using `final_cost` without COALESCE | Silently drops every unfinished work — the risky ones |
| Forgetting `PRAGMA foreign_keys = ON` | Every FK in the schema becomes decorative |
| `date.today()` anywhere | Demo drifts, slide number stops matching the app |
| MP quota shortfall applied to each work | Flags every work that MP recommended |
| Peer group with 3 rows | A median of 3 is noise; one outlier defines "normal" |
| Reading `planted_anomaly` in checks | Accuracy number becomes fake, and a judge can catch it |
| Storing district as free text | Two spellings and role scoping breaks silently |
| Bare score in the UI | Kills the explainability story the project rests on |
| Word "scam" on screen | A hilly road legitimately costs more; you just accused someone |

---

## Before final submission

Re-verify against the current official MPLADS guidelines:

- ₹5 crore annual entitlement per MP. **Since 1 April 2023 this is
  released as a single annual instalment**, not two of ₹2.5 crore as
  applied up to FY 2022-23. Model both correctly if your dataset spans
  the change.
- 15% Scheduled Caste and 7.5% Scheduled Tribe area floors.
- The permitted and not-permitted work category lists.
- Treatment of interest earned on unspent funds — under the 2023
  revision interest is remitted to the Consolidated Fund of India and is
  no longer available for works.
- Sanction timelines for District Authorities.

The 2023 revision changed several provisions. A rule engine citing a
superseded clause is worse than no rule engine.