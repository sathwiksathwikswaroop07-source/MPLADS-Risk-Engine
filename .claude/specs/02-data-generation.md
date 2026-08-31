# Spec 02 (revised) — Dummy data generator with planted anomalies

## Overview

Fills `backend/mplads.db` with ~6,000 works across 10 states and 53
districts, of which 290 carry a `planted_anomaly` label and **every
other row must be clean**.

This revision supersedes the as-built version. Two things changed:
spec 01b split `work_type` from 8 values to 15 and added the
`specification` column, and `TARGET_WORK_COUNT` rose from 4,500 to
6,000 to keep peer groups healthy after the split.

**The measurements from the first build are carried forward, not
discarded.** They were expensive to obtain and three of them dictate
implementation details that are not obvious from first principles. They
are recorded in "What the measurements forced" below, and the numbers
must be **re-measured** after regeneration — the split moves two of
them.

Nothing downstream works without this data: step 03 needs peer groups to
take medians against, step 08 needs ground truth to measure recall,
steps 04–07 need works and logins to serve.

## Depends on

- Step 01 — schema, config, engine.
- **Spec 01b** — the 15 work types, the `specification` column, the
  `m` unit, and the re-keyed cost model. Apply it first; this generator
  cannot run against the 8-type config.

## API endpoints

No API changes.

## Database changes

No schema changes in this step — spec 01b owns the `specification`
column and the `unit` constraint.

`backend/config.py` gains generation constants only: `BASE_UNIT_COST`,
`AREA_COST_MULTIPLIER`, `TERRAIN_COST_MULTIPLIER`,
`WORK_TYPE_QUANTITY_RANGE`, `WORK_TYPE_WEIGHTS`, `COST_NOISE_SIGMA`,
`RANDOM_SEED`, `TARGET_WORK_COUNT`, `FISCAL_YEARS`,
`PLANTED_ANOMALY_COUNTS`, and the clean-row guard rails.

These live in config rather than in the generator because the cost model
must be inspectable in one place. **`checks.py` must never read them** —
scoring against our own generation baseline would be marking our own
homework, and the recall number would mean nothing.

## Detection logic

None. This step produces the data that step 03 scores.

## Files to change

- `backend/config.py` — generation constants (mostly delivered by 01b)

## Files to create

- `backend/generate_data.py`

## New dependencies

- `faker` — generated MP, vendor and place names
- `werkzeug` — password hashing for the seeded demo accounts

---

## Rules for implementation

Project-wide rules from `CLAUDE.md` apply. The ones that bit hardest:

- **SQLAlchemy 2.x ORM.** No raw `sqlite3`, no string-formatted SQL.
- **Determinism.** One seeded `random.Random` instance threaded through
  every function; `Faker.seed()` alongside it. Never the global `random`
  module — an unrelated library seeding it silently changes the dataset.
  Iterate sorted collections only; never a `set`, never dict order.
- **No `date.today()` / `datetime.now()`.** Every date derives from
  `REFERENCE_DATE`.
- **Money is `Integer` rupees** — `int(round(x))` before assignment.
  **Dates are ISO-8601 strings** — `d.isoformat()`.
- **`checks.py` must never read** `planted_anomaly`, `specification`,
  `is_hill_district`, `default_area_type`, or the `BASE_UNIT_COST`
  family.
- **No real identity data.** PANs are hashes; names are generated.

Step-specific:

- **Clean rows must stay clean.** A clean row that trips a check is a
  real false positive. The generator actively prevents this rather than
  hoping — see the de-collision pass.
- **`quota_shortfall` is MP-level** and writes no work-level label.
  C3-MP scores the MP, and recall must be measured against the same
  subject type.
- **One label per work.** A work that is both overpriced and delayed
  makes per-label recall ambiguous. Draw the anomaly set from disjoint
  works.
- **`unit` is never drawn independently** — always
  `WORK_TYPE_UNITS[work_type]`. A peer group is one work type, so a
  mismatched unit makes that group's median meaningless.

---

## Generation order

Foreign keys dictate it. `session.flush()` after each tier to populate
the ids the next tier needs; **one commit at the end**, or batched
commits for the child tables. Never one commit per row — each is an
fsync, and ~40,000 of them turns a three-second script into minutes.

```
states → districts → constituencies → mps → agencies → vendors
       → users → allocations → works
       → payments, progress_updates, evidence, complaints
```

`init_db()` runs first, dropping and recreating all 16 tables. Always
safe to re-run; no partial-state handling, no existence checks.

`scores` and `alerts` stay **empty** — they belong to step 03.

---

## Scale

