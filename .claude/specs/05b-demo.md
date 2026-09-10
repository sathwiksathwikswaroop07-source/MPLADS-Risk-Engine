# Spec: Demo seed data and polish

## Overview

Roadmap step 12. The engine was finished and honest — 77.6% recall, 1.16%
false-positive rate, deterministic — but the *demo* was not ready. This step
makes the data show what the system can actually do, and removes the friction
of presenting it live.

Written after implementation, to record what was built and the three
measurement problems the work uncovered.

## Depends on

Steps 01–08 and 10. Changes generation, evaluation and two small pieces of
scoring; adds no schema and no endpoints.

## API endpoints

No API changes.

## Database changes

No schema changes. Secondary ground-truth labels for stacked works are written
to `audit_log`, reusing `record_planted_subjects()` and the existing
`action = 'planted_anomaly'` convention that MP and vendor truth already use.

## Detection logic

Two threshold corrections, both of the same kind — a check whose maximum could
not reach `ALERT_MIN_SCORE`, making it decorative:

- **C3-MP skips members with no works.** Zero SC spend across zero works is
  arithmetically a total breach of both floors and awarded the full 48. It is
  missing data, not a compliance finding.
- **C8 corroborating components 8 → 9.** Price (16) plus any one of them summed
  to exactly 24, one point under the threshold.

No new checks. `checks.py` still cannot read any ground-truth label.

## Frontend

- `Worklist.jsx` — `critical` restored to the severity filter, now that the
  band is reachable.
- `Login.jsx` / `login.css` — click-to-fill demo account chips. They set the
  same three fields a human types and do not submit; the role remains a filter
  the server checks, never a claim.

## Files to change

- `backend/config.py` — stacked counts, combinations, pinned demo geography,
  C8 component weights
- `backend/generate_data.py` — stacked planting phase, guaranteed verified
  complaints, readable MP usernames, demo-district and demo-state pinning
- `backend/checks.py` — C3-MP no-works guard, `print_demo_pointers()`
- `backend/evaluate.py` — merge secondary labels, count distinct works
- `frontend/src/officer/Worklist.jsx`, `frontend/src/Login.jsx`,
  `frontend/src/login.css`
- `CLAUDE.md` — C3-MP 25 → 48, C8 weights, stacked-label rules, demo notes

## Files to create

- `DEMO.md`, `README.md` (rewrite), `frontend/README.md` (rewrite)

## New dependencies

None.

## Rules for implementation

- **Stacked works must earn their score.** Every component is a real planted
  anomaly detected by a real check. Nothing is awarded for being a demo row.
- **The primary label must be the C7 one.** `build_child_records` dispatches on
  `works.planted_anomaly` to set the payment ratio and withhold evidence, so
  the column has to carry the label whose signal lives in the child rows. Cost
  and delay are pure column mutations and need no such cooperation.
- **Never comma-join labels.** The column is read by exact equality in four
  places.
- **Count distinct `work_id`s in the totals.** A stacked work appears under
  both its labels — correctly — so summing the per-label columns would count it
  twice in recall and precision.
- The false-positive rate is the honesty guard. It must not rise.

## What the work uncovered

**1. The critical band was unreachable.** Every planted work carried exactly
one label and the largest single award is 35, so the ceiling was 50 against a
threshold of 70. `--sev-critical` was dead CSS and the worklist had removed the
filter option because the bucket was always empty. Fixed by planting 12 works
with two genuine problems each; 10 now reach critical. The other two fall short
because C1's IQR fence correctly declines to flag them — left alone, since
overriding the fence is the exact mistake the fence exists to prevent.

**2. Twenty Rajya Sabha members were being maximally flagged for having no
works.** They hold no works in the dataset, so SC and ST spend were both zero
over zero — arithmetically a total breach of both statutory floors, awarding
the full 48. All twenty ranked *above* the four members the generator
deliberately pushed under the floor, who scored 26.

`evaluate.py` could not see any of it: only works are in the false-positive
denominator, so twenty false accusations coexisted with a reported 100% recall
on `quota_shortfall`. This is the strongest argument in the codebase for the
subject-level FP gap being worth closing — a whole class of false positive was
invisible to the accuracy number.

**3. C8's components were calibrated one point short.** `config.py` already
recorded fixing this once, raising the price component 14 → 16 because "the
strongest realistic pairing summed to 24 and stayed silent one point below the
threshold". The same arithmetic still applied to both corroborating components:
a vendor priced 2.6× their peers holding 64% of a district's works of one type
scored exactly 24. Raising them to 9 lifted vendor recall from 16.7% to 50%
with zero clean-vendor false positives.

**4. Alert ids cannot be written down.** They are autoincrement keys on a table
`checks.py` deletes and rebuilds, so they shift whenever the generator changes.
`DEMO.md` therefore quotes none of its own: `checks.py` prints a Demo pointers
block and that is authoritative.

**5. Demo geography has to be pinned.** Left to the shuffle, the stacked works
scattered one per district across the country and the two demo districts opened
on a medium; all four quota shortfalls landed outside the demo state, so the
State Officer worklist — the whole point of that beat — was empty. One stacked
work is now pinned to each demo district and one shortfall to the demo state.

## Deferred

**District utilisation still cannot raise an alert.** `C4_MAX_POINTS` is 15
against a threshold of 25, and its two components are capped to 15 before
summing, so no district can ever alert on C4 alone. CLAUDE.md's demo notes
promised this beat; the note has been corrected rather than the scoring
quietly changed.

Unlike the C3-MP and C8 corrections — which removed false positives and
recovered findings already being made — closing this one means deciding that a
district *should* be alertable on utilisation alone, which changes what a score
means for a whole subject type. That is a scoring-contract decision and belongs
in its own step, not in a polish pass.
