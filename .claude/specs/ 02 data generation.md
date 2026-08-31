# Step 02 — Dummy data generator with planted anomalies

## Overview

Step 01 produced an empty `mplads.db` with 16 tables. This step fills it.

The dataset is not decoration. It is the **measuring instrument** for the
whole project: step 03 scores it, step 08 reports recall against it, and
that recall number is the strongest slide in the deck. A generator that
produces plausible-looking rows but no reliable ground truth makes every
later accuracy claim meaningless.

So this step has two jobs, in priority order:

1. **Generate ~4,500 works that are genuinely clean** — comfortably
   inside every threshold in `config.py`.
2. **Plant ~290 known-bad rows** on top, labelled in `planted_anomaly`,
   so `evaluate.py` can compute recall per anomaly type and one honest
   false-positive rate.

A third, smaller job: a narrow write layer (`crud.py`) for the handful
of writes the running application actually performs.

## Depends on

- Step 01 (schema) — complete.
- **`config.py` must gain the cost model first.** It does not have one
  yet. See "Prerequisite" below. The generator cannot start without it.

---

## Prerequisite: the cost model in `config.py`

To plant a "4× normal cost" anomaly, the generator must first know what
normal *is*. Add to `config.py`:

```python
BASE_UNIT_COST = { ... }          # rupees per unit, per work_type
AREA_COST_MULTIPLIER = { ... }    # metro / urban / semi_urban / rural
TERRAIN_COST_MULTIPLIER = { ... } # plain / hilly / coastal
COST_NOISE_SPREAD = 0.18          # ±18% lognormal jitter on clean works
```

A clean work's estimated cost is:

```
base × area_mult × terrain_mult × quantity × noise
```

**`checks.py` must never import these three tables.** Detection compares
a work against its real peers in the data, never against the constant we
chose. Scoring against our own generation baseline would be marking our
own homework and the recall number would mean nothing. This rule is in
`CLAUDE.md` and is verified by grep in the Definition of Done.

`COST_NOISE_SPREAD` is load-bearing and needs care. Too tight and the
IQR fence sits barely above the median, so ordinary works trip C1 and
the false-positive rate explodes. Too loose and a planted 4× overrun
hides inside normal spread and recall collapses. 0.18 is a starting
value — step 08 tunes it against the measured numbers.

---

## Files

```
backend/
├── config.py          ← extended with the cost model (above)
├── crud.py            ← NEW: the app's actual writes
└── generate_data.py   ← NEW: the dataset
```

`models.py` and `db.py` are unchanged. This step must not touch the
schema.

---

## `crud.py` — scope, and what is deliberately excluded

**This is not a generic CRUD layer, and it must not become one.**

The instinct is to write `create_state()`, `get_states()`,
`update_work()`, `delete_vendor()` for all 16 tables. Resist it. That
would be roughly forty functions, and the project would call maybe eight
of them. Worse, several would contradict the architecture:

> **eSAKSHI is the system of record.** Implementing agencies and
> district authorities enter works there as part of their existing
> workflow; this platform reads that data, scores it, and pushes alerts
> back. **We never create a project record.** — `CLAUDE.md`

An `update_work()` or `delete_work()` in the codebase invites a future
route to call it, and the moment one does, the "we are a read-only
overlay, not a parallel data-entry system" answer stops being true. A
judge who asks "so can your system edit government records?" should get
a one-word answer, backed by the absence of the function.

### What `crud.py` contains — the complete list

These are every write the running application performs:

| Function | Called by | Why it exists |
|---|---|---|
| `create_complaint(...)` | Citizen portal, step 10 | The one thing a citizen writes |
| `verify_complaint(...)` | Officer portal, step 07 | Officer confirms a report is real |
| `set_alert_status(...)` | Officer portal, step 07 | acknowledge / escalate / resolve / snooze |
| `record_login(...)` | Auth, step 05 | Stamps `users.last_login_at` |
| `write_audit(...)` | Everywhere above | Append-only; see below |

