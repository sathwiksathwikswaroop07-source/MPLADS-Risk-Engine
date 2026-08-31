# Spec: Inflation Adjustment And Vendor-Level Checks

## Overview

Two related additions to detection. Costs now escalate year-on-year in the
generated data, and C1 normalises that escalation away before comparing a work
with its peers. A fourth subject level — the vendor — scores contractors on
pricing and procurement conduct.

Written after implementation, to record what was built and the two regressions
the work uncovered.

## Depends on

Steps 01–03. No repair was needed this time; step 03 left the tree green.

## API endpoints

No API changes.

## Database changes

One schema amendment. `scores.subject_type` accepted only
`'work','mp','district'`, so a vendor score raised `IntegrityError`. It now
accepts `'vendor'` as well.

No new table: `vendors` already exists and `scores` is polymorphic by design.

## Detection logic

### Cost normalisation (changes C1 and C5)

`_unit_cost()` in `checks.py` divides by `COST_INDEX[fy]`, returning constant
base-year prices. Both C1's peer comparison and C5's duplicate matching use it,
so neither compares 2024-25 cash against 2022-23 cash.

The peer ladder is deliberately **not** given an `fy` dimension. That would
split every peer group roughly threefold and push many under
`PEER_GROUP_MIN_ROWS`, making C1 skip far more often. Normalising removes the
year bias without shrinking the comparison set.

### C8 — vendor pricing and conduct (new, `subject_type = 'vendor'`)

Cap 30. Four components, summed then capped — the C7 pattern:

| Component | Points | Fires when |
|---|---|---|
| Prices above peers | 16 | vendor median ≥ 1.6× the work_type median, over ≥ 4 works |
| Concentration | 8 | ≥ 60% of a district+work_type's works, bucket ≥ 6 works |
| Works already flagged | 10 | ≥ 40% of the vendor's works already score ≥ 25 |
| Payment concentration | 8 | ≥ 45% of a district's payments, district total ≥ ₹1 crore |

Scored against the vendor, never against their works — for the same reason the
MP quota check is scored against the MP. Charging it per-work would flag every
contract that vendor ever won.

**No single component can alert alone** (max 16 against a 25-point threshold).
Price plus one corroborating component reaches 26. That is deliberate: a vendor
may hold most of a small district's work simply because few firms bid there.

Vendor alerts route to the **District Officer** of `vendors.district_id` — all
292 vendors have exactly one.

## Frontend

No frontend changes.

## Files to change

- `backend/config.py` — cost index, C8 thresholds, planted vendor count
- `backend/models.py` — allow `'vendor'` in `subject_type`
- `backend/generate_data.py` — inflate by FY, plant `vendor_overpricing`,
  de-collide in constant prices
- `backend/checks.py` — normalise `_unit_cost`, add C8 and vendor scoring

## Files to create

None. Both modules already existed.

## New dependencies

No new dependencies.

## Rules for implementation

All step-03 rules carry over. One addition:

- **`COST_INDEX` is read by both the generator and `checks.py`**, and that is a
  deliberate, narrow exception to the rule that checks must not read the
  generator's cost tables. The distinction is real and documented in
  `config.py`: the baseline unit cost is *our invented answer*, so scoring
  against it would be marking our own homework, whereas a price index is a
  *published economic fact* that a deployment would read from the WPI
  construction series. An officer deflating two years to constant prices before
  comparing them is doing ordinary analysis, not consulting the answer key.

## What the measurements forced

**1. The two halves cannot ship separately.** Modelling escalation without
teaching C1 about it makes detection worse, because a recent work is compared
at face value with older peers:

```
C1 clean-row false positives (% past the IQR fence)

  baseline (flat data, no deflation)      1.49%
  INFLATED data, checks do NOT deflate    1.70%
  INFLATED data, checks DO deflate        1.49%   restored exactly
```

**2. De-collision had to move to constant prices too.** This was a real
regression, caught only by re-running the step-02 guarantees: clean C5
duplicates jumped from 0 to **87**. Every one of them collided *only* after
deflation — the generator was de-colliding in nominal money while C5 compared
constant prices, so two works in different years could sit 18% apart in cash,
be declared clear, and land inside the 10% band once deflated. The sweep now
uses the same currency the check does, and the count is back to 0.

**3. C8's weighting had to be set by arithmetic, not taste.** At 14 points for
price, the strongest realistic pairing — consistently overpriced *and* works
already flagged — summed to **24**, one point below the alert threshold, so the
most informative vendors stayed silent. This is the same trap step 03 found
with C4 (cap 15 against a threshold of 25, so district alerts were impossible
by construction), reached by a different route. Price moved to 16.

Thresholds were sized against the measured clean spread rather than chosen:
the price component fires on 2 of 290 clean vendor+type pairs (0.7%) and
concentration on 6 of 1,478 eligible buckets (0.4%).

## Definition of done

Measured on the committed database.

- [x] Inflation present: median road unit cost rises across the dataset
- [x] **C5 clean accidental pairs back to 0** (the regression above), with
      18/20 planted pairs still detectable
- [x] Zero clean-row false positives on C2, C3 (both branches), C7 (both
      branches), C6
- [x] Clean works alert at **1.0%**
- [x] 4,938 subjects scored — 4,520 works, 73 MPs, 53 districts, 292 vendors.
      `subject_type='vendor'` inserts without `IntegrityError`
- [x] **2 vendor alerts, both planted, zero false positives.** The top five
      vendor scores are all planted
- [x] C8 components skip with a readable reason when a vendor has too few works
- [x] No single C8 component can alert alone
- [x] **Deterministic** — two runs give an identical score checksum
- [x] No alert below 25, none missing above 25; no FK violations
- [x] `grep` guards clean in `checks.py`
- [x] `COST_INDEX` read by both generator and checks, with the reasoning
      recorded in `config.py`

Recall is unchanged from step 03 within noise; the five checks that cap below
the alert threshold still bound it, and that remains a threshold-design
decision the team has chosen to defer.

Top vendor alert, Kashyap Enterprises, score 26: their works cost 2.2× the
median for the same work types across 18 jobs, and 8 of those 18 are already
flagged for verification.
