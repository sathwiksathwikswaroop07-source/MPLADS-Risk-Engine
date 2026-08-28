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
pip install fastapi uvicorn pandas faker python-multipart openpyxl
cd frontend && npm install && cd ..

# build the database from scratch
python -m backend.generate_data     # creates mplads.db, ~2000 works
python -m backend.checks            # scores everything, fills alerts
python -m backend.evaluate          # prints recall vs planted anomalies

# run
uvicorn backend.main:app --reload --port 8000
cd frontend && npm run dev          # port 5173
```

`generate_data.py` drops and recreates all tables. It is always safe to
re-run. `checks.py` deletes and rebuilds the `alerts` table only.

---

## Stack

| Layer | Choice | Notes |
|---|---|---|
| Database | SQLite (`backend/mplads.db`) | Single file, committed to git |
| Backend | FastAPI + uvicorn | Python 3.11+ |
| DB access | Raw `sqlite3` | No ORM, ever |
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
│   ├── config.py              ← REFERENCE_DATE, thresholds, point caps
│   ├── db.py                  ← schema + connection + query helpers
│   ├── generate_data.py       ← builds mplads.db with planted anomalies
│   ├── checks.py              ← the six checks + scoring
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
| 01 | Project skeleton, config, database schema | ☐ |
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

Defined in `backend/db.py`. Do not change a column without updating
this section in the same commit.

### works
| Column | Type | Notes |
|---|---|---|
| work_id | INTEGER PK | |
| mp_name | TEXT | |
| constituency | TEXT | |
| district | TEXT | |
| state | TEXT | |
| work_type | TEXT | see permitted list below |
| description | TEXT | free text, messy on purpose |
| terrain | TEXT | plain / hilly / coastal |
| quantity | REAL | see units table below |
| unit | TEXT | km / count / sqm |
| estimated_cost | INTEGER | rupees |
| final_cost | INTEGER | rupees, NULL until completed |
| sanctioned_on | TEXT | ISO date |
| completed_on | TEXT | ISO date, NULL if unfinished |
| status | TEXT | recommended / sanctioned / in_progress / completed |
| agency | TEXT | implementing agency |
| vendor_id | INTEGER | FK vendors |
| fy | TEXT | e.g. "2024-25" |
| is_sc_area | INTEGER | 0 or 1 |
| is_st_area | INTEGER | 0 or 1 |
| planted_anomaly | TEXT | ground-truth label, NULL for clean rows |

**Cost to use in checks:** always `COALESCE(final_cost, estimated_cost)`.
Never `final_cost` alone — it is NULL for every unfinished work, which
would silently exclude exactly the works most likely to be problems.

**Units by work_type** — a peer group is always a single work_type, so
units never mix:

| work_type | unit | quantity means |
|---|---|---|
| road | km | length |
| drain | km | length |
| borewell | count | number sunk |
| streetlight | count | poles installed |
| community_hall | sqm | built-up area |
| school_wall | sqm | wall area |

`planted_anomaly` exists only so `evaluate.py` can measure recall.
It must never be read by `checks.py` and never returned by the API.

### vendors
`vendor_id PK · name · district · registered_on`

### allocations
One row per MP per financial year.

`mp_name · fy · entitlement · released · spent`

SC and ST spend are **not** stored here — they are derived by summing
`works` where `is_sc_area = 1` / `is_st_area = 1` for that MP and year.
Storing them twice guarantees they will disagree.

### alerts
An alert can be about a work, an MP, or a district. Do not assume
`work_id`.

| Column | Notes |
|---|---|
| alert_id | INTEGER PK |
| subject_type | work / mp / district |
| subject_id | work_id, mp_name, or district name |
| risk_score | 0–100 |
| severity | critical / high / medium |
| reasons_json | see shape below |
| status | open / acknowledged / escalated / resolved |
| verdict | NULL / substantiated / not_substantiated |
| created_at | ISO datetime |

`reasons_json` is a JSON array. Every entry has exactly these keys:

```json
[
  {
    "check": "C1",
    "points": 31,
    "reason": "Cost per km is ₹8.4 lakh against a district median of ₹2.0 lakh for hilly roads (4.2×).",
    "evidence": { "value": 840000, "median": 200000, "ratio": 4.2, "peer_count": 47 }
  }
]
```

`reason` is what the UI prints. `evidence` is what charts read. The
frontend must never recompute a number that is not in `evidence`.

### complaints
| Column | Notes |
|---|---|
| complaint_id | INTEGER PK |
| work_id | FK works |
| text | TEXT |
| photo_path | TEXT, nullable |
| lat, lon | REAL, nullable |
| reporter_hash | TEXT — one complaint per reporter per work |
| verified | INTEGER 0/1 — only verified rows count toward C6 |
| created_at | ISO datetime |

### Indexes
```sql
CREATE INDEX idx_works_peer  ON works(work_type, district, terrain);
CREATE INDEX idx_works_mp    ON works(mp_name, fy);
CREATE INDEX idx_alerts_subj ON alerts(subject_type, subject_id);
```

---

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
| **C6 citizen reports** | 15 | Count of `verified = 1` complaints with distinct `reporter_hash`. 1 → 5, 2–3 → 10, 4+ → 15. Hard cap. |

### Peer group for C1

Try in this order and stop at the first group with **at least 8 rows**:

1. `work_type + district + terrain`
2. `work_type + state + terrain`
3. `work_type + terrain`
4. `work_type`

If even the last has fewer than 8 rows, **skip C1 and award zero** —
do not guess. Record the peer level used in `evidence.peer_level` so the
UI can say "compared against 47 hilly roads in this district".

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
- No ORM. Raw `sqlite3` with parameterised queries only. Never build SQL
  with f-strings or string concatenation.
- **No machine-learning libraries in the prototype.** Detection is
  median, IQR, date arithmetic and rules. No scikit-learn, no model
  files, no LLM calls in the scoring path.
- **Determinism.** Running `checks.py` twice on the same database must
  produce byte-identical `alerts`. That means: `REFERENCE_DATE`, a fixed
  random seed in `generate_data.py`, and no `date.today()`.
- A check that cannot produce a human-readable `reason` string may not
  award points.
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
| `date.today()` anywhere | Demo drifts, slide number stops matching the app |
| MP quota shortfall applied to each work | Flags every work that MP recommended |
| Peer group with 3 rows | A median of 3 is noise; one outlier defines "normal" |
| Reading `planted_anomaly` in checks | Your accuracy number becomes fake and a judge can catch it |
| Bare score in the UI | Kills the explainability story the whole project rests on |
| Word "scam" on screen | A hilly road legitimately costs more; you just accused someone |

---

## Before final submission

Re-verify against the current official MPLADS guidelines:

- ₹5 crore annual entitlement per MP, released in two instalments
- 15% Scheduled Caste and 7.5% Scheduled Tribe area floors
- The permitted and not-permitted work category lists
- Treatment of interest earned on unspent funds

The 2023 revision changed several provisions. A rule engine citing a
superseded clause is worse than no rule engine.