Read helpers live beside them, added as the API steps need them — not
speculatively now.

`scores` and `alerts` rows are written by `checks.py` in step 03, which
rebuilds both tables wholesale. That is a bulk rebuild, not CRUD, and
does not belong here.

### Rules for every write function

Each takes an existing `Session` as its first argument. **A CRUD
function must never create an engine, call `SessionLocal()`, or open its
own transaction** — the caller owns the transaction boundary, because
only the caller knows whether this write is one step of a larger unit of
work.

```python
def create_complaint(session: Session, *, work_id: int, user_id: int,
                     text: str, ...) -> Complaint:
    complaint = Complaint(work_id=work_id, user_id=user_id, text=text, ...)
    session.add(complaint)
    session.flush()          # assigns complaint_id, stays in the transaction
    write_audit(session, user_id=user_id, action="complaint_filed",
                subject_type="work", subject_id=work_id, detail=...)
    return complaint
```

Note `flush()`, not `commit()`. The complaint and its audit row must
land together or not at all; a commit inside the function would break
that. The FastAPI route commits once at the end.

### `write_audit` is the only writer of `audit_log`

`audit_log` is append-only. `crud.py` exposes `write_audit()` and
**nothing that updates or deletes an audit row.** Not a soft-delete
flag, not an "amend" helper. The value of an append-only log is entirely
in the absence of those functions.

### Delete operations

**There are none, for any table.** Nothing in the roadmap deletes
anything. If a future step needs one, it gets specified then, with a
reason.

---

## `generate_data.py`

### Determinism is a hard requirement, not a preference

Two runs with the same seed must produce byte-identical data. `checks.py`
run twice must give identical scores, and that chain starts here.

```python
rng = random.Random(config.RANDOM_SEED)   # instance, never the global module
Faker.seed(config.RANDOM_SEED)
fake = Faker("en_IN")
```

Use `rng.*` everywhere; never bare `random.*`, or an unrelated library
seeding the global generator silently changes your dataset.

Three specific traps:

- **Never iterate a `set`** when the order affects generated values.
  Python set ordering varies with hash randomisation across runs.
- **Never use `dict` ordering as a shuffle.** Sort explicitly.
- **Never call `date.today()`.** All dates derive from
  `config.REFERENCE_DATE`. This is grepped in the DoD.

### Reset behaviour

`generate_data.py` calls `init_db()` from `db.py` as its first action,
which drops and recreates all 16 tables. Always safe to re-run; no
partial-state handling, no "does this row already exist" checks. Say so
in the module docstring so nobody adds them later.

### Generation order

Foreign keys dictate it:

```
states → districts → constituencies → mps → agencies → vendors
       → users → allocations → works
       → payments, progress_updates, evidence, complaints
```

Use `session.flush()` after each parent tier to populate the ids the
next tier needs. **One `commit()` at the very end**, or batched commits
every few thousand rows for the child tables — never one commit per row.
Each commit is an fsync; ~20,000 of them turns a two-second script into
several minutes.

```python
with get_session() as session:      # commits once, on clean exit
    states = seed_states(session, rng)
    session.flush()
    districts = seed_districts(session, rng, states)
    session.flush()
    ...
```

### Scale and shape

| Tier | Count | Notes |
|---|---|---|
| states | 8–10 | Real names |
| districts | ~60 | Real names, spread across states |
| constituencies | ~120 | Lok Sabha + Rajya Sabha mix |
| mps | ~120 | One per constituency, real-ish names via Faker |
| agencies | ~150 | 2–3 per district |
| vendors | ~300 | 4–6 per district |
| users | ~40 | See demo accounts below |
| allocations | mps × 3 FYs | 2023-24, 2024-25, 2025-26 |
| **works** | **`TARGET_WORK_COUNT` (4500)** | The peer-group ladder needs this |
| payments | ~9,000 | 1–4 tranches per sanctioned work |
| progress_updates | ~14,000 | 2–6 per work, except the 400 below |
| evidence | ~7,000 | Absent on purpose for ghost assets |
| complaints | ~200 | Concentrated on a few works |

