# MPLADS Risk Engine

Anomaly detection and monitoring platform for the Members of Parliament
Local Area Development Scheme. Smart India Hackathon, problem statement
26102 (MoSPI — Data Informatics & Innovation Division).

## What it does

Reads MPLADS works data, runs deterministic checks over every work, MP
and district, produces a 0–100 risk score with a written reason for each
point awarded, and shows officers a ranked list of subjects that need
verification — worst first.

## What it is not

It does not detect fraud. It flags subjects whose numbers deviate from
comparable ones and from scheme rules, so a human can verify them.
A costly road may be a hilly road.

It is also not a data-entry system. **eSAKSHI is the system of record.**
Implementing agencies and district authorities enter works there as part
of their existing workflow; this platform reads that data, scores it,
and pushes alerts back to the same authorities. We never create a
project record.

---

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install sqlalchemy fastapi uvicorn pandas faker pyjwt werkzeug \
            python-multipart openpyxl
cd frontend && npm install && cd ..

export JWT_SECRET="$(python -c 'import secrets;print(secrets.token_urlsafe(48))')"

python -m backend.db                # creates empty mplads.db
python -m backend.generate_data     # fills it, ~4500 works
python -m backend.checks            # scores everything
python -m backend.evaluate          # recall vs planted anomalies

uvicorn backend.main:app --reload --port 8000
cd frontend && npm run dev          # port 5173
```

`generate_data.py` drops and recreates everything. Always safe to
re-run. `checks.py` rebuilds `scores` and `alerts` only.

---

## Stack

| Layer | Choice |
|---|---|
| Database | **SQLite** — `backend/mplads.db`, committed to git |
| ORM | **SQLAlchemy 2.x** for schema, CRUD, auth, serialisation |
| Analytics | **`text()` with bound params** for peer-group queries in `checks.py` |
| Backend | FastAPI + uvicorn, Python 3.11+ |
| Auth | **JWT** (PyJWT), no session table |
| Passwords | werkzeug hashing |
| Data | `faker` — generated, not scraped |
| Frontend | React (Vite), plain JS, Recharts |
| Styling | Plain CSS + variables in `frontend/src/theme.css` |

No other data-access style. No string-formatted SQL anywhere.

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
│   ├── models.py              ← all 16 SQLAlchemy models
│   ├── db.py                  ← engine, FK pragma, sessions, init_db()
│   ├── generate_data.py       ← dummy data + planted anomalies + demo users
│   ├── checks.py              ← the checks and scoring
│   ├── auth.py                ← JWT, login, scope enforcement
│   ├── evaluate.py            ← recall against planted anomalies
│   ├── main.py                ← FastAPI, two routers
│   └── mplads.db
└── frontend/
    └── src/
        ├── theme.css
        ├── api.js
        ├── App.jsx
        ├── Login.jsx          ← one login, redirects by role
        ├── citizen/           ← citizen portal
        ├── officer/           ← worklist: district + state officer
        └── oversight/         ← read-only: mp + ministry
```

---

## Roadmap

Mark a step complete only when its Definition of Done passes.

| Step | Feature | Status |
|---|---|---|
| 01 | Project skeleton, config, database schema | ☑ |
| 02 | Dummy data generator with planted anomalies | ☑ |
| 03 | Detection checks and scoring | ☑ |
| 04 | API endpoints — two routers | ☐ |
| 05 | JWT login and scope enforcement | ☐ |
| 06 | Officer alert list | ☐ |
| 07 | Alert detail with evidence pack | ☐ |
| 08 | Accuracy evaluation script | ☐ |
| 09 | Ministry / State dashboards | ☐ |
| 10 | Citizen portal and complaint page | ☐ |
| 11 | CSV / Excel upload | ☐ |
| 12 | Demo seed data and polish | ☐ |

**Steps 01–08 are the minimum viable prototype.** Step 08 sits ahead of
the extra screens deliberately — the accuracy number is worth more than
another page.

---

## Critical: the reference date

Every date calculation reads `REFERENCE_DATE` from `backend/config.py`.

```python
REFERENCE_DATE = date(2026, 9, 15)   # pin this, never move it
```

**Never call `date.today()` or `datetime.now()` anywhere in `backend/`.**
Delay scores would drift daily, the demo would change overnight, and the
recall number on your slide would stop matching the app.

---

## Database schema