| Tier | Count |
|---|---|
| states | 10 |
| districts | 53 |
| constituencies | ~120 |
| mps | ~120 |
| agencies | ~150 |
| vendors | ~300 |
| users | ~40 |
| allocations | mps × 3 FYs |
| **works** | **`TARGET_WORK_COUNT` = 6,000** |
| payments | ~12,000 |
| progress_updates | ~18,000 |
| evidence | ~9,000 |
| complaints | ~200 |

Real district and constituency names are worth the effort — a judge
scanning the screen recognises Pune and Nashik; generated names read as
a toy.

---

## Works — field rules

Cost, for a clean work:

```
base   = BASE_UNIT_COST[work_type]
cost   = base × AREA_COST_MULTIPLIER[area_type]
              × TERRAIN_COST_MULTIPLIER[terrain]
              × quantity
              × lognormal(0, COST_NOISE_SIGMA)
```

- **`work_type`** drawn against `WORK_TYPE_WEIGHTS`, not uniformly.
- **`quantity`** from `WORK_TYPE_QUANTITY_RANGE[work_type]`.
- **`unit`** from `WORK_TYPE_UNITS[work_type]`. Never independent.
- **`terrain` / `area_type`** weighted by the district's
  `is_hill_district` and `default_area_type` hints. Those two district
  columns exist **only** for this weighting.
- **`final_cost`** NULL unless `status == "completed"`; when set,
  `estimated_cost × uniform(0.96, 1.12)` — honest variance, not a second
  anomaly source.
- **`expected_completion_on`** = `sanctioned_on +
  EXPECTED_DURATION_DAYS[(work_type, area_type)]`. Stored, not computed
  at read time.
- **Date chain monotonic** on clean works: `recommended_on ≤
  sanctioned_on ≤ completed_on ≤ REFERENCE_DATE`.
- **`progress_pct` consistent with `status`**: `completed` → 100,
  `recommended` → 0. Anything else is a data-integrity bug C7 will
  correctly flag, inflating the false-positive rate for no reason.
- **`lat` / `lon`** inside the district. A work in the Bay of Bengal is
  noticed instantly in a demo.

### `specification` — new in this revision

Short, human, consistent with the work type. Drawn from a small phrase
table per type, with the actual quantity interpolated:

| work_type | example |
|---|---|
| `road_single_lane` | `3.75 m carriageway, BT surface` |
| `road_two_lane` | `7.0 m carriageway, BT surface, paved shoulders` |
| `drain_covered` | `RCC box, 1.2 m depth, precast slab cover` |
| `bridge_minor` | `28 m span, 2-lane deck, Class A loading` |
| `hospital_phc` | `G+1, 18 beds, 1 lift, OPD block` |
| `hospital_chc` | `G+2, 60 beds, 2 lifts, OT and labour room` |
| `borewell_deep` | `165 m depth, 150 mm casing, submersible pump` |
| `streetlight_solar` | `40 poles, 9 m, 40 W LED with solar panel` |
| `community_hall` | `G+1, 420 sqm, stage and green room` |
| `school_wall` | `1.8 m height, brick with RCC coping` |

**Floors are named here and only here.** This is the field that carries
what the work-type split cannot: a `hospital_chc` on three floors and
one on a single floor are the same `work_type` with the same bed count,
and the cost gap between them is real. The system cannot score that
difference and must not pretend to — so it shows the officer the fact
and lets them judge it during verification.

Vary the values realistically. If every `hospital_chc` reads `G+2`, the
column demonstrates nothing in the demo, and the one screen where it
matters — the alert detail beside a cost comparison — falls flat.

---

## Clean works must actually be clean

The requirement most likely to be quietly missed, and it decides whether
the false-positive number is presentable.

Every work **without** a `planted_anomaly` label must sit comfortably
inside every threshold:

| Check | Clean works must satisfy |
|---|---|
| C1 cost | Inside the IQR fence of their own peer group |
| C2 delay | Under 180 days overdue, or completed |
| C2b stall | Updated within 90 days, or progress on track |
| C3 compliance | Monotonic dates, permitted category, inside MP term |
| C5 duplicate | Not near-identical to another work in the same district |
| C6 complaints | Zero or one verified complaint |
| C7 evidence | Payment ratio ≤ progress ratio + 0.20; completed works have evidence |

### Allocations must reconcile

`allocations.spent` for an MP-year must equal the summed payments across
that MP's works in that year. Generate works first, compute `spent` from
them. If the two disagree, C4 and C3-MP produce numbers that contradict
the work list on screen, and the first judge to add up the column finds
it.

