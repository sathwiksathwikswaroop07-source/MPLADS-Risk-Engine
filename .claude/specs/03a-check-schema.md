# Spec: Detection Checks And Scoring

## Overview

`backend/checks.py` reads the generated data, runs nine deterministic checks
across three subject levels, and writes a `scores` row for every work, MP and
district — plus an `alerts` row for the subjects that cross the threshold. This
is the step the project exists for: everything before it was scaffolding, and
everything after it is presentation.

Written after implementation, to record what was built and the three data
problems the work uncovered.

## Depends on

Steps 01 (schema, config) and 02 (data). Step 02 had to be repaired first —
see below.

## API endpoints

No API changes. Step 04 reads the `scores` and `alerts` tables this step fills.

## Database changes

No schema changes. `scores` and `alerts` already existed from step 01; this
step deletes and rebuilds both on every run and touches nothing else.

`backend/config.py` regained 13 generation constants that a config rewrite had
dropped (see "The blocking repair").

## Detection logic

Nine checks. Every one returns `{check, points, reason, evidence}` or nothing;
a check that cannot produce a human-readable reason may not award points.

### Work level — `subject_type = 'work'`

| Check | Cap | Rule |
|---|---|---|
| **C1** cost outlier | 35 | Unit cost against the peer median, gated by the IQR fence |
| **C2** delay | 25 | Days since sanction while not complete: 180/365/540 bands |
| **C2b** predicted stall | 8 | Behind schedule *and* untouched for 90 days — early warning |
| **C3** compliance | 15 | Date ordering, future dates, outside MP term, not-permitted category. Highest only, never stacked |
| **C5** duplicate | 20 | Same district and type, unit cost within 10%, sanctioned within 60 days. Both works alerted, each naming the other |
| **C6** citizen reports | 15 | Distinct verified reporters: 1/2/4 bands |
| **C7** paid without proof | 35 | Payment gap, completed-with-no-evidence, stale-while-paid, implausibly fast, shared photo. Summed, then capped |

### MP level — `subject_type = 'mp'`

**C3-MP** (25): SC-area spend below the 15% floor, ST below 7.5%, each scaled
by how far short it falls. The two stack. Scored against the MP, never against
their works — awarding it per-work would flag every work that member ever
recommended.

### District level — `subject_type = 'district'`

**C4** (15): spend measured *against the calendar*, not as a raw unspent
balance, plus a March-rush component.

### C1 is fence-first, then banded

A work inside `Q3 + 1.5·IQR` scores **zero even above 2× the median** — in a
tightly clustered peer group 2× is ordinary, and awarding ratio points there is
how a peer group of cheap borewells starts flagging half of itself. Past the
fence, award `max(fence_points, ratio_band)`.

Peer groups walk `PEER_GROUP_LADDER` until a rung holds ≥ 8 rows, and the rung
reached is recorded in `evidence.peer_level`. Stock SQLite has no `median()` or
`percentile()`, so quantiles are computed in Python; `statistics.quantiles`
sorts internally and is order-independent.

### C2 and C2b are mutually exclusive

Both write `delay_points`, so a work that is very overdue *and* stale would be
charged twice for one problem. C2 is evaluated first and C2b runs only behind
an explicit `if c2_points == 0:` guard.

## Frontend

No frontend changes.

## Files to change

- `backend/config.py` — restore 13 generation constants
- `backend/generate_data.py` — adopt two renamed constants

## Files to create

- `backend/checks.py`

## New dependencies

No new dependencies.

## Rules for implementation

- SQLAlchemy ORM for writes; `text()` with **bound named params** for
  analytics. No string-formatted SQL, no `SELECT *`.
- Never read the ground-truth anomaly label, the district generation hints, or
  the generator's baseline cost tables. Detection compares a work against its
  real peers; scoring against our own baseline would make recall meaningless.
- Cost is always `COALESCE(final_cost, estimated_cost)`.
- No `date.today()` — every date derives from `REFERENCE_DATE`.
- Never "fraud", "scam" or "corrupt". "Flagged", "needs verification".
- No ML. Median, IQR, date arithmetic, rules.
- One shared helper owns the polymorphic join, filtering `subject_type` before
  joining `subject_id`. The trap is real: work and district ids overlap, so an
  unfiltered join silently renders an MP alert as a work alert.
