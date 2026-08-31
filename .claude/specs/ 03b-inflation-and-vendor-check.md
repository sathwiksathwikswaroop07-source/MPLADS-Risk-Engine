# Spec 03b — Inflation normalisation and the vendor consistency check

## Overview

An amendment to Step 03, from a review of the scoring model. Two
additions, both of which close real gaps:

**1. C1 currently compares costs across years without adjusting for
inflation.** A road sanctioned in 2023 is compared directly against one
sanctioned in 2026 and looks artificially cheap. Every peer group
spanning multiple financial years carries this bias, and our dataset
spans three. C1 gains a normalisation step.

**2. Nothing checks a vendor against their own pricing history.** A
contractor charging ₹4.2 lakh/km on four rural roads and ₹9.8 lakh/km on
a fifth is a distinct pattern from "this work is expensive" — it is
selective pricing, and no existing check sees it. This becomes **C8**.

Both came out of a proposed grading model. The parts of that proposal
not adopted are recorded at the end, with reasons, so they are not
re-litigated later.

## Depends on

- Step 03 (`03-checks-scoring.md`) — the check contract, the peer-group
  ladder, the load-once architecture. Unchanged by this amendment.
- Spec 01b — the 15 work types.

---

## Change 1 — inflation normalisation in C1

### Config

```python
# Construction cost inflation, applied when comparing works sanctioned
# in different years. Indian construction input costs have run well
# above headline CPI; 3% is too low, and the value is tunable because
# it should be checked against a published index before submission.
CONSTRUCTION_INFLATION_RATE = 0.05

# Everything is normalised to this year's prices. Derived from
# REFERENCE_DATE so it can never drift independently.
INFLATION_BASE_YEAR = REFERENCE_DATE.year        # 2026
```

### Which date determines a work's price year

**`sanctioned_on`, not `completed_on`.** Two reasons, and the second
matters more:

A work's price is fixed at tender and sanction. A road sanctioned in
2022 and finished in 2026 was priced in 2022 money; using the completion
year would treat four years of construction as four years of price
inflation the contractor never received.

And `completed_on` is NULL for every unfinished work — which is exactly
the set most worth checking. Keying on it would silently skip every
in-progress and stalled work, the population C2, C2b and C7 exist to
catch.

Fallback order: `sanctioned_on` → `recommended_on` → `Skip("no date to
price against")`.

### The formula

```python
years = INFLATION_BASE_YEAR - price_year
normalised_unit_cost = unit_cost * (1 + CONSTRUCTION_INFLATION_RATE) ** years
```

Applied to **every work in the peer group and to the work being
scored**, before the median, quartiles and fence are computed. Not
pairwise projection of one work onto another — normalise the whole
group to a common base once, then the existing C1 logic runs unchanged
on normalised values.

Because both sides are adjusted to the same base year, an imperfect rate
largely cancels. A 2% error in the rate over a 3-year gap moves a
comparison by about 6%, well inside the IQR fence. Getting the *method*
right matters more than getting the rate exactly right.

### Fence-first still applies

Nothing else about C1 changes. Normalise, then compute
`q1`, `q3`, `median`, `fence = q3 + 1.5 × IQR`, then gate on the fence
and band on the ratio. A work inside the fence scores zero even at 2×
the median.

### The reason sentence must not confuse the officer

If the alert says "₹8.4 lakh per km" and the officer opens the record
and sees ₹7.2 lakh, they will conclude the system is broken — and they
will be right to. State the adjustment explicitly:

> Cost is ₹8.4 lakh per km at 2026 prices (₹7.2 lakh as sanctioned in
> 2023), against a median of ₹2.0 lakh for 47 comparable works. 4.2×.

`evidence` carries both figures and the rate, so the UI never has to
recompute:

```json
{
  "value_nominal": 720000,
  "value_normalised": 840000,
  "price_year": 2023,
  "base_year": 2026,
  "inflation_rate": 0.05,
  "median": 200000,
  "q1": 150000, "q3": 260000, "fence": 425000,
  "ratio": 4.2,
  "peer_count": 47,
  "peer_level": "work_type+terrain+area_type"
}
```

All peer statistics in `evidence` are **normalised** figures. Label them
that way in the UI or the numbers will not reconcile against the raw
records.

### The generator must deflate, or this breaks

**This is the interaction most likely to be missed, and it inverts the
result if it is.**

If `generate_data.py` prices a 2023 work and a 2026 work at the same
nominal rate, then normalisation inflates the 2023 one by 15% and it
becomes an outlier — the fix would *manufacture* false positives.

Clean works must be generated in **nominal money of their own sanction
year**:

```python
nominal_cost = base_cost / (1 + CONSTRUCTION_INFLATION_RATE) ** (
    INFLATION_BASE_YEAR - sanction_year
)
```