`released` follows the scheme: `ANNUAL_ENTITLEMENT` (₹5 crore) as a
single instalment for FY ≥ 2023-24, per `SINGLE_INSTALMENT_FROM`.

### SC/ST placement is deliberate, not random

`quota_shortfall` is planted on exactly `PLANTED_QUOTA_SHORTFALL_MPS`
(4) MPs. For that label to mean anything, **every other MP must sit
above** the 15% SC and 7.5% ST floors.

Random `is_sc_area` assignment will not achieve this — with ~50 works
per MP, natural variance puts a handful of unplanted MPs under the
floor, and they surface as false positives indistinguishable from the
real finding. Assign against a per-MP target (18–25% SC, 9–14% ST), then
force the 4 planted MPs down to 6–11% SC.

### The no-progress works

`WORKS_WITHOUT_PROGRESS_DATA` works get `progress_pct = 0` and **zero
`progress_updates` rows**, so step 03's graceful-degradation path is
exercised by data rather than intention. These are **not** anomalies —
`planted_anomaly` stays NULL, and step 08 must not count them as false
positives.

---

## What the measurements forced

Three findings from the first build. Two are implementation requirements
that are not obvious from first principles; keep them.

**1. C5 collides by chance, badly.** C5 pairs works in the same district
and work_type within 10% unit cost and 60 days. At 4,500 works across 8
types that happened **~455 times by chance** against 20 planted pairs —
a 23× swamp. Widening the cost spread did not fix it (log-sd 0.55 still
left ~278). Clean works must be **actively de-collided** after
generation.

*Expected to improve after the split.* Collisions scale roughly with the
square of the bucket size, and 15 types instead of 8 roughly halves each
`(district, work_type)` bucket — so expect the chance count near a
quarter of 455. The sweep is still required. **Re-measure it.**

**2. The de-collision oscillated.** Fixing one pair at a time pushes
work X off Y and onto Z, then back onto Y — the same four collisions
were re-fixed on all twelve sweeps, forever. **The fix moves a work
clear of its whole neighbourhood at once**, not pair by pair.