Sixteen tables. Defined in `backend/models.py`. Column order is
normative. Full rationale in
`.claude/specs/01-project-skeleton-schema.md`.

### Conventions

- **Dates are ISO-8601 strings**, typed `String` — not `Date`/`DateTime`.
  SQLite has no date type; ISO text sorts and compares correctly.
- **Money is `Integer` rupees.** No `Float` or `Numeric` for currency.
- **Booleans are `Integer` 0/1** with a CHECK constraint.
- **No real identity data.** PANs are hashes; names are generated.
- Every CheckConstraint must be declared explicitly — SQLAlchemy infers
  none of them from Python types.

### The foreign-keys pragma is mandatory

SQLAlchemy does **not** enable SQLite foreign keys, and `create_engine`
has no option for it. Without this listener every FK is decorative:

```python
@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, _):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()
```

### Group A — Reference data

**`states`** — `state_id · name · code`

**`districts`** — `district_id · state_id · name · is_hill_district ·
default_area_type` · UNIQUE(state_id, name)

**`constituencies`** — `constituency_id · state_id · name · house` ·
UNIQUE(state_id, name, house)

**`mps`** — `mp_id · full_name · house · constituency_id · state_id ·
term_start · term_end · is_active`

**`agencies`** — `agency_id · name · agency_type · district_id`
Implementing agencies — the government body running the work.

**`vendors`** — `vendor_id · name · district_id · pan_hash · address ·
registered_on · is_active`
Private contractors — the company that builds it. Distinct from
agencies: an agency tenders, a vendor executes.

`districts.is_hill_district` and `districts.default_area_type` are
**generation hints only**. Nothing in `checks.py` may read them; the
work's own `terrain` and `area_type` are the truth.

### Group B — Accounts and access

**`users`** — `user_id · username · password_hash · full_name · role ·
scope_type · scope_id · mp_id · is_active · created_at · last_login_at`

`role`: citizen / mp / district_officer / state_officer / ministry
`scope_type`: constituency / district / state / national

An MP is a *person in the scheme* (`mps`); a user is *a login*. Keep
them separate. `role` decides which actions are allowed; `scope_type` +
`scope_id` decides which rows are visible. Never conflate the two.

**Roles are provisioned, never self-declared.** There is no signup form
offering "district officer", and **no endpoint anywhere writes to
`users.role`**. Officer accounts would come from the Ministry, citizens
from Aadhaar-verified registration. In the prototype all accounts are
seeded by `generate_data.py`.

There is no `sessions` table — see Authentication below.

### Group C — Scheme records

**`allocations`** — `allocation_id · mp_id · fy · entitlement ·
released · spent · released_on` · UNIQUE(mp_id, fy)

SC/ST spend are **not** columns here. They are derived by summing
`works` where `is_sc_area = 1` / `is_st_area = 1`. Storing them twice
guarantees they disagree.

**`works`** — 27 columns, in this order:

| # | Column | Notes |
|---|---|---|
| 1 | work_id | PK |
| 2 | mp_id | FK |
| 3 | constituency_id | FK |
| 4 | district_id | FK |
| 5 | agency_id | FK, nullable pre-sanction |
| 6 | vendor_id | FK, nullable pre-award |
| 7 | fy | "2024-25" |
| 8 | work_type | road / bridge / hospital / borewell / … |
| 9 | description | free text, messy on purpose |
| 10 | terrain | plain / hilly / coastal |
| 11 | area_type | metro / urban / semi_urban / rural |
| 12 | quantity | see unit map |
| 13 | unit | km / count / sqm / beds |
| 14 | estimated_cost | INTEGER rupees |
| 15 | final_cost | NULL until completed |
| 16 | recommended_on | ISO date |
| 17 | sanctioned_on | nullable |
| 18 | expected_completion_on | nullable — stored, not computed |
| 19 | completed_on | nullable |
| 20 | status | recommended / sanctioned / in_progress / completed |
| 21 | progress_pct | 0–100, may be stale |
| 22 | last_updated_on | ISO date — staleness signal |
| 23 | lat | |
| 24 | lon | |
| 25 | is_sc_area | 0/1 |
| 26 | is_st_area | 0/1 |
| 27 | planted_anomaly | ground truth, NULL for clean rows |

