# Step 08 — Accuracy evaluation

## Overview

`evaluate.py` answers one question: **is `checks.py` any good?**

It is the only file in the project permitted to read
`works.planted_anomaly`. `checks.py` scores 6,000 works blind; this
script opens the answer key and marks the paper.

It produces two numbers:

- **Recall** — of the anomalies we planted, how many did we catch?
- **False-positive rate** — of the clean works, how many did we wrongly
  flag?

Both matter, and only reporting the first is the most common way an
accuracy claim becomes dishonest. A system that flags everything has
100% recall and is worthless.

## Not part of the product

Nobody logs in and uses this. It writes nothing to the database. It
reads, counts, prints, exits.

**On real MPLADS data it cannot run at all**, because `planted_anomaly`
would be empty — nobody labels real irregularities in advance. In a
deployment this file is deleted. It exists to prove the detection works
before anyone trusts it with real data.

## Why it comes now, not last

The roadmap lists this as step 08, after the screens. **Build it
immediately after `checks.py` instead.**

It is the feedback loop for threshold tuning. Without it you change
`C5_UNIT_COST_TOLERANCE` from 0.10 to 0.15 and have no idea whether you
improved anything. With it you see duplicate recall go 45% → 78% and
know. That loop runs twenty or thirty times, and every run before this
file exists is guesswork.

## Depends on

- Step 02 — planted labels in `works.planted_anomaly`
- Step 03 — populated `scores` and `alerts`

Run `checks.py` first, always. Evaluating a stale `scores` table
silently reports last run's numbers.

---

## Files

```
backend/
└── evaluate.py     ← NEW
```

No config changes. No schema changes. No new dependencies.

Roughly 100 lines. This is the simplest file in the backend — counting
and division. All the intelligence is in `checks.py`.

---

## What it computes

### 1. Recall, per label

For each label in `config.PLANTED_ANOMALY_COUNTS`:

```
planted  = works with that planted_anomaly
caught   = those that have an alert
recall   = caught / planted
```

### 2. Caught by any check vs by the intended check

**Report both.** They are different questions and the gap between them
is informative.

A work planted as `cost_overrun` that alerted only because C2 fired on
its delay was flagged for the wrong reason. The officer arrives looking
for the wrong thing. Counting that as a catch inflates the number.

```
caught_any      → the work has an alert, from any check
caught_intended → the alert's reasons_json contains the check that
                  should have caught this label
```

Label-to-check mapping (put it in `evaluate.py`, not `config.py` — it
exists only for measurement and `checks.py` must never see it):

| Label | Intended check |
|---|---|
| `cost_overrun` | C1 |
| `long_delay` | C2 |
| `impossible_date` | C3 |
| `ineligible_work` | C3 |
| `duplicate_pair` | C5 |
| `payment_ahead_of_work` | C7 |
| `ghost_asset` | C7 |
| `vendor_price_spike` | C8 |
| `quota_shortfall` | C3-MP (MP-level) |

If `caught_any` is high and `caught_intended` is low, the score is
right by accident. That is worth knowing before a judge finds it.

### 3. False positives

```
clean            = works with planted_anomaly IS NULL
false_positives  = clean works that have an alert
fp_rate          = false_positives / clean
```

**Count the no-progress works in this denominator.** The
`WORKS_WITHOUT_PROGRESS_DATA` rows are clean works, so if any of them
alerts, that is a genuine false positive — and specifically it says the
graceful-degradation path is broken. Excluding them would hide the bug
they exist to expose.

The likely cause if they do appear: when a work has no
`progress_updates` rows, `progress_pct = 0` means *unknown*, not
*nothing done*. C7's payment-gap component must skip rather than compute
a huge gap against a zero it should not trust. Fix that in `checks.py`,
not here.

### 4. False positives broken down by check

Which check is producing them:

```
C1  88 of 141
C5  31 of 141
C7  22 of 141
```

Without this you know the rate is 3.4% and have no idea what to tune.
With it you go straight to `COST_NOISE_SIGMA` or
`C5_UNIT_COST_TOLERANCE`.

### 5. MP-level, separately

`quota_shortfall` is planted on MPs, not works. Its recall is measured
against `scores` rows with `subject_type = 'mp'` — never mixed into the
work-level totals. Mixing subject types makes both numbers wrong.

---

## Output

One table, readable at a glance, because you will read it thirty times.