Real district and constituency names are worth the effort — a judge
scanning the screen recognises Pune and Nashik, and generated names read
as a toy. `CLAUDE.md` permits copying these from the public dashboard.

### `works` — field rules

Follow the Step 01 column semantics exactly. The ones with real logic:

- **`terrain` and `area_type`** are drawn per work, weighted by the
  district's `default_area_type` / `is_hill_district` hints — a Pune work
  is usually `urban` but sometimes `rural`. Those two district columns
  exist **only** for this weighting. `checks.py` may never read them.
- **`unit`** comes from `config.WORK_TYPE_UNITS[work_type]`. Never drawn
  independently — a peer group is one work_type, so a mismatched unit
  makes the group's median meaningless.
- **`estimated_cost`** from the cost model above. Integer rupees:
  `int(round(...))`, never a float in the column.
- **`final_cost`** is NULL unless `status == "completed"`. When set, it
  is `estimated_cost × rng.uniform(0.96, 1.12)` — small honest variance,
  not a second anomaly source.
- **`expected_completion_on`** = `sanctioned_on +
  EXPECTED_DURATION_DAYS[(work_type, area_type)]`, falling back to
  `DEFAULT_DURATION_DAYS`. **Stored, not computed at read time** — the
  citizen page shows "expected by 16 Jan 2026" and must not have to
  recompute it.
- **Date chain must be monotonic** on clean works:
  `recommended_on ≤ sanctioned_on ≤ completed_on ≤ REFERENCE_DATE`.
  Violating it is `impossible_date`, and it must only happen where
  deliberately planted.
- **`progress_pct`** must be consistent with `status`: `completed` → 100,
  `recommended` → 0. Anything else is a data-integrity bug that C7 will
  correctly flag, inflating your false-positive rate for no reason.
- **`lat` / `lon`** roughly inside the district. They are shown on a map;
  a work in the Bay of Bengal is noticed instantly in a demo.

### Clean works must actually be clean

This is the requirement most likely to be quietly missed, and it decides
whether the false-positive number is presentable.

Every work **not** carrying a `planted_anomaly` label must sit
comfortably inside every threshold — not marginally, comfortably:

| Check | Clean works must satisfy |
|---|---|
| C1 cost | Inside the IQR fence of their own peer group |
| C2 delay | Under 180 days overdue, or completed |
| C2b stall | Updated within 90 days, or progress on track |
| C3 compliance | Monotonic dates, permitted category, inside MP term |
| C5 duplicate | Not near-identical to another work in the same district |
| C6 complaints | Zero or one verified complaint |
| C7 evidence | Payment ratio ≤ progress ratio + 0.20; completed works have evidence rows |

C5 is the sneaky one. With 4,500 works over ~8 work types and ~60
districts, near-identical pairs happen *by chance* — same type, same
district, similar cost, sanctioned weeks apart. After generating, sweep
for accidental C5 matches among unlabelled works and perturb the cost or
sanction date of one of each pair until it clears. Skipping this sweep
is how you end up demoing a 12% false-positive rate you cannot explain.

### Allocations must reconcile with works

`allocations.spent` for an MP-year must equal the sum of payments across
that MP's works in that year. If the two disagree, C4 (district
utilisation) and C3-MP (quota) produce numbers that contradict the work
list on screen, and the first judge to add up the column finds it.

Generate the works first, then compute `spent` from them. Do not draw
`spent` randomly and hope.

`released` follows the scheme: `ANNUAL_ENTITLEMENT` (₹5 crore) as a
single instalment for FY ≥ 2023-24, per `SINGLE_INSTALMENT_FROM`.

### SC/ST areas need deliberate placement

