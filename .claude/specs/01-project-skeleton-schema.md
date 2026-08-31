# Spec: Project Skeleton, Config And Database Schema

## Overview

This step lays the foundation every later step reads from: the folder
layout, a single `config.py` holding `REFERENCE_DATE` together with
every threshold and point cap, and `models.py` + `db.py` holding the
complete SQLAlchemy schema, engine and session plumbing. Nothing is
detected and nothing is served over HTTP yet — the deliverable is an
empty, correctly-shaped `mplads.db` that step 02 can fill and step 03
can score.

It comes first because the generator, the checks, the API and the login
all depend on exact table and column names. Changing any of them once
data exists means regenerating everything, so the schema is defined once
here, in full, including tables that stay empty until later steps.

**This spec supersedes the "Database schema" section of CLAUDE.md.**
Updating CLAUDE.md to match is part of this step's Definition of Done.

> **Amended by `01b-work-type-granularity.md`.** Three things below are
> now out of date, and 01b is the authority on them:
>
> - `works` has **28** columns, not 27 — `specification` at 27,
>   `planted_anomaly` at 28. `area_type` (11) and
>   `expected_completion_on` (18) are unchanged.
> - `work_type` has **15** values, not 8 (roads split by lane, bridges
>   by span class, hospitals by tier, and so on).
> - `unit` allows **`m`** as well as km / count / sqm / beds; bridges
>   are measured in metres.
>
> Everything else here still stands. Read 01b for the reasoning — it is
> kept separate rather than merged so the *why* survives.

### Decisions carried into this revision

Four things changed since the previous draft. Each is a deliberate call,
recorded here so nobody reverts it by accident.

**1. SQLAlchemy 2.x ORM over SQLite**, reversing the earlier "no ORM"
rule. The team is already fluent in SQLAlchemy, and familiarity is worth
more over a seven-day sprint than the marginal transparency of
hand-written DDL. The split is: **ORM** for schema, CRUD, auth and
serialisation; **`text()` with bound parameters** for the analytical
queries in `checks.py`, where peer-group aggregates read more clearly as
SQL. Neither half uses string-formatted SQL.

**2. JWT replaces the server-side session table.** The team knows JWT
well. `role`, `scope_type` and `scope_id` travel inside the token, so a
request needs no database lookup to know who is asking. The `sessions`
table is **dropped**. See the *Authentication* note below for what this
costs.

**3. Scores are separated from alerts.** A score is a *measurement* —
every work, MP and district has one, including clean subjects scoring 3.
An alert is a *workflow item* — created only when a score crosses a
threshold, and carrying status, assignee and verdict. Jamming them into
one table left clean works with no score anywhere, which broke the
citizen-facing project listing. They are now two tables, and the
per-check point columns on `scores` make the dashboard's "flags by type"
charts a plain `GROUP BY` instead of JSON parsing.

**4. `works.area_type` joins `works.terrain`.** Terrain and urbanisation
are independent axes: Mumbai is coastal *and* metro; Shimla is hilly
*and* urban. A metro road legitimately costs more than a rural one —
land, labour, utility shifting, traffic-window working — so comparing
them produces false positives. Both live on the **work**, not the
district, because a district like Pune contains both a metro core and
rural talukas. `districts.is_hill_district` survives only as a default
hint when generating data.

There is deliberately **no** separate table for metro cities, hill
areas, or per-work-type assets (roads, bridges, hospitals). Those are
column *values*, not entities. Separate tables would multiply
combinatorially — a hilly metro needs a third table — and per-type
tables would require the detection code to be rewritten for each type
and make cross-type queries impossible. One `works` table with
`work_type`, `terrain` and `area_type` covers every case, and adding a
new category becomes one line in `config.py`.

## Depends on

Nothing. This is the first roadmap step.

## API endpoints

No API changes. `backend/main.py` arrives in step 04.

## Database changes

This step creates the entire schema from nothing. `backend/models.py`
does not exist yet, so there is nothing to verify against — this spec
defines what it will contain.

**Sixteen tables** in five groups. Column order below is normative: the
Definition of Done checks `PRAGMA table_info` against it, and SQLAlchemy
emits columns in declaration order, so declare them in this order.

---

### Group A — Reference data (geography and people)

These are looked up constantly and referenced by ID everywhere else.
Storing `district` as free text on every work makes district filtering
and role scoping unreliable the first time a name is spelled two ways.

#### `states` → `State`
| # | Column | SQLAlchemy | Notes |
|---|---|---|---|
| 1 | state_id | `Integer, primary_key=True` | |
| 2 | name | `String, nullable=False, unique=True` | "Maharashtra" |
| 3 | code | `String, nullable=False, unique=True` | "MH" |

#### `districts` → `District`
| # | Column | SQLAlchemy | Notes |
|---|---|---|---|
| 1 | district_id | `Integer, primary_key=True` | |
| 2 | state_id | `Integer, ForeignKey("states.state_id"), nullable=False` | |
| 3 | name | `String, nullable=False` | "Pune" |
| 4 | is_hill_district | `Integer, nullable=False, default=0` | 0/1 |
| 5 | default_area_type | `String, nullable=False, default='rural'` | metro / urban / semi_urban / rural |

`UniqueConstraint("state_id", "name")`,
`CheckConstraint("is_hill_district IN (0,1)")`,
`CheckConstraint("default_area_type IN ('metro','urban','semi_urban','rural')")`

Both of these columns are **generation hints only**. They seed sensible
defaults for a new work's `terrain` and `area_type`; the values that
matter for detection live on the work itself. Nothing in `checks.py` may
read either column.