**3. Direction matters.** Nudging costs *upward* piles works into the
peer group's upper tail and trips C1's IQR fence — trading one false
positive for another (C1's 2×-median rate went 0.64% → 2.25%). **Nudge
downward**, below the cheapest neighbour, which satisfies both checks.

### Cost-noise sigma is bounded on both sides

The IQR fence flags 1–4% of clean rows whatever sigma is chosen; that is
inherent to a right-skewed distribution. What matters is *where they
land*, because C1 is fence-gate then ratio-band — a work clearing only
the fence scores 10, below the 25-point alert threshold:

| sigma | clears fence | → 10 pts only | → 20+ pts |
|---|---|---|---|
| 0.20 | 1.47% | 1.40% | 0.08% |
| 0.28 | 2.03% | 1.50% | 0.53% |
| 0.35 | 2.52% | 0.61% | 1.91% |
| 0.45 | 3.33% | 0.05% | 3.28% |

At 0.35+ clean rows start earning alert-grade points; below 0.25 costs
look implausibly uniform. **`COST_NOISE_SIGMA = 0.28`** — measured, not
guessed. Nothing in spec 01b touches the noise model, so this value
carries forward unchanged.

---

## Planted anomalies

Counts come from `config.PLANTED_ANOMALY_COUNTS`. Never hardcoded here
or in the generator.

| Label | Count | How to plant it |
|---|---|---|
| `cost_overrun` | 60 | Multiply `estimated_cost` by `uniform(3.0, 6.0)` **after** the clean cost is computed |
| `long_delay` | 80 | Sanctioned 400–700 days before `REFERENCE_DATE`, `in_progress`, progress 15–60 |
| `impossible_date` | 20 | `completed_on` 5–40 days *before* `sanctioned_on` |
| `ineligible_work` | 20 | Category drawn from `NOT_PERMITTED_WORK_CATEGORIES` |
| `duplicate_pair` | 40 (20 pairs) | Same district and type, unit cost within 6%, sanctioned 10–50 days apart. **Label both rows** |
| `payment_ahead_of_work` | 40 | Payments 75–95% of cost while progress is 10–30 |
| `ghost_asset` | 30 | Completed, progress 100, fully paid, **zero evidence rows** |
| `quota_shortfall` | 4 MPs | SC share forced to 6–11%. Labelled on the **MP** |

290 work-level labels out of 6,000 (~4.8%), plus 4 MPs.

Three planting rules that are easy to get wrong:

1. **Plant after the clean value exists, never instead of it.** A
   `cost_overrun` work still needs a correct base cost to multiply, or
   the "4.2× the peer median" sentence is a coincidence rather than a
   fact.
2. **De-collide clean rows *before* planting duplicates**, or the sweep
   will helpfully un-plant your 20 planted pairs.
3. **`ghost_asset` must be known before the evidence tier runs** — its
   evidence rows are *withheld*, not deleted afterwards. Same for the
   ~10 duplicate pairs that share a `photo_hash` to exercise C7's
   reused-photo component.

---

## Demo users

`CLAUDE.md`'s demo script names specific accounts. **Create exactly
these usernames** or the rehearsed demo breaks:

| Username | Role | Scope |
|---|---|---|
| `do.pune` | district_officer | district = Pune |
| `do.nashik` | district_officer | district = Nashik |
| `so.maharashtra` | state_officer | state = Maharashtra |
| `mp.pune` | mp | constituency, linked via `mp_id` |
| `ministry` | ministry | national |
| `citizen.pune` | citizen | constituency |

Plus ~30 filler accounts. The Pune/Nashik pair exists for the
ten-second access-control demonstration: log in as one, paste the
other's alert URL, get 403.

One shared password, defined once as a module constant and printed on
completion. Hash with `werkzeug.security.generate_password_hash` — the
same function `auth.py` verifies against in step 05.

**No endpoint anywhere writes `users.role`.** Roles exist only in seed
data. That is what "provisioned, never self-declared" means.

---

## Definition of done

Re-measure everything after regenerating — the type split moves several
of these numbers, and carrying forward the old ones would be reporting
results from a dataset that no longer exists.

Structure:

- [ ] `python -m backend.generate_data` runs clean; ~6,000 works
- [ ] `python -m backend.generate_data` runs again cleanly (init_db drops first)
- [ ] All 16 tables exist; 14 have rows — `scores` and `alerts` empty
- [ ] `PRAGMA foreign_key_check` returns 0 rows
- [ ] Every work's `unit` equals `WORK_TYPE_UNITS[work_type]` — zero mismatches
- [ ] All 15 work types are present; distribution matches `WORK_TYPE_WEIGHTS` within sampling error
- [ ] Every work has a non-empty `specification` consistent with its type
- [ ] `allocations.spent` equals summed payments for that MP-year, every row

Determinism:

```bash
python -m backend.generate_data && sha256sum backend/mplads.db > /tmp/a
python -m backend.generate_data && sha256sum backend/mplads.db > /tmp/b
diff /tmp/a /tmp/b        # identical
```

Ground truth:

- [ ] 290 work-level labels, every label at its exact target, plus 4 quota-shortfall MPs
- [ ] Every planted work carries exactly one label
- [ ] `duplicate_pair` count is even; both members of each pair labelled
- [ ] Exactly 4 MPs below the 15% SC floor; **no unplanted MP below either floor**
- [ ] All 30 `ghost_asset` works have zero evidence rows
- [ ] `WORKS_WITHOUT_PROGRESS_DATA` works have `progress_pct = 0` and no progress rows

Clean-row false positives — **the numbers that matter**:

- [ ] Zero on clean rows for C2, C3 (both branches), C6, C7 (both branches), and C5
- [ ] C5 chance collisions before de-collision: **record the new figure** (was ~455 at 8 types; expect far lower)
- [ ] C1 clean rows clearing the fence: target under ~1.5% (was 1.32%)
- [ ] C1 clean rows past 2× median: target under 1% (was 0.80%)
- [ ] The de-collision sweep terminates — no pair fixed more than once

Planted anomalies remain detectable:

- [ ] long_delay 80/80, impossible_date 20/20, ineligible_work 20/20, ghost_asset 30/30, payment_ahead 40/40
- [ ] cost_overrun: ≥57/60 past the fence
- [ ] duplicate_pair: ≥19/20

Peer groups:

- [ ] List every rung-3 group under `PEER_GROUP_MIN_ROWS` and the rung it falls through to. More will fall short than the previous eleven — that is the ladder working, not a fault, but it should be a documented list rather than a surprise at step 03.

Grep guards:

```bash
grep -rn "date.today\|datetime.now" backend/                 # empty
grep -rn "SELECT \*" backend/                                # empty
grep -rni "fraud\|scam\|corrupt" backend/                    # empty
grep -rln "BASE_UNIT_COST" backend/    # only config.py, generate_data.py
grep -rln "is_hill_district" backend/  # only models.py, generate_data.py
grep -rln "specification" backend/     # only models.py, generate_data.py
```

The real proof lands at step 03: run `checks.py` and confirm planted
anomalies score high while clean rows stay under 25.