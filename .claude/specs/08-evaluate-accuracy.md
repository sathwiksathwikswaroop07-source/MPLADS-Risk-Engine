# Spec: Accuracy Evaluation

## Overview

`backend/evaluate.py` measures the detection engine against the anomalies the
generator planted, reporting per-label recall and one overall false-positive
rate. This is the number CLAUDE.md says to close the demo on, and the only
honest answer to "does it actually work?".

Written after implementation, to record what was built and the two ground-truth
problems the work uncovered.

## Depends on

Steps 01–03b. Reads `works`, `scores` and `audit_log`; writes nothing.

## API endpoints

No API changes.

## Database changes

No schema changes. `generate_data.py` now writes `audit_log` rows recording
which MPs and vendors were planted — see below.

## Detection logic

No new detection logic. This measures what step 03 built.

## Frontend

No frontend changes.

## Files to change

- `backend/generate_data.py` — persist planted MP and vendor ids; fix the
  `quota_shortfall` planting arithmetic

## Files to create

- `backend/evaluate.py`

## New dependencies

No new dependencies.

## Rules for implementation

- **`evaluate.py` is the one module permitted to read `planted_anomaly`.**
  That is its entire purpose, and exactly why `checks.py` must never touch it:
  if the scoring code could see the labels, the number would measure itself.
- Never join `scores.subject_id` without filtering `subject_type` first. An
  MP-level label compared against work scores would silently match unrelated
  rows.
- Reads only. The script must never write to `scores` or `alerts`.

## What the work uncovered

**1. Two planted anomalies had no ground truth at all.** `works.planted_anomaly`
covers only the seven work-level labels. `quota_shortfall` is chosen per MP and
`vendor_overpricing` per vendor, and neither table has such a column — the
generator picked ids with `rng.sample`, returned them, and kept only `len()`
for the summary. The ids were discarded.

Recall for those labels was therefore unmeasurable, and could not be inferred:
20 MPs cross the alert threshold against 4 planted. The generator now writes
one `audit_log` row per planted subject (`action='planted_anomaly'`, NULL
`user_id`, the label in `detail`). That table already exists for system
provenance and its `subject_type`/`subject_id` pair is already polymorphic, so
no schema change was needed.

**2. `quota_shortfall` planting was silently broken.** Once ground truth
existed, the first evaluation run showed **0 of 4 planted MPs detected** — while
20 unplanted MPs alerted. The planting computed its target from *total work
cost* while C3-MP measures against *released funds*, and works routinely cost
several times what is released in one year:

```
mp 8: total work cost 812,995,751   released 200,000,000
      target = total x 0.15 x 0.4 = 48,779,745
      but the floor is released x 0.15 = 30,000,000
      -> planted "shortfall" landed at 23.6%, well ABOVE the 15% floor
```

All four planted MPs passed the check they were supposed to fail. Targeting
released funds instead puts them at 5.2–5.9% and detection went 0% → 100%.

This is the kind of bug that only an accuracy script finds. The generator ran
green, the checks ran green, and the number would have been quietly wrong.

## What is reported, and why two rates

Per label: **detected** (score > 0 — a check saw it) and **alerted**
(score ≥ 25 — it reached an officer's worklist). They differ sharply, and
collapsing them would hide the real finding: several checks cap below the alert
threshold, so a work can be correctly identified and still need a second signal
before anyone is sent to look at it. That is a threshold decision, not a
detection failure.

**Precision** is reported alongside the required metrics because it answers the
question an officer actually asks — *if I open an alert, how often is it real?*

## Definition of done

Measured on the committed database.

- [x] Per-label planted / detected / alerted / recall for all nine labels,
      including `quota_shortfall` at the **mp** level and `vendor_overpricing`
      at the **vendor** level
- [x] **Every planted label detected at 95–100%**
- [x] One overall false-positive rate: **1.02%** (43 of 4,230 clean works)
- [x] Work-level recall **74.8%** (217 of 290 reach an officer)
- [x] Precision **83.5%**
- [x] Deterministic: two runs print identical numbers
- [x] `checks.py` still contains no reference to `planted_anomaly`

```
label                    level    planted  detected  alerted   recall
cost_overrun             work          60   57 ( 95%)      47    78.3%
long_delay               work          80   80 (100%)      52    65.0%
impossible_date          work          20   20 (100%)      11    55.0%
ineligible_work          work          20   20 (100%)       8    40.0%
duplicate_pair           work          40   40 (100%)      32    80.0%
payment_ahead_of_work    work          40   40 (100%)      39    97.5%
ghost_asset              work          30   30 (100%)      28    93.3%
quota_shortfall          mp             4    4 (100%)       0     0.0%
vendor_overpricing       vendor         6    6 (100%)       2    33.3%
```

`quota_shortfall` alerts at 0% because the SC shortfall caps at 15 against a
25-point threshold — the same cap-below-threshold pattern step 03 recorded for
C4. Detection is correct; whether it should alert alone is a threshold decision
the team has deferred.