#### `constituencies` → `Constituency`
| # | Column | SQLAlchemy | Notes |
|---|---|---|---|
| 1 | constituency_id | `Integer, primary_key=True` | |
| 2 | state_id | `Integer, FK states, nullable=False` | |
| 3 | name | `String, nullable=False` | "Pune" |
| 4 | house | `String, nullable=False` | lok_sabha / rajya_sabha |

`UniqueConstraint("state_id", "name", "house")`,
`CheckConstraint("house IN ('lok_sabha','rajya_sabha')")`

A Rajya Sabha member has no constituency in the ordinary sense; for
those rows use the state name with `house = 'rajya_sabha'`.

#### `mps` → `MP`
| # | Column | SQLAlchemy | Notes |
|---|---|---|---|
| 1 | mp_id | `Integer, primary_key=True` | |
| 2 | full_name | `String, nullable=False` | |
| 3 | house | `String, nullable=False` | lok_sabha / rajya_sabha |
| 4 | constituency_id | `Integer, FK constituencies, nullable=False` | |
| 5 | state_id | `Integer, FK states, nullable=False` | |
| 6 | term_start | `String, nullable=False` | ISO date |
| 7 | term_end | `String` | ISO date, NULL if serving |
| 8 | is_active | `Integer, nullable=False, default=1` | 0/1 |

`term_start` / `term_end` are not decoration — a work recommended
outside an MP's term is a data-integrity flag in C3.

#### `agencies` → `Agency`
| # | Column | SQLAlchemy | Notes |
|---|---|---|---|
| 1 | agency_id | `Integer, primary_key=True` | |
| 2 | name | `String, nullable=False` | "Pune Zilla Parishad" |
| 3 | agency_type | `String, nullable=False` | pwd / zilla_parishad / municipal / other |
| 4 | district_id | `Integer, FK districts, nullable=False` | |

#### `vendors` → `Vendor`
| # | Column | SQLAlchemy | Notes |
|---|---|---|---|
| 1 | vendor_id | `Integer, primary_key=True` | |
| 2 | name | `String, nullable=False` | |
| 3 | district_id | `Integer, FK districts, nullable=False` | |
| 4 | pan_hash | `String` | hashed, never a real PAN |
| 5 | address | `String` | |
| 6 | registered_on | `String` | ISO date |
| 7 | is_active | `Integer, nullable=False, default=1` | 0/1 |

Store a hash, never a real or realistic PAN. This is generated data and
must not resemble a genuine identity document.

---

### Group B — Accounts and access

#### `users` → `User`
Everyone who can log in — **including citizens**, which is a change from
the previous draft. Requiring a citizen login makes the one-complaint-
per-person rule enforceable and lets a citizen track their own report,
at the cost of some friction.

Still separated from `mps`: an MP is a *person in the scheme*, a user is
*a login*. One MP may have no login; one login may be a clerk acting for
a district.

| # | Column | SQLAlchemy | Notes |
|---|---|---|---|
| 1 | user_id | `Integer, primary_key=True` | |
| 2 | username | `String, nullable=False, unique=True` | "do.pune", "mp.pune01" |
| 3 | password_hash | `String, nullable=False` | werkzeug — never plaintext |
| 4 | full_name | `String, nullable=False` | |
| 5 | role | `String, nullable=False` | citizen / mp / district_officer / state_officer / ministry |
| 6 | scope_type | `String, nullable=False` | constituency / district / state / national |
| 7 | scope_id | `Integer` | meaning depends on scope_type; NULL when national |
| 8 | mp_id | `Integer, FK mps` | only for role = 'mp' |
| 9 | is_active | `Integer, nullable=False, default=1` | 0/1 |
| 10 | created_at | `String, nullable=False` | ISO datetime |
| 11 | last_login_at | `String` | NULL until first login |

`CheckConstraint("role IN ('citizen','mp','district_officer','state_officer','ministry')")`,
`CheckConstraint("scope_type IN ('constituency','district','state','national')")`

A citizen's scope is their own constituency.

`scope_id` is deliberately **not** a ForeignKey — its target table
depends on `scope_type`, so no single FK can express it. Validate it in
`auth.py` at step 05. Comment this so a later reader does not "fix" it.

`scope_type` + `scope_id` decides which *rows* are visible. `role`
decides which *actions* are allowed. Keep the two concepts separate —
conflating them is why role systems become unmaintainable.

#### Permission matrix

Recorded here because it shapes the API in step 04 and the auth
dependencies in step 05. No code enforces it yet at this step.

| Action | citizen | mp | district_officer | state_officer | ministry |
|---|:--:|:--:|:--:|:--:|:--:|
| Browse works in scope | ✅ | ✅ | ✅ | ✅ | ✅ |
| See risk score and reasons | ❌ | ✅ | ✅ | ✅ | ✅ |
| File a complaint | ✅ | ❌ | ❌ | ❌ | ❌ |
| Verify a complaint | ❌ | ❌ | ✅ | ✅ | ❌ |
| Acknowledge an alert | ❌ | ❌ | ✅ | ✅ | ❌ |
| Escalate an alert | ❌ | ❌ | ✅ | ✅ | ❌ |
| Resolve an alert with a verdict | ❌ | ❌ | ✅ | ✅ | ❌ |
| Snooze an alert | ❌ | ❌ | ✅ | ✅ | ❌ |
| National dashboard | ❌ | ❌ | ❌ | ❌ | ✅ |
| Upload data | ❌ | ❌ | ✅ | ✅ | ✅ |