**Costs are compared in constant prices.** `checks.py` deflates every
unit cost by `COST_INDEX[fy]` before comparing peers, because the peer
ladder has no year dimension and a recent work would otherwise look
expensive purely for being recent. The index is a published economic
fact — a deployment reads the WPI construction series — which is why
`checks.py` may read it where it may never read `BASE_UNIT_COST`.

**Cost convention:** always `COALESCE(final_cost, estimated_cost)`.
Never `final_cost` alone — it is NULL for every unfinished work, which
would silently exclude exactly the works most likely to be problems.

**`terrain` and `area_type` are independent axes** and both live on the
work, not the district. Mumbai is coastal *and* metro; Shimla is hilly
*and* urban. A district like Pune contains both a metro core and rural
talukas — tagging the district would make a flat road inherit "hilly"
and excuse a genuinely overpriced work.

**There is deliberately no separate table** for metro cities, hill
areas, or per-work-type assets. Those are column values. Separate tables
multiply combinatorially, and per-type tables would force the detection
code to be rewritten per type and make cross-type queries impossible.
Adding a new category is one line in `config.py`.

**Units by work_type** — a peer group is always one work_type, so units
never mix:

| work_type | unit |
|---|---|
| road, drain | km |
| borewell, streetlight | count |
| community_hall, school_wall | sqm |
| hospital | beds |

`planted_anomaly` exists only so `evaluate.py` can measure recall. It
must never be read by `checks.py` and never returned by the API.

**`payments`** — `payment_id · work_id · vendor_id · tranche_no ·
amount · paid_on · progress_pct_at_payment · voucher_ref` ·
UNIQUE(work_id, tranche_no)

**`progress_updates`** — `update_id · work_id · progress_pct ·
reported_on · reported_by · note`

The *history*, not just the current value. A falsified progress number
is hard to spot; a jump from 20 to 90 in one day, or a whole history
entered on one afternoon, is not.

**`evidence`** — `evidence_id · work_id · kind · file_path ·
photo_hash · exif_lat · exif_lon · stage · captured_at · uploaded_at`

`kind`: photo / completion_cert / handover / utilisation_cert.
**The absence of rows here is itself the signal.**

### Group D — System output

**`scores`** — 15 columns. One row per subject, for **every** subject —
a clean work scoring 3 gets a row exactly as a flagged one scoring 78.
This is what lets the citizen listing and the officer worklist read from
the same place.

`score_id · subject_type · subject_id · total_score · cost_points ·
delay_points · compliance_points · duplicate_points · public_points ·
evidence_points · utilisation_points · reasons_json · checks_run ·
checks_skipped · scored_on` · UNIQUE(subject_type, subject_id)

Per-check columns exist so they are **queryable** — "which districts
have a delay problem specifically" is a `GROUP BY`, and the dashboard's
flags-by-type chart needs no JSON parsing. `reasons_json` carries the
sentences; the columns carry the numbers.

`reasons_json` shape, fixed:

```json
[
  {
    "check": "C1",
    "points": 31,
    "reason": "Cost per km is ₹8.4 lakh against a hilly-metro median of ₹2.0 lakh (4.2×).",
    "evidence": { "value": 840000, "median": 200000, "ratio": 4.2,
                  "peer_count": 47, "peer_level": "work_type+terrain+area_type" }
  }
]
```

`reason` is what the UI prints. `evidence` is what charts read. The
frontend must never recompute a number that is not in `evidence`.

**`alerts`** — a thin workflow record pointing at a score. Created only
when `total_score >= 25`.

`alert_id · score_id (FK, unique) · severity · status · verdict ·
resolution_note · snoozed_until · assigned_to · created_at · resolved_at`

`verdict` and `resolution_note` are **required** when `status` becomes
`resolved` — enforced in the API. An officer must not be able to clear a
₹31 lakh alert with a bare "visited" button; closing an alert has to
record what was found. `snoozed_until` is the honest alternative to a
dismiss button: the alert returns instead of disappearing.

**`complaints`** — `complaint_id · work_id · user_id · text ·
photo_path · lat · lon · verified · verified_by · created_at` ·
UNIQUE(work_id, user_id)

One complaint per citizen per work. That constraint is what makes C6's
distinct-reporter count meaningful and stops one person inflating a
score.

### Group E — Accountability

**`audit_log`** — `log_id · user_id · action · subject_type ·
subject_id · detail · created_at`