`quota_shortfall` is planted on exactly `PLANTED_QUOTA_SHORTFALL_MPS`
(4) MPs. For that label to mean anything, **every other MP must sit
above** the 15% SC and 7.5% ST floors.

Random assignment of `is_sc_area` will not do this — with ~37 works per
MP, natural variance puts a handful of unplanted MPs under the floor,
and they surface as false positives that look exactly like the real
finding. Assign SC/ST works per MP against a target share (say 18–25%
SC, 9–14% ST), then force the 4 planted MPs down to 6–11% SC.

### The 400 no-progress works

`WORKS_WITHOUT_PROGRESS_DATA` (400) works get `progress_pct = 0` and
**zero `progress_updates` rows**, so the graceful-degradation path is
exercised by real data rather than by intention. These are **not**
anomalies — leave `planted_anomaly` NULL. Step 03 must skip C2b and the
progress half of C7 on them and record the skip in
`scores.checks_skipped`; step 08 must not count them as false positives.

---

## Planted anomalies

Counts come from `config.PLANTED_ANOMALY_COUNTS`. Never hardcode them
here or in the generator.

| Label | Count | How to plant it |
|---|---|---|
| `cost_overrun` | 60 | Multiply `estimated_cost` by `rng.uniform(3.0, 6.0)` **after** the clean cost is computed, so the peer median stays honest |
| `long_delay` | 80 | `sanctioned_on` 400–700 days before `REFERENCE_DATE`, status `in_progress`, `progress_pct` 15–60 |
| `impossible_date` | 20 | `completed_on` 5–40 days *before* `sanctioned_on` |
| `ineligible_work` | 20 | `work_type` / description drawn from `NOT_PERMITTED_WORK_CATEGORIES` |
| `duplicate_pair` | 40 (20 pairs) | Clone a work into the same district: same type, unit cost within 6%, sanctioned 10–50 days apart. **Label both rows** — C5 alerts both, and evaluate.py counts both |
| `payment_ahead_of_work` | 40 | Payments totalling 75–95% of cost while `progress_pct` is 10–30 |
| `ghost_asset` | 30 | `status = completed`, `progress_pct = 100`, fully paid, **zero evidence rows** |
| `quota_shortfall` | 4 MPs | SC share forced to 6–11%. Labelled on the **MP**, not on works |

Total ≈ 290 of 4,500 (~6.4%).

Three planting rules that are easy to get wrong:

1. **Plant after the clean value exists, never instead of it.** A
   `cost_overrun` work still needs a correct base cost to be multiplied,
   or the "4.2× the peer median" sentence in the alert is a coincidence
   rather than a fact.
2. **One label per work.** A work that is both overpriced and delayed
   makes per-label recall ambiguous — which label did the catch belong
   to? Draw the anomaly set from disjoint works.
3. **`duplicate_pair` and `ghost_asset` reach into child tables.**
   Duplicates need matching evidence `photo_hash` values if you also
   want to exercise C7's reused-photo rule (worth doing — plant ~10 of
   the pairs with a shared hash). Ghost assets need their evidence rows
   *withheld*, which means the anomaly must be known before the evidence
   tier runs, not patched in afterwards.

---

## Demo users

`CLAUDE.md`'s demo script names specific accounts. **The generator must
create exactly these usernames** or the rehearsed demo breaks:

| Username | Role | Scope |
|---|---|---|
| `do.pune` | district_officer | district = Pune |
| `do.nashik` | district_officer | district = Nashik |
| `so.maharashtra` | state_officer | state = Maharashtra |
| `mp.pune` | mp | constituency, linked via `mp_id` |
| `ministry` | ministry | national |
| `citizen.pune` | citizen | constituency |

Plus ~30 filler accounts across districts.

The Pune/Nashik pair exists for the ten-second access-control
demonstration: log in as one, paste the other's alert URL, get 403.