**Only District and State officers act on alerts.** MPs and the Ministry
are view-only, and this is not an arbitrary product choice: under the
scheme an MP *recommends* works while the District Authority sanctions,
executes and verifies them. A platform that let an MP close an alert on
their own constituency's work would invert the accountability the scheme
is built on. Say that if asked — it demonstrates domain understanding,
not just role plumbing.

Citizens have the narrowest surface: browse and complain, nothing else.

#### Two portals, one database

The public and officer surfaces are served by **separate API routers**
(`/citizen/*` and `/officer/*`) with different auth dependencies, and by
**separate page sets** in the React app. They read the **same
`mplads.db`** — never two databases.

Separate routers make the citizen restriction structural rather than
remembered: the citizen router has no code path that selects
`total_score`, so it cannot leak one. Two databases, by contrast, would
break the link between a citizen's complaint and the officer's score for
the same work, and would require every work to exist twice and stay in
sync.

#### Authentication — no session table

The login screen may offer a role selector for convenience, but **the
server must ignore it** and read `role` from this table. A client that
can declare its own role has no access control at all; a judge testing
your authorisation will try exactly this.

On successful login the server issues a JWT carrying
`sub` (user_id, as a **string** — PyJWT rejects an integer `sub`),
`role`, `scope_type`, `scope_id` and `exp` (12 hours). Every subsequent
request decodes it and derives the query filter from the claims.

What this costs, and the honest answer if asked: a stateless token
cannot be revoked, so logout only deletes the client's copy, and
`is_active = 0` does not take effect until the token expires. Mitigate
by checking `users.is_active` on state-changing actions
(acknowledge / escalate / resolve) while skipping it on plain reads.
Production would add a revocation list; a twelve-hour token is
acceptable for a prototype.

The signing secret is read from the `JWT_SECRET` environment variable,
must be at least 32 bytes, and must never appear in the repository.

---

### Group C — The scheme's core records

#### `allocations` → `Allocation`
One row per MP per financial year.

| # | Column | SQLAlchemy | Notes |
|---|---|---|---|
| 1 | allocation_id | `Integer, primary_key=True` | |
| 2 | mp_id | `Integer, FK mps, nullable=False` | |
| 3 | fy | `String, nullable=False` | "2024-25" |
| 4 | entitlement | `Integer, nullable=False` | rupees, 50000000 |
| 5 | released | `Integer, nullable=False` | rupees actually authorised |
| 6 | spent | `Integer, nullable=False` | rupees disbursed |
| 7 | released_on | `String` | ISO date |

`UniqueConstraint("mp_id", "fy")`

**Do not add SC/ST spend columns.** They are derived by summing `works`
where `is_sc_area = 1` / `is_st_area = 1`. Storing them alongside the
derived sum guarantees the two disagree.

Note for the generator: since 1 April 2023 the ₹5 crore annual
entitlement is released as a **single annual instalment**, not two of
₹2.5 crore. Model years before and after that change correctly if the
dataset spans them.

#### `works` → `Work`
The central table. Twenty-seven columns.

| # | Column | SQLAlchemy | Notes |
|---|---|---|---|
| 1 | work_id | `Integer, primary_key=True` | |
| 2 | mp_id | `Integer, FK mps, nullable=False` | |
| 3 | constituency_id | `Integer, FK constituencies, nullable=False` | |
| 4 | district_id | `Integer, FK districts, nullable=False` | |
| 5 | agency_id | `Integer, FK agencies` | nullable pre-sanction |
| 6 | vendor_id | `Integer, FK vendors` | nullable pre-award |
| 7 | fy | `String, nullable=False` | "2024-25" |
| 8 | work_type | `String, nullable=False` | road / bridge / hospital / borewell / … |
| 9 | description | `String, nullable=False` | free text, messy on purpose |
| 10 | terrain | `String, nullable=False` | plain / hilly / coastal |
| 11 | area_type | `String, nullable=False` | metro / urban / semi_urban / rural |
| 12 | quantity | `Float, nullable=False` | see unit map |
| 13 | unit | `String, nullable=False` | km / count / sqm / beds |
| 14 | estimated_cost | `Integer, nullable=False` | rupees |
| 15 | final_cost | `Integer` | NULL until completed |
| 16 | recommended_on | `String, nullable=False` | ISO date |
| 17 | sanctioned_on | `String` | NULL if not yet sanctioned |
| 18 | expected_completion_on | `String` | ISO date, NULL until sanctioned |
| 19 | completed_on | `String` | NULL if unfinished |
| 20 | status | `String, nullable=False` | recommended / sanctioned / in_progress / completed |
| 21 | progress_pct | `Float, nullable=False, default=0` | 0–100, may be stale |
| 22 | last_updated_on | `String, nullable=False` | ISO date — staleness signal |
| 23 | lat | `Float` | |
| 24 | lon | `Float` | |
| 25 | is_sc_area | `Integer, nullable=False, default=0` | 0/1 |
| 26 | is_st_area | `Integer, nullable=False, default=0` | 0/1 |
| 27 | planted_anomaly | `String` | ground truth, NULL for clean rows |

Five columns exist for named reasons:

- **`area_type`** — urbanisation, independent of terrain. A metro road
  legitimately costs several times a rural one; comparing them without
  this column manufactures false positives. Seeded from
  `districts.default_area_type` but stored per work, because one
  district contains both.
- **`recommended_on`** separate from `sanctioned_on` — the gap is the
  District Authority's sanction lag, a distinct signal from execution
  delay.
- **`expected_completion_on`** — stored, not computed. Set at sanction
  time as `sanctioned_on + EXPECTED_DURATION_DAYS[(work_type, area_type)]`.
  It is stored rather than derived because the citizen page shows
  "overdue by N days" and `checks.py` computes delay from the same
  figure; deriving it in two places guarantees the two eventually
  disagree about what "overdue" means.