Every state-changing action taken **inside this app** — logins, alert
actions, complaints, check runs. Not government-side actions; those live
in eSAKSHI. Append-only: nothing may UPDATE or DELETE from it. It
matters more now that there is no session table to cross-reference.

### Polymorphic columns

`users.scope_id`, `scores.subject_id` and `audit_log.subject_id` are
**deliberately not ForeignKeys** — their target table varies by row.
`scores.subject_type` is one of work / mp / district / **vendor**.

**Never join on `subject_id` without first filtering `subject_type`.**
This fails silently rather than erroring:

```python
# WRONG — a district-level score with subject_id = 3
#         silently matches work_id = 3
.join(Work, Work.work_id == Score.subject_id)

# RIGHT — filter and join belong together, always
.filter(Score.subject_type == "work")
.join(Work, Work.work_id == Score.subject_id)
```

Keep them in one shared helper so they cannot be separated.

### Indexes

```
idx_works_peer         works(work_type, terrain, area_type, district_id)
idx_works_mp           works(mp_id, fy)
idx_works_district     works(district_id, status)
idx_works_constituency works(constituency_id)
idx_payments_work      payments(work_id)
idx_progress_work      progress_updates(work_id, reported_on)
idx_evidence_work      evidence(work_id, kind)
idx_evidence_hash      evidence(photo_hash)
idx_scores_subj        scores(subject_type, subject_id)
idx_scores_total       scores(subject_type, total_score DESC)
idx_alerts_open        alerts(status, severity)
idx_complaints_work    complaints(work_id, verified)
```

Three are load-bearing: `idx_works_peer` (column order matches the peer
ladder, so each rung is a prefix), `idx_scores_total` (the worklist
sort), `idx_evidence_hash` (the reused-photo self-join).

---

## Authentication

**JWT, no session table.** On login the server issues a token carrying
`sub` (user_id, as a **string** — PyJWT rejects an integer `sub`),
`role`, `scope_type`, `scope_id`, `exp` (12 hours). Every request
decodes it and derives the query filter from the claims — no database
lookup needed.

The signing secret comes from the `JWT_SECRET` environment variable,
must be at least 32 bytes, and never appears in the repository.

### Login

The login screen may offer a role selector, but **the server ignores it
as a claim and uses it only as an extra filter**:

```sql
WHERE username = ? AND role = ? AND is_active = 1
```

Then verify the password hash. A citizen picking "District Officer"
matches no row and login fails. Return a generic "invalid credentials"
regardless of which part failed.

### What stateless costs

A JWT cannot be revoked, so logout only deletes the client's copy and
`is_active = 0` does not take effect until expiry. Mitigate by
re-checking `users.is_active` and `role` on **state-changing actions**
(acknowledge / escalate / resolve) while trusting the token alone on
reads — the worklist loads on every page view and does not deserve a DB
hit.

The honest answer if asked: *"The token is signed, so role and scope
can't be forged. For state-changing actions we re-verify the account is
still active — that closes the gap where a stateless token outlives a
revoked user. Production would add a revocation list."*

### Scope enforcement

`scope_type` + `scope_id` come from the verified token and are applied
in **one shared dependency** that every scoped route depends on.

- Never filter by scope in the frontend. Data that reached React has
  already left the server.
- Never accept a district, state or constituency id from the client. A
  route taking `?district_id=` lets an officer type someone else's.
- Never write the `WHERE` per route. One route will be missed.

---

## Roles

| Action | citizen | mp | district_officer | state_officer | ministry |
|---|:--:|:--:|:--:|:--:|:--:|
| Browse works in scope | ✅ | ✅ | ✅ | ✅ | ✅ |
| See risk score and reasons | ❌ | ✅ | ✅ | ✅ | ✅ |
| File a complaint | ✅ | ❌ | ❌ | ❌ | ❌ |
| Verify a complaint | ❌ | ❌ | ✅ | ✅ | ❌ |
| Acknowledge / escalate / resolve / snooze | ❌ | ❌ | ✅ | ✅ | ❌ |
| National dashboard | ❌ | ❌ | ❌ | ❌ | ✅ |
| Upload data | ❌ | ❌ | ✅ | ✅ | ✅ |

**Only District and State officers act on alerts.** MPs and the Ministry
are view-only, and this is not arbitrary: under the scheme an MP
*recommends* works while the District Authority sanctions, executes and
verifies them. A platform letting an MP close an alert on their own
constituency's work would invert the accountability the scheme rests on.