All demo accounts share one password, defined once as a module constant
and printed by the generator on completion. **Hash with
`werkzeug.security.generate_password_hash`** — the same function
`auth.py` will verify against in step 05. Never store plaintext, not
even in a prototype: it is one grep away from being visible in a demo,
and it is exactly the kind of detail a judge probes.

**No endpoint anywhere writes `users.role`.** Roles exist only here, in
seed data. That is what "provisioned, never self-declared" means.

---

## Rules for implementation

- SQLAlchemy ORM objects only. **No `text()` in this step at all** —
  analytical SQL belongs to `checks.py`.
- No f-string or `%`-formatted SQL anywhere, ever.
- Money is `int` rupees at the point of assignment. Do arithmetic in
  float if convenient, `int(round(x))` before it touches the column.
- Dates are ISO-8601 strings: `d.isoformat()`. Never a `date` object into
  a `String` column, never `str(datetime)`.
- All thresholds, counts, seeds and costs come from `config.py`. A
  literal number in `generate_data.py` that a judge might ask about is a
  bug.
- Structure as one function per tier (`seed_states`, `seed_districts`, …)
  each taking `(session, rng, …parents)` and returning what the next tier
  needs. A single 900-line `main()` cannot be debugged when the recall
  number comes out wrong.
- The generator prints a summary table of row counts on completion.

---

## Definition of done

Row counts and integrity:

```bash
python -m backend.generate_data     # completes, prints summary
python -m backend.generate_data     # runs again cleanly (init_db drops first)
```

- [ ] All 16 tables exist; 14 have rows (`scores` and `alerts` empty — they belong to step 03)
- [ ] `works` count is between 4,000 and 5,000
- [ ] Every `works.mp_id`, `constituency_id`, `district_id` resolves; no orphans
- [ ] Every `payments.work_id`, `progress_updates.work_id`, `evidence.work_id`, `complaints.work_id` resolves
- [ ] Every `complaints.user_id` resolves to a `citizen`-role user
- [ ] No `IntegrityError` on any insert — all CHECK constraints satisfied
- [ ] Exactly 400 works have `progress_pct = 0` and no `progress_updates` rows
- [ ] `allocations.spent` equals the summed payments for that MP-year, for every row

Ground truth:

- [ ] Planted label counts match `config.PLANTED_ANOMALY_COUNTS` exactly
- [ ] Every planted work carries exactly one label; no work has two
- [ ] `duplicate_pair` count is even, and both members of each pair are labelled
- [ ] Exactly 4 MPs are below the 15% SC floor; **no unplanted MP is below either floor**
- [ ] All 30 `ghost_asset` works have zero evidence rows

Determinism:

```bash
python -m backend.generate_data && sha256sum backend/mplads.db > /tmp/a
python -m backend.generate_data && sha256sum backend/mplads.db > /tmp/b
diff /tmp/a /tmp/b        # must be identical
```

Note: this compares the whole database file, which is the strictest form
of the check. If it fails, an unseeded `random` call or a set iteration
is the usual cause.

Rule compliance:

```bash
grep -rn "date.today\|datetime.now" backend/           # empty
grep -rni "fraud\|scam\|corrupt" backend/              # empty
grep -rn "text(" backend/generate_data.py              # empty
grep -rn "BASE_UNIT_COST\|COST_MULTIPLIER" backend/checks.py   # empty (when it exists)
grep -rn "def delete_\|def update_work" backend/crud.py        # empty
```

Sanity, by eye:

- [ ] Open the top 10 most expensive works — each is plausibly expensive for its type and area, not absurd
- [ ] Pick one district, add up its works' costs — the total is a believable multiple of ₹5 crore, not ₹900 crore
- [ ] The demo accounts log in (deferred to step 05, but the hashes must be present now)

---

## What this step deliberately does not do

- No scores. No alerts. Step 03 owns both tables and rebuilds them.
- No API. No auth verification. Steps 04 and 05.
- No `update_*` or `delete_*` functions for scheme data, in any file.