- **`progress_pct`** — needed for the payment-versus-progress gap. May
  be zero or stale; checks must handle that rather than assume it is
  populated.
- **`last_updated_on`** — when the record was last touched at all. A
  work nobody has updated in 400 days while money moved is suspicious
  whether or not `progress_pct` is meaningful. This is the fallback that
  makes the ghost-asset check work on incomplete data.

**Cost convention:** always `COALESCE(final_cost, estimated_cost)`.
Never `final_cost` alone — it is NULL for every unfinished work, which
would silently exclude exactly the works most likely to be problems.
Expose this as a hybrid property or a module-level helper so no query
forgets it.

`planted_anomaly` exists only so `evaluate.py` can measure recall. It
must never be read by `checks.py`, and must be excluded from every
Pydantic response model in step 04.

#### `payments` → `Payment`
One row per tranche. Without this table there is no payment-versus-
progress gap, which is the strongest ghost-asset signal available.

| # | Column | SQLAlchemy | Notes |
|---|---|---|---|
| 1 | payment_id | `Integer, primary_key=True` | |
| 2 | work_id | `Integer, FK works, nullable=False` | |
| 3 | vendor_id | `Integer, FK vendors` | |
| 4 | tranche_no | `Integer, nullable=False` | 1, 2, 3… |
| 5 | amount | `Integer, nullable=False` | rupees |
| 6 | paid_on | `String, nullable=False` | ISO date |
| 7 | progress_pct_at_payment | `Float` | NULL if unrecorded |
| 8 | voucher_ref | `String` | |

`UniqueConstraint("work_id", "tranche_no")`, `CheckConstraint("amount > 0")`

#### `progress_updates` → `ProgressUpdate`
The *history* of the progress field, not just its current value. A
falsified progress number is hard to spot; a number that jumped from 20
to 90 in one day, or whose whole history was entered on a single
afternoon, is not.

| # | Column | SQLAlchemy | Notes |
|---|---|---|---|
| 1 | update_id | `Integer, primary_key=True` | |
| 2 | work_id | `Integer, FK works, nullable=False` | |
| 3 | progress_pct | `Float, nullable=False` | 0–100 |
| 4 | reported_on | `String, nullable=False` | ISO date |
| 5 | reported_by | `String` | agency name or user reference |
| 6 | note | `String` | |

#### `evidence` → `Evidence`
Photographs and documents attached to a work. **The absence of rows here
is itself the signal** — a work marked complete with no evidence row is
exactly what the ghost-asset check looks for.

| # | Column | SQLAlchemy | Notes |
|---|---|---|---|
| 1 | evidence_id | `Integer, primary_key=True` | |
| 2 | work_id | `Integer, FK works, nullable=False` | |
| 3 | kind | `String, nullable=False` | photo / completion_cert / handover / utilisation_cert |
| 4 | file_path | `String` | |
| 5 | photo_hash | `String` | perceptual hash — duplicate photo detection |
| 6 | exif_lat | `Float` | |
| 7 | exif_lon | `Float` | |
| 8 | stage | `String` | before / during / after |
| 9 | captured_at | `String` | ISO datetime |
| 10 | uploaded_at | `String, nullable=False` | ISO datetime |

---

### Group D — Output of the system

#### `scores` → `Score`
**New table.** One row per subject per scoring run, for **every**
subject — a clean work scoring 3 gets a row exactly as a flagged one
scoring 78 does. This is what lets the citizen project listing and the
officer worklist read from the same place.

| # | Column | SQLAlchemy | Notes |
|---|---|---|---|
| 1 | score_id | `Integer, primary_key=True` | |
| 2 | subject_type | `String, nullable=False` | work / mp / district |
| 3 | subject_id | `Integer, nullable=False` | work_id, mp_id, or district_id |
| 4 | total_score | `Integer, nullable=False` | 0–100, clamped |
| 5 | cost_points | `Integer, nullable=False, default=0` | C1 |
| 6 | delay_points | `Integer, nullable=False, default=0` | C2 + C2b |
| 7 | compliance_points | `Integer, nullable=False, default=0` | C3 / C3-MP |
| 8 | duplicate_points | `Integer, nullable=False, default=0` | C5 |
| 9 | public_points | `Integer, nullable=False, default=0` | C6 — citizen reports |
| 10 | evidence_points | `Integer, nullable=False, default=0` | C7 — paid, no proof of work |
| 11 | utilisation_points | `Integer, nullable=False, default=0` | C4 — district subjects only |
| 12 | reasons_json | `Text, nullable=False` | the human-readable sentences |
| 13 | checks_run | `Text, nullable=False` | JSON array of check ids that executed |
| 14 | checks_skipped | `Text, nullable=False` | JSON array of `{check, why}` |
| 15 | scored_on | `String, nullable=False` | ISO datetime |

`UniqueConstraint("subject_type", "subject_id")` — one current score per
subject. `checks.py` deletes and rebuilds the whole table on each run;
score history is out of scope for the prototype, though this shape would
support it by dropping the unique constraint later.

`CheckConstraint("total_score BETWEEN 0 AND 100")`,
`CheckConstraint("subject_type IN ('work','mp','district')")`

**Why per-check columns and not JSON alone.** These are queryable:
`SELECT district_id, AVG(delay_points) … GROUP BY district_id` answers
"which districts have a delay problem specifically", and the dashboard's
flags-by-type chart is a plain `GROUP BY` rather than JSON parsing in
Python. `reasons_json` stays for the sentences the UI prints; the
columns carry the numbers.