### Alert routing

Follows `scores.subject_type`:

| Score subject | Lands on |
|---|---|
| work | District Officer's worklist |
| mp (quota shortfall) | **State Officer's** worklist |
| district (utilisation) | **State Officer's** worklist |
| vendor (pricing conduct) | District Officer's worklist |

Never send an alert about someone only to that same person. A district
officer must not be the sole recipient of an alert saying his own
district is underspending.

---

## Scoring

Each check returns `{check, points, reason, evidence}`. Points are
summed per subject and clamped to 0–100.

**Checks run at three levels. Do not mix them.** Awarding an MP's quota
shortfall to each of their works would flag every work that MP ever
recommended — a false-positive machine.

### Work-level — `subject_type = 'work'`

| Check | Max | Rule |
|---|---|---|
| **C1 cost outlier** | 35 | Unit cost = `COALESCE(final_cost, estimated_cost) / quantity` against the peer-group median. Past the upper IQR fence (Q3 + 1.5·IQR): at fence → 10, 2× median → 20, 3× → 28, 4×+ → 35. |
| **C2 delay** | 25 | `REFERENCE_DATE − sanctioned_on` while not completed. 180–364 → 10, 365–539 → 18, 540+ → 25. |
| **C2b predicted stall** | 8 | Not yet late but on track to be: progress below expected-for-elapsed-time and no update in 90 days. This is the PS's "early warning". |

**C1 is fence-first, then banded.** The IQR fence is the gate and the
ratio table is the scale. A work that does not clear `Q3 + 1.5·IQR`
scores zero on C1 **even if it is above 2× the median** — in a tightly
clustered peer group 2× can still be ordinary. Once it clears the fence,
award the higher of 10 and whatever the ratio band gives. Never award
ratio points to a work inside the fence; that is how a peer group of
cheap borewells starts flagging half of itself.

**C2 and C2b are mutually exclusive.** Both write into
`scores.delay_points`, so a very overdue work that is also stale and
behind schedule would otherwise be charged twice for one problem.
Evaluate C2 first; **if C2 awards anything, C2b does not run.** C2b is
for works that are *not yet* late — that is the whole point of calling
it an early warning. Enforce this in `checks.py` with an explicit
`if c2_points == 0:` guard, not by hoping the conditions never overlap.
| **C3 work compliance** | 15 | Highest of: `completed_on` before `sanctioned_on`; `sanctioned_on` before `recommended_on`; a date in the future; work outside the MP's term; work_type or description in the not-permitted list. Do not stack. |
| **C5 duplicate** | 20 | Same district, same work_type, unit cost within 10%, sanctioned within 60 days. Alerts **both** works, each naming the other. |
| **C6 citizen reports** | 15 | Distinct `verified = 1` complaints. 1 → 5, 2–3 → 10, 4+ → 15. Hard cap. |
| **C7 ghost asset risk** | 35 | Payment ratio exceeds progress ratio by >0.20 → 10, >0.35 → 18, >0.50 → 25. Completed with zero evidence rows → 15. No `last_updated_on` change in 180 days while payment ratio > 0.5 → 12. Implausibly fast completion → 12. `photo_hash` matching another work → 20. Sum, capped. |

### MP-level — `subject_type = 'mp'`

| Check | Max | Rule |
|---|---|---|
| **C3-MP quota** | 25 | SC-area spend below 15% of released funds → up to 15, scaled by shortfall. ST-area below 7.5% → up to 10. These stack. |

### District-level — `subject_type = 'district'`

| Check | Max | Rule |
|---|---|---|
| **C4 utilisation** | 15 | `spent / released` behind where the calendar says it should be → 10. Over 60% of the year's spend in Jan–Mar → 8. Stack, cap 15. |

### Vendor-level — `subject_type = 'vendor'`

| Check | Max | Rule |
|---|---|---|
| **C8 vendor conduct** | 30 | Median unit cost ≥ 1.6× the work_type median over ≥ 4 works → 16. ≥ 60% of a district's works of one type → 8. ≥ 40% of their works already flagged → 10. ≥ 45% of a district's payments → 8. Sum, capped. |