```
MPLADS Risk Engine — accuracy against planted ground truth
REFERENCE_DATE 2026-09-15 · 6,000 works · 320 planted · 4 planted MPs

WORK-LEVEL RECALL
Label                    Planted   Any   Intended   Recall
cost_overrun                  60    54         52    86.7%
long_delay                    80    78         78    97.5%
impossible_date               20    20         20   100.0%
ineligible_work               20    19         19    95.0%
duplicate_pair                40    33         31    77.5%
payment_ahead_of_work         40    37         36    90.0%
ghost_asset                   30    26         25    83.3%
vendor_price_spike            30    24         21    70.0%
──────────────────────────────────────────────────────────
TOTAL                        320   291        282    88.1%

MP-LEVEL
quota_shortfall                4     4          4   100.0%

FALSE POSITIVES
141 of 5,680 clean works alerted            2.5%
  by check:  C1 88 · C5 31 · C7 22

SEVERITY OF FALSE POSITIVES
  critical   0
  high       12
  medium    129
```

That last block matters more than it looks. A false positive at medium
severity costs an officer a glance. One at critical costs a site visit.
**Zero critical false positives** is a much stronger claim than a low
overall rate, and it is the honest way to present an imperfect number.

Exit code 0 always — this is a report, not a test that fails a build.

---

## Optional: write a JSON summary

If time allows, also write `backend/evaluation.json` with the same
numbers. A "System Accuracy" page in the Ministry portal can then render
it without exposing `planted_anomaly` through the API.

**If you build that page, label it as measured against test data.** In a
real deployment the number would not exist. Presenting it as live
accuracy on real works would be a false claim, and it is exactly the
kind of thing a MoSPI judge would catch.

Only build it once the officer worklist and alert detail are finished.
It is polish.

---

## Rules for implementation

- **The only file that may read `planted_anomaly`.** `checks.py` is
  grepped for it in step 03's DoD; this file is the exception.
- **Reads only. Writes nothing to the database**, not even an
  `audit_log` row.
- Bulk-read with `text()` and named columns. No `SELECT *`.
- **No `date.today()`.** Not needed — nothing here is time-dependent.
- Deterministic: same database in, same numbers out.
- Round percentages once, at print time. Never round mid-calculation.
- Handle `planted = 0` for a label without dividing by zero — print `—`,
  not `0.0%`. A label with nothing planted was not measured; that is
  different from being missed entirely.

---

## How to use it

```bash
python -m backend.checks && python -m backend.evaluate
```

Always chained. Evaluating without re-running checks reports the
previous run's scores against your current expectations, which is how
you end up chasing a fix that already worked.

The tuning loop:

```
read the table → change ONE number in config.py → re-run both → compare
```

One number at a time. Change three and you cannot tell which helped,
and threshold interactions are not intuitive — tightening C5 changes
C1's false positives, because the de-collision perturbs costs.

**Record each run.** A short log of `sigma 0.28 → C1 FP 1.4%` beats
re-deriving it later, and it becomes the calibration story if a judge
asks how you chose your thresholds.

---

## Targets

Not pass/fail — direction to tune toward.

| Metric | Target | Comment |
|---|---|---|
| Overall recall | > 85% | Below 75% something is broken, not mistuned |
| Recall, any single label | > 70% | One weak label is acceptable; two suggests a systematic issue |
| False-positive rate | < 5% | Above 10% the worklist stops being credible |
| Critical false positives | **0** | The one to hold firm on |
| `caught_intended` / `caught_any` | > 0.90 | Below this, scores are right by accident |

**A recall of 88% with a 3% false-positive rate is a genuinely good
result and should be presented as-is.** Do not tune toward 99% — you
would get there by loosening thresholds until everything alerts, and the
false-positive column would give you away to the first judge who reads
the whole table.

---

## Definition of done

- [ ] `python -m backend.evaluate` prints the table and exits 0
- [ ] Every label in `PLANTED_ANOMALY_COUNTS` appears, including any at
      0% — a silently missing row hides a check that never fires
- [ ] `planted` counts match `PLANTED_ANOMALY_COUNTS` exactly. A
      mismatch means the generator did not plant what it claimed
- [ ] Both `caught_any` and `caught_intended` are reported
- [ ] `quota_shortfall` is measured against `subject_type = 'mp'`, and
      is not in the work-level total
- [ ] False-positive denominator is all clean works, including the
      no-progress ones
- [ ] False positives are broken down by check and by severity
- [ ] Running it twice without re-running `checks.py` gives identical
      output
- [ ] `grep -rn "planted_anomaly" backend/` matches only `models.py`,
      `generate_data.py` and `evaluate.py` — **never `checks.py`**
- [ ] Nothing was written: row counts in `scores` and `alerts` are
      unchanged after a run

Then the judgement call that no checklist covers: read the table and ask
whether you would defend these numbers out loud. If a label sits at 40%,
either fix it or be ready to say why it is hard — *"duplicate detection
is our weakest check at 77%, because near-identical works occur
legitimately and we chose to keep the false-positive rate low"* is a
better answer than a number you cannot explain.