The tradeoff is that adding a new check later means a schema change.
That is acceptable here because the database is rebuilt from scratch on
every run.

`checks_skipped` implements graceful degradation. A check whose required
fields are absent must record why rather than silently scoring zero, so
the alert page can say *"3 of 8 checks ran; payment-progress and
evidence checks require authenticated eSAKSHI data."*

`reasons_json` shape, fixed:

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

#### `alerts` → `Alert`
Now a thin workflow record pointing at a score. Created only when
`total_score >= 25`.

| # | Column | SQLAlchemy | Notes |
|---|---|---|---|
| 1 | alert_id | `Integer, primary_key=True` | |
| 2 | score_id | `Integer, FK scores, nullable=False, unique=True` | |
| 3 | severity | `String, nullable=False` | critical / high / medium |
| 4 | status | `String, nullable=False, default='open'` | open / acknowledged / escalated / resolved |
| 5 | verdict | `String` | NULL / substantiated / not_substantiated / could_not_verify |
| 6 | resolution_note | `String` | why it was closed |
| 7 | snoozed_until | `String` | ISO date — reappears after this |
| 8 | assigned_to | `Integer, FK users` | |
| 9 | created_at | `String, nullable=False` | ISO datetime |
| 10 | resolved_at | `String` | ISO datetime |

`CheckConstraint("severity IN ('critical','high','medium')")`,
`CheckConstraint("status IN ('open','acknowledged','escalated','resolved')")`,
`CheckConstraint("verdict IS NULL OR verdict IN ('substantiated','not_substantiated','could_not_verify')")`

Severity bands: 70–100 critical, 45–69 high, 25–44 medium. Below 25 the
subject still gets a `scores` row but no alert.

**`verdict` and `resolution_note` are not optional decoration.** An
officer must not be able to clear a ₹31 lakh alert with a bare
"visited" button — closing an alert has to record *what was found*. Both
fields are required when `status` moves to `resolved`; enforce that in
the API at step 04, not in the schema, so the constraint stays readable.

`snoozed_until` is the honest alternative to a dismiss button: the alert
returns instead of disappearing.

#### `complaints` → `Complaint`
Public reports. Now filed by a logged-in citizen.

| # | Column | SQLAlchemy | Notes |
|---|---|---|---|
| 1 | complaint_id | `Integer, primary_key=True` | |
| 2 | work_id | `Integer, FK works, nullable=False` | |
| 3 | user_id | `Integer, FK users, nullable=False` | the citizen |
| 4 | text | `String, nullable=False` | |
| 5 | photo_path | `String` | |
| 6 | lat | `Float` | |
| 7 | lon | `Float` | |
| 8 | verified | `Integer, nullable=False, default=0` | 0/1 — only verified rows score |
| 9 | verified_by | `Integer, FK users` | |
| 10 | created_at | `String, nullable=False` | ISO datetime |

`UniqueConstraint("work_id", "user_id")` — one complaint per citizen per
work. That constraint is what makes C6's distinct-reporter count
meaningful and stops one person inflating a score.

`reporter_hash` is gone; the citizen login supersedes it.

The attribute is named `text` — take care not to shadow the imported
`sqlalchemy.text` in this module. Import it as
`from sqlalchemy import text as sql_text` where both are needed.

**Never store a raw phone number or device ID anywhere.** This is a
government platform handling reports about named public figures; treat
identifying data as a liability.

---

### Group E — Accountability

#### `audit_log` → `AuditLog`
Every state-changing action. Non-negotiable in a government system, and
more important now that there is no session table to cross-reference.

| # | Column | SQLAlchemy | Notes |
|---|---|---|---|
| 1 | log_id | `Integer, primary_key=True` | |
| 2 | user_id | `Integer, FK users` | NULL for system actions |
| 3 | action | `String, nullable=False` | login / acknowledge / escalate / resolve / snooze / complain / verify / upload / run_checks |
| 4 | subject_type | `String` | |
| 5 | subject_id | `Integer` | |
| 6 | detail | `String` | short JSON or free text |
| 7 | created_at | `String, nullable=False` | ISO datetime |

`subject_type` + `subject_id` say what the action was done *to* — an
alert, a work, an MP — or NULL for actions with no target, such as
login. Like the other polymorphic pairs, not a ForeignKey.

Append-only. Nothing in the codebase may UPDATE or DELETE from it.

---

### Indexes

Declared with `Index(...)` in each model's `__table_args__`, or as
`index=True` on single columns. `create_all()` emits them.

| Name | Columns |
|---|---|
| idx_works_peer | works(work_type, terrain, area_type, district_id) |
| idx_works_mp | works(mp_id, fy) |
| idx_works_district | works(district_id, status) |
| idx_works_constituency | works(constituency_id) |
| idx_payments_work | payments(work_id) |
| idx_progress_work | progress_updates(work_id, reported_on) |
| idx_evidence_work | evidence(work_id, kind) |
| idx_evidence_hash | evidence(photo_hash) |
| idx_scores_subj | scores(subject_type, subject_id) |
| idx_scores_total | scores(subject_type, total_score DESC) |
| idx_alerts_open | alerts(status, severity) |
| idx_complaints_work | complaints(work_id, verified) |

Twelve indexes. Three are load-bearing:

- `idx_works_peer` — column order matches the peer-group ladder below,
  so each rung is a prefix of this index.
- `idx_scores_total` — the worklist sort.
- `idx_evidence_hash` — the reused-photo check is a self-join on this.

`idx_sessions_user` is gone with the sessions table.

### Peer-group ladder

`config.py` defines it; `checks.py` walks it. Try each rung in order and
stop at the first with at least `PEER_GROUP_MIN_ROWS` (8) rows:

1. `work_type + terrain + area_type + district_id`
2. `work_type + terrain + area_type + state_id`
3. `work_type + terrain + area_type`
4. `work_type + area_type`
5. `work_type`

If even the last rung has fewer than 8 rows, **skip C1, award zero, and
record it in `checks_skipped`** — do not guess. Store the rung used in
`evidence.peer_level` so the UI can say "compared against 47 hilly metro
roads".

`area_type` is given up **after** district deliberately: urbanisation
explains more cost variance than geography does, so it is worth keeping
longer.

**Dataset-size consequence.** Three dimensions plus district makes rung 1
small. With 2,000 works across 6 work types, 3 terrains and 4 area types
the first rung averages three rows — not a median. **Step 02 must
generate 4,000–5,000 works**, and most comparisons will land on rung 3.
Note this in the step 02 spec.

### CHECK constraints to enforce

Every one is a `CheckConstraint` in the model's `__table_args__`.
SQLAlchemy will not infer them from Python types.

- `works.status` in (recommended, sanctioned, in_progress, completed)
- `works.terrain` in (plain, hilly, coastal)
- `works.area_type` in (metro, urban, semi_urban, rural)
- `works.unit` in (km, count, sqm, beds)
- `works.progress_pct` between 0 and 100
- `works.is_sc_area`, `works.is_st_area` in (0, 1)
- `districts.default_area_type` in (metro, urban, semi_urban, rural)
- `districts.is_hill_district` in (0, 1)
- `mps.house`, `constituencies.house` in (lok_sabha, rajya_sabha)
- `users.role` in (citizen, mp, district_officer, state_officer, ministry)
- `users.scope_type` in (constituency, district, state, national)
- `scores.subject_type` in (work, mp, district)
- `scores.total_score` between 0 and 100
- every `*_points` column on `scores` >= 0
- `alerts.severity` in (critical, high, medium)
- `alerts.status` in (open, acknowledged, escalated, resolved)
- `alerts.verdict` IS NULL OR in (substantiated, not_substantiated, could_not_verify)
- `payments.amount` > 0
- `evidence.kind` in (photo, completion_cert, handover, utilisation_cert)
- `complaints.verified` in (0, 1)
- `vendors.is_active`, `mps.is_active`, `users.is_active` in (0, 1)

## Detection logic

No detection logic. Checks are step 03. This step defines only the
thresholds, point caps and the peer-group ladder in `config.py` that
step 03 will read.

## Frontend

No frontend changes. The React app arrives in step 06.

Three rules to record now, because they shape the API in step 04.

**1. Citizens see facts, not scores.** A logged-in citizen browsing
their constituency sees cost, dates, status, contractor name, photos and
map location — but not `total_score` and not the reasons. A work showing
"Risk 78" publicly, before any officer has verified it, is an accusation
the system is not entitled to make; the hilly road may be legitimately
expensive. Scores become visible to the public only after an officer
resolves the alert, if at all.

**Delay is a fact, not a score.** "Expected by 16 Jan 2026, still in
progress — 242 days overdue" is date arithmetic from two fields the
citizen can already see, so show it plainly. Withholding it would make
the citizen page less honest, not more careful. This is why
`expected_completion_on` is a stored column.

Contractor names are public record and may be shown. **Never show a
contractor name next to a risk score on a public page** — facts about a
named private company are transparency; a score beside their name is an
accusation. Citizens not seeing scores keeps this safe; do not relax it
later.

**2. Each role's view is a different shape, not the same screen
filtered.** Building one worklist and relabelling it four times is
visible to anyone looking closely.

- **Citizen** — project list with dates, cost, contractor, photos, map,
  overdue flag; a complaint button.
- **MP** — constituency works, plus an SC/ST quota meter against the 15%
  and 7.5% floors, unspent balance, and stalled works. Framed as
  assistance, not audit.
- **District Officer** — the ranked worklist, alert detail with the
  evidence pack, and the act buttons. This is the primary screen.
- **State Officer** — district comparison, and the MP-quota and
  district-utilisation alerts that are routed to them rather than to the
  district.
- **Ministry** — league tables and trend over time. They do not read
  individual works.

**3. Alert routing follows `scores.subject_type`.** Work-level scores
land on the District Officer's worklist. MP-quota and
district-utilisation scores land on the **State Officer's** — never only
on the person the alert is about. A district officer should not be the
sole recipient of an alert saying his own district is underspending.

## Files to change

- `CLAUDE.md` — replace the "Database schema" section with the schema
  above; change the ORM rule from "no ORM, raw sqlite3" to the
  SQLAlchemy split; record the JWT decision and the removal of
  `sessions`; add the `scores` table and the `area_type` dimension to
  the scoring section; correct the fund-release note from two
  instalments of ₹2.5 crore to a single annual instalment of ₹5 crore
  from 1 April 2023; tick step 01 once the Definition of Done passes.
- `.claude/commands/spec.md` — its Rules section still says "No ORM.
  Raw `sqlite3` only", which now contradicts this spec and would be
  copied into every future spec it generates. Update it to the
  SQLAlchemy split.

## Files to create

- `backend/__init__.py` — empty, so `python -m backend.generate_data`
  resolves.
- `backend/config.py` — `REFERENCE_DATE`, `DATABASE_URL`, all
  thresholds, all point caps, permitted and not-permitted work category
  lists, the work_type→unit map, the
  `(work_type, area_type)`→expected-duration map, the peer-group ladder,
  and the severity bands.
- `backend/models.py` — `Base` and all sixteen model classes, with every
  CheckConstraint, UniqueConstraint and Index declared.