Scored against the **vendor**, never against their works — charging it
per-work would flag every contract that vendor ever won, exactly as
awarding an MP's quota shortfall per-work would. No single component
reaches the alert threshold on its own: a vendor may hold most of a
small district's work simply because few firms bid there.

Measure utilisation **against the calendar**, not raw unspent balance.
Under the single-annual-release model funds sit in a nodal account and
are drawn down as needed, so low spend early in the year is normal.

### Peer group for C1

Try in order, stop at the first with at least `PEER_GROUP_MIN_ROWS` (8):

1. `work_type + terrain + area_type + district_id`
2. `work_type + terrain + area_type + state_id`
3. `work_type + terrain + area_type`
4. `work_type + area_type`
5. `work_type`

`area_type` is given up **after** district deliberately — urbanisation
explains more cost variance than geography.

If even the last rung has fewer than 8 rows, **skip C1, award zero, and
record it in `checks_skipped`.** Store the rung in `evidence.peer_level`
so the UI can say "compared against 47 hilly metro roads".

**Dataset consequence:** three dimensions plus district makes rung 1
small. `generate_data.py` must produce **4,000–5,000 works**; most
comparisons land on rung 3.

### Expected duration

Keyed by `(work_type, area_type)`, not work type alone. A metro road
takes longer for permissions and utility shifting, not construction;
treating them the same makes every metro work look delayed.

### Baseline costs live in config, not in the generator

`generate_data.py` needs a realistic "normal" cost before it can plant a
work at 4× normal, and `evaluate.py` needs to know what normal was. So
the cost model is `BASE_UNIT_COST[work_type]` with
`AREA_COST_MULTIPLIER[area_type]` and `TERRAIN_COST_MULTIPLIER[terrain]`
in `config.py` — never hardcoded inside the generator.

`checks.py` must **not** read these tables. Detection compares a work
against its actual peers in the data, never against a constant we chose;
scoring against our own generation baseline would be marking our own
homework and the recall number would mean nothing.

### Graceful degradation

Every check declares the fields it needs. If a field is absent the check
**skips and records why** in `checks_skipped` — it must not crash and
must not silently score zero. The alert page then shows *"5 of 8 checks
ran; payment-progress and evidence checks require authenticated eSAKSHI
data."*

### Severity bands

| Score | Severity | Token |
|---|---|---|
| 70–100 | critical | `--sev-critical` |
| 45–69 | high | `--sev-high` |
| 25–44 | medium | `--sev-medium` |
| 0–24 | — | score row written, no alert |

---

## Planted anomalies

`generate_data.py` plants these, writing the label into
`planted_anomaly`. `evaluate.py` measures recall per label.

| Label | Count | What it looks like |
|---|---|---|
| `cost_overrun` | 60 | Unit cost 3–6× the peer median |
| `long_delay` | 80 | Sanctioned 400–700 days ago, unfinished |
| `impossible_date` | 20 | `completed_on` before `sanctioned_on` |
| `ineligible_work` | 20 | work_type from the not-permitted list |
| `duplicate_pair` | 40 (20 pairs) | Near-identical twin within 60 days |
| `payment_ahead_of_work` | 40 | Payment ratio 0.75–0.95, progress 0.10–0.30 |
| `ghost_asset` | 30 | Marked complete, no evidence, fully paid |
| `quota_shortfall` | 4 MPs | SC spend forced under 15% |

~290 planted out of ~4,500. Everything else must be clean — if clean
rows trip checks, the false-positive rate is real and you loosen
thresholds rather than hide it.

Generate some works with `progress_pct = 0` and empty
`progress_updates` on purpose, so the graceful-degradation path is
exercised by the data, not just by intention.

`evaluate.py` reports per label: planted, caught, recall — plus one
overall false-positive rate.

---

## Frontend

### Two portals, one database

`/citizen/*` and `/officer/*` are separate FastAPI routers with
different auth dependencies, and separate page sets in React. They read
the **same `mplads.db`** — never two databases. Separate routers make
the citizen restriction structural: the citizen router has no code path
that selects `total_score`, so it cannot leak one.

### Three portals, not five

Five roles, but only **three home screens**. Group by *what a role can
do*, never by seniority — two roles with identical permissions share a
page, and two roles that differ on whether action buttons exist must
not.

| Portal | Roles | Why together |
|---|---|---|
| **Citizen** `/citizen` | citizen | Never sees a score |
| **Worklist** `/officer` | district_officer, state_officer | **Identical permissions** — only scope differs, and scope comes from the token |
| **Oversight** `/oversight` | mp, ministry | See scores, cannot act on anything |