- A failing check degrades to a recorded skip rather than killing a
  4,500-work run.

## The blocking repair

A config rewrite (`a01aa44`) removed 15 constants `generate_data.py` imports,
so the generator died with `AttributeError: FISCAL_YEARS`. The failure came
*after* `init_db()`, leaving the database empty — nothing to score.

Thirteen were restored from `7fc87f6`. Two were renames adopted in the
generator instead: `QUOTA_SHORTFALL_MP_COUNT` → `PLANTED_QUOTA_SHORTFALL_MPS`,
and `SPARSE_DATA_WORK_COUNT` → `WORKS_WITHOUT_PROGRESS_DATA` (120 → 400, which
gives the graceful-degradation path a larger population).

## What the data revealed

Three findings, none of them fixable by tuning a threshold:

**1. C4 was scoring a financial year that does not exist.** `REFERENCE_DATE`
sits in FY 2026-27; the dataset runs to 2025-26, and 2025-26 has releases but
no works. C4 now scores the latest year with actual *spend*. Scoring a year
with no rows made C4 skip every district in the country — technically correct
and completely useless.

**2. The district allocation join was wrong.** Joining districts to
constituencies by `state_id` credited every district in Maharashtra with all
ten of its members' entitlements. It now follows `works.district_id`, which is
the real link between a district and the members who commission work there.

**3. Five checks can never raise an alert alone.** C2b (8), C3 (15), C5 (20),
C6 (15) and C4 (15) all cap below `ALERT_MIN_SCORE` (25):

| Planted label | Detected | Alerted | Why the gap |
|---|---|---|---|
| `payment_ahead_of_work` | 40/40 | 100% | C7 caps at 35 |
| `ghost_asset` | 30/30 | 90% | C7 caps at 35 |
| `cost_overrun` | 60/60 | 83% | C1 caps at 35 |
| `duplicate_pair` | 40/40 | 80% | C5 caps at 20 — needs a second check |
| `long_delay` | 80/80 | 64% | planted at 400–700 days; C2's middle band gives 18 |
| `impossible_date` | 20/20 | 55% | C3 caps at 15 |
| `ineligible_work` | 20/20 | 40% | C3 caps at 15 |

Every planted anomaly **is detected and scored**. The recall gap is entirely
about whether one check's cap reaches the alert threshold. `long_delay` is the
clearest case: CLAUDE.md plants it at 400–700 days, but its own C2 band table
only awards 25 at 540+, so a work at 400–539 scores 18 by design.

This is a threshold-design decision, not an implementation bug, so the
thresholds were left exactly as CLAUDE.md specifies. Raising C3 to 25, adding a
365+ band to C2, or lowering `ALERT_MIN_SCORE` would each close it — that call
belongs to the team.

**Also noted:** C7's shared-photo component cannot fire on the current dataset.
The generator derives `photo_hash` from `work_id`, so it is unique per work.
The check is correct and costs nothing; it contributes zero recall until a few
shared hashes are planted.

## Definition of done

Measured on the committed database.

- [x] Generator repaired: 4,520 works, 290 planted anomalies at exact targets,
      zero clean-row false positives
- [x] 4,646 subjects scored — 4,520 works, 73 MPs, 53 districts. Every subject
      has a row, clean ones included
- [x] 258 alerts, none below 25, none missing above 25
- [x] `total_score` within 0–100 for every row; no FK violations
- [x] **Deterministic** — two runs give identical summaries and an identical
      checksum over all score rows
- [x] C2 and C2b never both fire (0 works carry both)
- [x] 711 subjects record at least one skipped check with a readable reason
- [x] Clean-row false-positive rate **0.4%** (19 of 4,230)
- [x] Every planted label detected; alert rates in the table above
- [x] Alert routing: `mp` and `district` scores route to State, not District
- [x] `grep` guards clean in `checks.py`: no `date.today`/`datetime.now`, no
      `SELECT *`, no ground-truth label, no district hints, no baseline cost
      tables
- [x] The top alert explains itself from screen content alone

Top alert, work #740, score 55 (high): C2 +25 (sanctioned 626 days ago, 50%
complete, 416 days overdue), C5 +20 (matches work #865, unit cost within 7%,
6 days apart), C6 +10 (3 verified reporters). Six of six checks ran.