- `backend/db.py` — the `engine`, the `foreign_keys` pragma event
  listener, `SessionLocal`, a `get_session()` context manager, a
  FastAPI-style `get_db()` dependency for step 04, and `init_db()`.
- `.claude/specs/01-project-skeleton-schema.md` — this file.

Splitting models from engine plumbing keeps `models.py` importable by a
test harness without opening a connection, and stops `db.py` growing
into a thousand-line module by step 06.

**Directory rename required.** A `Backend/` directory (capital B)
currently holds two empty files, `Authentication.PY` and
`Authorization.py`. Neither belongs to the layout CLAUDE.md defines, and
`.PY` breaks imports on case-sensitive filesystems. Authentication
arrives properly in step 05 as `backend/auth.py`. Delete both with
`git rm`, then rename the directory to lowercase `backend/`. macOS is
case-insensitive, so git needs an explicit two-step move
(`git mv Backend backend2 && git mv backend2 backend`) or the rename
will not be recorded.

## New dependencies

- **`sqlalchemy>=2.0`** — the ORM. Pin the major version; the 1.x and
  2.x APIs differ enough that a mixed tutorial will not run.

Not needed until later steps: `fastapi`, `uvicorn` (04); `pandas`,
`faker` (02); `pyjwt`, `werkzeug` (05); `python-multipart`, `openpyxl`
(11); `imagehash` (12). Install them when those steps arrive.

`alembic` is **not** required. Migrations are pointless while
`generate_data.py` rebuilds the database from scratch on every run;
`drop_all` + `create_all` is the migration strategy for this prototype.

## Rules for implementation

Project-wide:

- **SQLAlchemy 2.x ORM** for schema, CRUD, auth and serialisation.
  **`text()` with bound parameters** for analytical queries in
  `checks.py`. No other data-access style.
- **No string-formatted SQL, ever.** Named parameters in `text()`;
  never f-strings, never `%` formatting, never concatenation.
- **No ML libraries in the prototype.** Detection is median, IQR, date
  arithmetic and rules. No scikit-learn, no model files, no LLM calls in
  the scoring path.
- **Every flag must be explainable.** A check that cannot produce a
  human-readable reason string may not award points.
- **A check that cannot run must say so.** Record it in
  `scores.checks_skipped` with a reason; never silently score zero.
- **Wording.** Never output "fraud", "scam", or "corrupt" in code, UI
  copy, or comments. Use "flagged", "needs verification", "risk
  indicator".
- **Never rank or score Members of Parliament by suspicion.** MP-level
  scores cover compliance only — a quota shortfall is a compliance fact,
  not an accusation, and there is no MP leaderboard.
- **Scoring is capped.** No single check may exceed its cap in
  `config.py`; `total_score` is clamped to 0–100.
- **Determinism.** Running the checks twice on the same data must
  produce identical scores.
- **The server never trusts a client-supplied role or scope.** Both come
  from the verified JWT, which was built from `users`.

Step-specific:

- **`REFERENCE_DATE = date(2026, 9, 15)`, pinned.** `config.py` must not
  import or call `date.today()`, and neither may anything reading it.
- **Every threshold and point cap lives in `config.py`.** Step 03 must
  be able to retune C1's fence multipliers or C2's day bands without
  editing `checks.py`. Name them explicitly: `C1_MAX_POINTS = 35`,
  `C2_DELAY_BANDS`, `PEER_GROUP_MIN_ROWS = 8`, `PEER_GROUP_LADDER`,
  `EXPECTED_DURATION_DAYS = {("road","metro"): 270, …}`,
  `SEVERITY_BANDS`.
- **Expected duration is keyed by `(work_type, area_type)`,** not by
  work type alone. A metro road takes longer than a rural one for
  permissions and utility shifting, not construction; treating them the
  same makes every metro work look delayed.
- **The foreign-keys pragma is mandatory.** SQLAlchemy does **not**
  enable SQLite foreign keys, and `create_engine` has no option for it.
  Without this listener every FK in this spec is decorative and the FK
  test below will fail:

  ```python
  @event.listens_for(engine, "connect")
  def _set_sqlite_pragma(dbapi_connection, _):
      cur = dbapi_connection.cursor()
      cur.execute("PRAGMA foreign_keys=ON")
      cur.close()
  ```

- **`init_db()` is `Base.metadata.drop_all(engine)` then
  `create_all(engine)`.** SQLAlchemy sorts the drop order by dependency
  itself. Safe to re-run at any time.
- **`scope_id`, `scores.subject_id` and `audit_log.subject_id` are
  deliberately not ForeignKeys** — their target table is polymorphic.
  Comment all three so a later reader does not add one and break
  inserts.
- **Never join on `subject_id` without first filtering
  `subject_type`.** This is the trap the polymorphic column sets, and it
  fails silently rather than erroring:

  ```python
  # WRONG — a district-level score with subject_id = 3
  #         silently matches work_id = 3
  .join(Work, Work.work_id == Score.subject_id)

  # RIGHT — type filter and join belong together, always
  .filter(Score.subject_type == "work")
  .join(Work, Work.work_id == Score.subject_id)
  ```

  Put the filter and the join in a single shared helper so the two can
  never be separated. Without it, an officer sees an alert about MP #1
  rendered as work #1.
- **Scope filtering is one shared dependency, never per-route.**
  `scope_type` + `scope_id` come from the verified JWT and are applied
  in a single function that every scoped route depends on. Three rules
  follow from this, and all three are step 04/05 concerns recorded here
  so the API is not built the wrong way round:
  - Never filter by scope in the frontend. Data that reached React has
    already left the server; DevTools shows all of it.
  - Never accept a district, state or constituency id from the client.
    A route taking `?district_id=` lets an officer type someone else's.
    The value comes from the token, not the query string.
  - Never write the `WHERE` clause per route. One route will be missed.