District and State Officer match on every row of the permission matrix
above. The state officer's extra content — MP-quota and
district-utilisation alerts — is not a different page, it is the same
worklist holding more subject types, which `SUBJECT_ROUTING` already
produces. So the State Officer view costs almost nothing on top of the
District Officer view.

Within Oversight the shell is shared and the widgets differ by scope:

- **MP** — constituency works, SC/ST quota meter against the 15% and
  7.5% floors, unspent balance, stalled works. Framed as assistance,
  not audit.
- **Ministry** — national league tables and trend over time. They do not
  read individual works.

Neither renders an action button anywhere.

### Three portals, two routers

Page count and router count are **different questions.** Do not add a
third router to match the third portal.

`/citizen/*` is a separate router because the guarantee *"this router
cannot leak a risk score"* must be provable by the **absence of code** —
no code path selects `total_score`, so a leak requires someone to add
the field deliberately. MPs and Ministry users legitimately see scores,
so there is no such guarantee to protect for them; their restriction is
on **writes**, and `require_role(*ALERT_ACTOR_ROLES)` on the four action
endpoints enforces it with a 403. A third router would add files without
adding safety.

### One login, redirect by role

One login page, one `/auth/login` endpoint. The role dropdown remains a
**filter, not a claim**. On success the frontend reads `user.role` from
the response and redirects:

```js
const PORTAL = {
  citizen:          "/citizen",
  district_officer: "/officer",
  state_officer:    "/officer",
  mp:               "/oversight",
  ministry:         "/oversight",
};
```

Three login endpoints would mean getting the timing-attack fix, the
lockout counter and the audit write right in three places instead of
one.

**That map is convenience, not security.** A route guard bounces an MP
who deep-links `/officer` so they do not see a broken page — but the
enforcement is that every API call still returns 403. Never let a
frontend redirect be the reason data is safe.

### Citizens see facts, not scores

A citizen sees cost, dates, status, contractor, photos, location — but
never `total_score` or the reasons. A work showing "Risk 78" publicly,
before any officer has verified it, is an accusation the system is not
entitled to make.

**Delay is a fact, not a score.** "Expected by 16 Jan 2026, still in
progress — 242 days overdue" is arithmetic on two fields the citizen can
already see. Show it plainly; hiding it makes the page less honest, not
more careful. This is why `expected_completion_on` is stored.

Contractor names are public record and may be shown. **Never show a
contractor name beside a risk score on a public page.**

### CSS

No hex value in any component. Tokens in `theme.css`:

```
--bg  --surface  --surface-2  --border
--text  --text-muted  --text-faint
--accent  --accent-soft
--sev-critical  --sev-critical-bg
--sev-high  --sev-high-bg
--sev-medium  --sev-medium-bg
--ok  --ok-bg
--radius  --shadow
```

Light on `:root`; dark under both `@media (prefers-color-scheme: dark)`
and `[data-theme="dark"]`.

### Rules

- The alert list is the officer portal's **home screen**. Not a tab.
- **Every score is shown with its reasons.** A bare number is never
  displayed alone — not in a table cell, not in a tooltip.
- All fetch calls live in `api.js`. No `fetch()` inside a component.
- Loading and empty states required on every page.
- Prefer a persistent priority banner over a modal popup for the top
  alert. Modals get dismissed reflexively and block the task the officer
  came to do. If a modal is used, once per day, top 3 together, and
  every button a real action — never a bare dismiss.

---

## Rules

### Data and detection
- SQLAlchemy 2.x ORM for schema/CRUD/auth; `text()` with bound params
  for analytics. No other style.
- **No string-formatted SQL, ever.** Named parameters only.
- **No ML libraries in the prototype.** Median, IQR, date arithmetic,
  rules. No scikit-learn, no model files, no LLM calls in the scoring
  path.
- **Determinism.** Running `checks.py` twice on the same data must
  produce identical scores. That means `REFERENCE_DATE`, a fixed random
  seed in `generate_data.py`, and no `date.today()`.
- A check that cannot produce a human-readable `reason` may not award
  points. A check that cannot run must record why.
- `checks.py` must never read `planted_anomaly`,
  `districts.is_hill_district`, or `districts.default_area_type`.
