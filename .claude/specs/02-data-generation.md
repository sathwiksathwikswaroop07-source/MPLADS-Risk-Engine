# Spec: Dummy Data Generator With Planted Anomalies

## Overview

Fills `backend/mplads.db` with ~4,500 works across 10 states and 53
districts, of which 290 carry a `planted_anomaly` label and the rest must be
clean. Written after the fact to record what was built and, more usefully,
the measurements that forced several of the design decisions.

Step 01 left every table empty. Nothing downstream works without data: step
03 needs peer groups to take medians against, step 08 needs ground truth to
measure recall, steps 04–07 need works and logins to serve.

## Depends on

Step 01 — schema, config, engine. No other step.

## API endpoints

No API changes.

## Database changes

No schema changes. `backend/config.py` gains generation constants only:
`BASE_UNIT_COST`, `AREA_COST_MULTIPLIER`, `TERRAIN_COST_MULTIPLIER`,
`COST_NOISE_SIGMA`, `RANDOM_SEED`, `TARGET_WORK_COUNT`, `FISCAL_YEARS`,
`PLANTED_ANOMALY_COUNTS`, and the clean-row guard rails.

These live in config rather than in the generator because `evaluate.py` needs
to know what "normal" was in order to plant a work at 4× normal. `checks.py`
must never read them — scoring against our own generation baseline would be
marking our own homework.

## Detection logic

No detection logic. This step only produces the data that step 03 scores.

## Frontend

No frontend changes.

## Files to change

- `backend/config.py` — generation constants appended

## Files to create

- `backend/generate_data.py`

## New dependencies

- `faker` — generated MP, vendor and place names
- `werkzeug` — password hashing for the seeded demo accounts

## Rules for implementation

Project-wide rules from CLAUDE.md apply. The ones that bit hardest here:

- **SQLAlchemy 2.x ORM.** No raw `sqlite3`, no string-formatted SQL.
- **Determinism.** One seeded `random.Random` instance threaded through every
  function; `Faker.seed()` alongside it. Never the global `random` module.
  Iterate sorted collections only.
- **No `date.today()` / `datetime.now()`.** Every date derives from
  `REFERENCE_DATE`.
- **Money is `Integer` rupees; dates are ISO-8601 strings.**
- **`checks.py` must never read** `planted_anomaly`, `is_hill_district`,
  `default_area_type`, or the `BASE_UNIT_COST` family.
- **No real identity data.** PANs are hashes; names are generated.

Step-specific:

- **Clean rows must stay clean.** A clean row that trips a check is a real
  false positive. The generator actively prevents this rather than hoping.
- **`quota_shortfall` is MP-level** and writes no work-level label — C3-MP
  scores the MP, and recall has to be measured against the same subject type.

## What the measurements forced

Three findings changed the implementation:

**1. C5 collides by chance, badly.** C5 pairs works in the same district and
work_type within 10% unit cost and 60 days. At this dataset size that happens
~455 times by chance against 20 planted pairs — a 23× swamp. Widening the
cost spread does not fix it (log-sd 0.55 still leaves ~278). Clean works are
now actively de-collided after generation.

**2. The de-collision oscillated.** Fixing one pair at a time pushes work X
off Y and onto Z, then back onto Y — the same four collisions were re-fixed
on all twelve sweeps, forever. The fix moves a work clear of its *whole*
neighbourhood at once.

**3. Direction matters.** Nudging costs *upward* piles works into the peer
group's upper tail and trips C1's IQR fence — trading one false positive for
another (C1's 2×-median rate went 0.64% → 2.25%). Nudging downward, below the
cheapest neighbour, satisfies both checks.

**Cost-noise sigma is bounded on both sides.** The IQR fence flags 1–4% of
clean rows whatever sigma is chosen; that is inherent to a right-skewed
distribution. What matters is where they land, because C1 is fence-gate then
ratio-band — a work clearing only the fence scores 10, below the 25-point
alert threshold:

```
sigma   clears fence   -> 10 pts only   -> 20+ pts
 0.20        1.47%           1.40%          0.08%
 0.28        2.03%           1.50%          0.53%
 0.35        2.52%           0.61%          1.91%
 0.45        3.33%           0.05%          3.28%
```

At 0.35+ clean rows start earning alert-grade points; below 0.25 costs look
implausibly uniform. `COST_NOISE_SIGMA = 0.28`.

## Definition of done

Measured on the committed database.

- [x] `python -m backend.generate_data` runs clean; 4,520 works
- [x] 290 work-level planted anomalies, every label at its exact target,
      plus 4 quota-shortfall MPs
- [x] **Deterministic** — two consecutive runs give an identical checksum
      over `works` ordered by `work_id`
- [x] FK pragma live, `PRAGMA foreign_key_check` returns 0 rows
- [x] **Zero false positives on clean rows** for C2, C3 (both branches),
      C6, C7 (both branches), and C5
- [x] C1 clean rows: 1.32% clear the fence (10 pts, no alert), 0.80% pass
      2× median — under the 1% target
- [x] Planted anomalies detectable: long_delay 80/80, impossible_date 20/20,
      ineligible_work 20/20, ghost_asset 30/30, payment_ahead 40/40,
      cost_overrun 57/60 past the fence, duplicate_pair 19/20
- [x] 375 works with `progress_pct = 0` and no `progress_updates` rows, so
      step 03's graceful-degradation path is exercised by the data
- [x] `do.pune` and `do.nashik` exist in different districts with scrypt
      hashes
- [x] `grep` guards clean: no `date.today` / `datetime.now`, no `SELECT *`,
      no "fraud/scam/corrupt"
- [x] `BASE_UNIT_COST` appears only in `config.py` and `generate_data.py`;
      `is_hill_district` only in `models.py` and `generate_data.py`

Eleven rung-3 peer groups sit under `PEER_GROUP_MIN_ROWS`, which is the
ladder working as designed — those works fall through to rung 4 or 5.

The real proof lands at step 03: run `checks.py` and confirm planted
anomalies score high while clean rows stay under 25.