- **Every CheckConstraint must be declared explicitly.** A missing one
  means the generator can write data your own checks then flag as a
  false positive.
- **Declare columns in the order given above.** `create_all` emits them
  in declaration order and the Definition of Done checks that order.
- **No `SELECT *` and no bare `.all()` on a full table in helpers.**
  Name columns or use `load_only`.
- **Do not add SC/ST spend columns to `allocations`.**
- **Nothing in `checks.py` may read `districts.is_hill_district` or
  `districts.default_area_type`.** Those are generation hints; the work's
  own `terrain` and `area_type` are the truth. Reading the district
  values would reintroduce exactly the bug this design avoids — a flat
  road in a hill district being excused as expensive-by-terrain.
- **`db.py` and `models.py` define schema only — they insert no rows.**
  All data comes from step 02, including the seeded demo users.
- **Store dates as ISO-8601 strings**, typed `String`, not `Date` or
  `DateTime`. SQLite has no date type; SQLAlchemy's date types add
  silent conversion behaviour, and ISO text sorts and compares correctly
  in both Python and SQL.
- **Money is `Integer` rupees.** No `Float` or `Numeric` for currency
  anywhere.
- **No real or realistic identity data.** PANs are hashes. Vendor and MP
  names are generated.

## Definition of done

- [ ] `python -c "import backend.models, backend.db"` succeeds from the
      project root.
- [ ] `python -m backend.db` creates `backend/mplads.db` with no errors.
- [ ] `python -c "from backend.models import Base; print(len(Base.metadata.tables))"`
      prints `16`.
- [ ] `sqlite3 backend/mplads.db ".tables"` lists exactly these sixteen,
      and nothing else: `agencies`, `alerts`, `allocations`,
      `audit_log`, `complaints`, `constituencies`, `districts`,
      `evidence`, `mps`, `payments`, `progress_updates`, `scores`,
      `states`, `users`, `vendors`, `works`.
- [ ] `sessions` does **not** appear in that list.
- [ ] `PRAGMA table_info(works)` returns 27 columns whose names and
      order match the `works` table above exactly — `area_type` at
      position 11, `expected_completion_on` at 18, `planted_anomaly`
      last.
- [ ] `PRAGMA table_info(scores)` returns 15 columns including all seven
      `*_points` columns and `checks_skipped`.
- [ ] `PRAGMA table_info(alerts)` returns 10 columns and includes
      `score_id`, `resolution_note` and `snoozed_until`.
- [ ] `PRAGMA table_info(users)` returns 11 columns including
      `scope_type` and `scope_id`.
- [ ] `.indexes` includes all twelve indexes listed above.
- [ ] On a session from `SessionLocal()`,
      `session.execute(text("PRAGMA foreign_keys")).scalar()` returns
      `1`. **This is the check most likely to fail** — it proves the
      event listener is wired.
- [ ] Running `init_db()` twice in a row succeeds and leaves every table
      empty — proving `drop_all` handles the dependency order.
- [ ] Adding a `Work` with a `vendor_id` that does not exist raises
      `IntegrityError` on flush (proves FK enforcement is live, not just
      declared).
- [ ] Adding a `Work` with `area_type = 'suburban'` raises
      `IntegrityError` — the allowed set is metro / urban / semi_urban /
      rural.
- [ ] Adding two `Complaint` rows sharing a `(work_id, user_id)` raises
      `IntegrityError`.
- [ ] Adding two `Score` rows sharing a `(subject_type, subject_id)`
      raises `IntegrityError`.
- [ ] Adding a `Score` with `total_score = 101`, or
      `subject_type = 'vendor'`, raises `IntegrityError`.
- [ ] Adding an `Alert` whose `score_id` does not exist raises
      `IntegrityError`; adding two alerts with the same `score_id` also
      raises.
- [ ] Adding a `User` with `role = 'auditor'` raises `IntegrityError`;
      `role = 'citizen'` **succeeds** — citizens are users in this
      revision.
- [ ] `grep -rn "date.today\|datetime.now" backend/` returns nothing.
- [ ] `grep -rni "fraud\|scam\|corrupt" backend/` returns nothing.
- [ ] `grep -rn "SELECT \*" backend/` returns nothing.
- [ ] `grep -rn "is_hill_district\|default_area_type" backend/` matches
      only `models.py` and `generate_data.py` — never `checks.py`
      (which does not exist yet; re-run this check at step 03).
- [ ] No f-string or `%`-formatted string is passed to `text()` anywhere
      in `backend/` — spot-check by eye; there is too little code at
      this step for a grep to be worth writing.
- [ ] `python -c "from backend.config import REFERENCE_DATE, PEER_GROUP_LADDER; print(REFERENCE_DATE, len(PEER_GROUP_LADDER))"`
      prints `2026-09-15 5`.
- [ ] `pip show sqlalchemy` reports version 2.0 or higher.
- [ ] The `Backend/` directory no longer exists and `git log --follow`
      shows the rename to `backend/` was recorded.
- [ ] CLAUDE.md's schema section matches this spec; its ORM rule says
      SQLAlchemy; it records JWT and the absence of `sessions`; and its
      fund-release note says single annual instalment from 1 April 2023.
- [ ] `.claude/commands/spec.md` no longer says "No ORM. Raw `sqlite3`
      only."
- [ ] No recall check applies at this step — there is no data and no
      scoring. The first baseline is established in step 03 and measured
      by `evaluate.py` in step 08.