where `base_cost` is the `BASE_UNIT_COST` calculation at base-year
prices. Normalisation in C1 then undoes this exactly, and a clean 2023
work lands on the same normalised median as a clean 2026 one.

Verify with a direct query after regenerating: median nominal unit cost
per sanction year should *fall* going back in time, at roughly the
inflation rate. If it is flat across years, the generator is not
deflating and C1 will misfire on every older work.

### No effect on other checks

C5 compares works sanctioned within 60 days of each other, so inflation
between them is negligible — C5 keeps using nominal unit cost. C7 uses
payment ratios, which are dimensionless. C2, C2b, C3, C4 and C6 do not
touch cost.

---

## Change 2 — C8, vendor price consistency

### What it catches

A vendor whose pricing is internally inconsistent. Not "this vendor is
expensive" — that is C1's job, and a consistently expensive vendor is a
procurement question, not an anomaly. C8 fires when a vendor prices *one
work* far above what they themselves charge for the same kind of work
elsewhere.

This is a different shape of problem from C1, and either can fire
without the other:

| Situation | C1 | C8 | Reading |
|---|:--:|:--:|---|
| Expensive vs peers, normal for this vendor | ✅ | ❌ | Vendor is consistently dear |
| Normal vs peers, 3× this vendor's own rate | ❌ | ✅ | Selective pricing |
| Expensive both ways | ✅ | ✅ | The strongest cost signal available |

### Config

```python
C8_MAX_POINTS = 15
C8_MIN_PRIOR_WORKS = 3          # by the same vendor, same type + area_type
C8_RATIO_BANDS = (              # vs the vendor's own median
    (1.6, 6),
    (2.2, 11),
    (3.0, C8_MAX_POINTS),
)
COST_POINTS_COMBINED_CAP = 40   # C1 + C8 together
```

### Algorithm

1. Work has a `vendor_id`. If NULL → `Skip("no vendor recorded")`.
2. Collect that vendor's **other** works with the **same `work_type`
   and same `area_type`**. Exclude the work being scored.
3. Fewer than `C8_MIN_PRIOR_WORKS` (3) → `Skip("vendor has only N
   comparable works")`. Comparing against one prior job is noise.
4. Normalise every unit cost — the vendor's history spans years, so the
   same base-year adjustment as C1 applies. Without it C8 would flag
   every vendor whose older jobs were cheaper, which is all of them.
5. `ratio = this work's normalised unit cost / median of the vendor's`.
6. Band with `C8_RATIO_BANDS`.

Same `work_type` **and** `area_type` is not optional. A vendor's rural
road rate and metro road rate should differ — that is what
`AREA_COST_MULTIPLIER` exists to model. Comparing across area types
would flag every vendor who works in both.

### Points column

C8 writes to **`cost_points`**, alongside C1, and the combined value is
capped at `COST_POINTS_COMBINED_CAP` (40).

They stack rather than exclude, because both firing genuinely is worse
than either alone. The cap stops one underlying fact — "this work is
expensive" — from taking 50 of the 100 available points and drowning
out delay, compliance and evidence signals.

No new column, no schema change. If a vendor-inconsistency dashboard is
wanted later, adding a `vendor_points` column to `scores` is cheap,
since `checks.py` rebuilds that table on every run.

### Reason sentence

State the fact. Do not speculate about cause.

> This vendor's four other rural single-lane roads averaged ₹4.2 lakh
> per km at 2026 prices. This one is ₹9.8 lakh per km — 2.3×.

Evidence: `{vendor_median, value_normalised, ratio, prior_count,
work_type, area_type}`.

### The caveat that belongs in the UI

Different districts have genuinely different haulage distances, quarry
access and labour rates, so the same vendor can legitimately price
differently in two rural districts. C8 is a question for a verifier, not
a finding. The alert detail should say so in one line — and this is the
same discipline as *a costly road may be a hilly road*.

---

## Change 3 — generator changes this forces

Three, and the first is a blocker.

### Vendors must specialise, or C8 never runs

With 300 vendors over 6,000 works, each vendor averages 20 works. Spread
across 15 work types and 4 area types, that is about **0.3 works per
(vendor, type, area_type) bucket** — `C8_MIN_PRIOR_WORKS = 3` would
essentially never be met and the check would skip on every row.

Real contractors specialise. Model it:

- Reduce vendors to **~200**, giving ~30 works each.
- Assign each vendor **1–2 work types** they specialise in and **1–2
  districts** they operate in.
- A vendor's works then concentrate into 2–4 buckets of 6–12 works,
  which C8 can use.

Verify after generating: at least 70% of works with a vendor should have
≥ 3 comparable prior works by that vendor. Below that, C8 is decorative.

### Costs must be deflated to sanction-year money

Per Change 1. Without it, normalisation manufactures false positives on
every older work.

### A planted label for C8

A new check needs ground truth or `evaluate.py` cannot measure it. Add
to `PLANTED_ANOMALY_COUNTS`:

```python
"vendor_price_spike": 30,
```

Planted by taking a vendor with an established history in one bucket and
pricing a single work at 2.5–4× their own normalised median — while
keeping it **inside** the general peer-group fence where possible, so it
tests C8 specifically rather than being caught incidentally by C1.

Total planted rises from 290 to **320** work-level labels, plus the 4
quota-shortfall MPs.

The clean-row guard extends too: no unplanted work may sit above
`C8_RATIO_BANDS[0]` (1.6×) of its vendor's own median. Add this to the
de-collision pass.

---

## Considered and not adopted

Recorded so these do not resurface.

**Inverting the scale to 100 = good, alert below 50.** The `scores`
table, `SEVERITY_BANDS`, `ALERT_MIN_SCORE`, the worklist sort and all of
spec 03 are built on 0 = clean, 100 = risky. Beyond the rework, "Risk 78
— here is why" is what an alert system says; a quality score of 22 makes
the officer subtract every time, and it reads as grading the MP rather
than flagging a record for verification.

**Alerting below 50%.** On a 100-point quality scale that would alert on
roughly half of 6,000 works. Three thousand alerts is not a worklist.
`ALERT_MIN_SCORE = 25` on the risk scale yields 5–7%, which is a
morning's work for a district officer — the number to design against.

**Pairwise comparison against one or two prior works.** If the
comparison work is itself an outlier, the whole range is wrong. A median
over ≥ 8 peers cannot be moved by one bad row, which is why
`PEER_GROUP_MIN_ROWS` exists. Kept.

**Raising delay to 30% of the score.** Delay is the most common
condition in government works and often legitimate — land acquisition,
monsoon, a court stay. Weighted that heavily, the top of the worklist
fills with ordinary late projects while cost anomalies sink. C2 stays at
25 against C1's 35.

**Public opinion as a direct 10-point score.** Brigadable: ten people
from one group could push a work to the top of an officer's list. C6
stays as it is — only *verified* complaints, only *distinct* logged-in
users, hard cap at 15. A citizen report is a signal for an officer to
verify, never a score the public sets.

**A flat "completed a month early is suspicious" rule.** Already covered
by `C7_IMPLAUSIBLY_FAST`, which uses a fraction of expected duration
rather than a flat number of days — a borewell finishing a month early
is normal; a major bridge finishing a month early is not.

---

## Files to change

- `backend/config.py` — `CONSTRUCTION_INFLATION_RATE`,
  `INFLATION_BASE_YEAR`, `C8_MAX_POINTS`, `C8_MIN_PRIOR_WORKS`,
  `C8_RATIO_BANDS`, `COST_POINTS_COMBINED_CAP`, and
  `PLANTED_ANOMALY_COUNTS["vendor_price_spike"] = 30`
- `backend/generate_data.py` — vendor specialisation, sanction-year
  deflation, the new planted label, extended clean-row guard
- `backend/checks.py` — normalisation inside the peer index; new
  `check_c8_vendor_consistency`
- `backend/evaluate.py` — report recall for `vendor_price_spike`
- `.claude/specs/03-checks-scoring.md` — amendment pointer
- `CLAUDE.md` — add C8 to the scoring table; note the inflation
  normalisation under C1

---

## Definition of done

Inflation:

- [ ] Median **nominal** unit cost by sanction year falls going back in
      time at roughly `CONSTRUCTION_INFLATION_RATE` — proves the
      generator deflates
- [ ] Median **normalised** unit cost by sanction year is flat across
      years — proves normalisation undoes it
- [ ] C1's clean-row fence clearance is no worse than the pre-change
      figure (was 1.32%). **If it jumped, the generator is not
      deflating**
- [ ] A work sanctioned in 2023 and one in 2026 with identical
      normalised cost receive identical C1 points
- [ ] Every C1 reason sentence states both the nominal and base-year
      figure, and names the sanction year
- [ ] Works with no `sanctioned_on` and no `recommended_on` are skipped,
      not priced at base year

C8:

- [ ] ≥ 70% of works with a vendor have ≥ 3 comparable prior works —
      otherwise C8 skips too often to matter
- [ ] C8 skips, with a reason, when `vendor_id` is NULL or the sample is
      short
- [ ] C8 never compares across `area_type` or `work_type`
- [ ] `cost_points` never exceeds `COST_POINTS_COMBINED_CAP` (40) on any
      row
- [ ] `vendor_price_spike`: 30 planted, recall recorded by
      `evaluate.py`
- [ ] No unplanted work exceeds 1.6× its vendor's own normalised median
- [ ] A vendor who is uniformly expensive triggers C1 but **not** C8 —
      construct one by hand and confirm

Unchanged behaviour:

- [ ] Two runs of `checks.py` still produce identical scores
- [ ] Total planted work-level labels: 320
- [ ] C5, C7 and the rest are unaffected — their counts match the
      pre-change run