- Thresholds and point caps live in `config.py`, never inline.
- No `SELECT *`, no bare `.all()` on a full table.

### Language
- Never write "fraud", "scam", or "corrupt" in code, comments, or UI.
  Use "flagged", "needs verification", "risk indicator".
- The system scores works, MPs' *compliance*, and districts'
  *utilisation*. There is **no MP risk leaderboard**.

### Data access boundary
- Scrape only the **public** eSAKSHI dashboard — rate-limited, cached,
  identifiable user agent.
- **Never attempt the authenticated portion of eSAKSHI.** Not with
  borrowed credentials, not by guessing endpoints. Unauthorised access
  to a government system is an offence.
- Work-level payments, progress and evidence are not public. The
  prototype demonstrates the logic on generated data; a deployment reads
  the Ministry's own.
- Real district, constituency and MP names may be copied from the public
  dashboard to make the dataset credible.

### Git
- One feature branch per roadmap step: `feature/<slug>`.
- Commit `mplads.db` so the team sees identical data.
- Never commit to `main` directly. Never commit `JWT_SECRET`.

---

## How to verify your work

```bash
python -m backend.generate_data && python -m backend.checks
python -m backend.checks          # run twice
```
The second run must produce the same alert count and top-10 scores.

```bash
python -m backend.evaluate        # recall must not drop
grep -rn "date.today\|datetime.now" backend/          # empty
grep -rni "fraud\|scam\|corrupt" backend/             # empty
grep -rn "SELECT \*" backend/                         # empty
```

Then open the app and click the top alert. If you cannot explain out
loud why it scored what it scored, using only what is on screen, the
step is not done.

---

## Common mistakes to avoid

| Mistake | Why it hurts |
|---|---|
| `final_cost` without COALESCE | Silently drops every unfinished work — the risky ones |
| Forgetting `PRAGMA foreign_keys = ON` | Every FK becomes decorative |
| Joining `subject_id` without filtering `subject_type` | An MP alert renders as a work alert. Fails silently |
| `date.today()` anywhere | Demo drifts; the slide stops matching the app |
| MP quota applied to each work | Flags every work that MP recommended |
| Peer group with 3 rows | A median of 3 is noise |
| Reading `planted_anomaly` in checks | Accuracy number becomes fake; a judge can catch it |
| Terrain on the district, not the work | A flat road in a hill district gets excused |
| Filtering scope in the frontend | Data already left the server |
| A third router to match the third portal | Files without safety — the router split protects score exposure, not page count |
| Grouping portals by seniority | Puts an actor (state officer) beside watchers; action buttons appear where they must not |
| Bare score in the UI | Kills the explainability the project rests on |
| "Scam" on screen | A hilly road legitimately costs more |
| Letting C2 and C2b both fire | One delay charged twice in `delay_points` |
| C1 ratio points without clearing the fence | A tight peer group flags half of itself |
| `checks.py` reading `BASE_UNIT_COST` | Scoring against our own generator = fake recall |

---

## Demo notes

- Log in as `do.pune` → alerts. Log out, `do.nashik` → different list.
  Paste Pune's alert URL into Nashik's session → **403**. Ten seconds,
  and access control is proven rather than described.
- Show the State Officer once — the MP-quota and district-utilisation
  alerts he gets that the district officer does not.
- Excel upload answers "how does this connect to eSAKSHI?" in five
  seconds. Click it.
- Close on the recall number.
- Nothing new is built on the last day: evaluation and rehearsal only.
  Record a backup video.

---

## Before final submission

Re-verify against the current official MPLADS guidelines:

- ₹5 crore annual entitlement per MP. **Since 1 April 2023 released as a
  single annual instalment**, not two of ₹2.5 crore as applied up to
  FY 2022-23. Model both correctly if the dataset spans the change.
- 15% Scheduled Caste and 7.5% Scheduled Tribe area floors.
- The permitted and not-permitted work category lists.
- Interest on unspent funds — under the 2023 revision it is remitted to
  the Consolidated Fund of India and no longer available for works.
- Sanction timelines for District Authorities, and any minimum share of
  works the District Authority must physically inspect. If you can quote
  the real inspection quota and show the system prioritising which works
  fill it, that is a strong slide.

The 2023 revision changed several provisions. A rule engine citing a
superseded clause is worse than no rule engine.