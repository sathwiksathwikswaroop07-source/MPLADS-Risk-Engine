# Step 03 — Detection checks and scoring

## Overview

This is the product. Everything before it was plumbing; everything after
it is presentation.

`checks.py` reads the populated database, runs nine checks across three
subject levels, and writes:

- a **`scores` row for every subject** — every work, every MP, every
  district, including the clean ones that score 3 or 0;
- an **`alerts` row only where `total_score >= ALERT_MIN_SCORE`** (25).

It is a batch script, not a service. `python -m backend.checks` from
scratch every time.

**Nothing here may be non-deterministic.** Two runs on the same database
must produce identical scores, identical reason sentences, identical
alert counts. Step 08 measures this against planted ground truth, and a
recall number that moves between runs is worthless.

> **Amended by `03b-inflation-and-vendor-check.md`.** Two additions:
> C1 normalises every unit cost to base-year prices before taking the
> median, and a new **C8** compares a work against its own vendor's
> pricing history (max 15, writes to `cost_points`, combined cap 40).
> 03b is the authority on both. Everything else here stands.

## Depends on

- Step 02 — populated database with planted anomalies.

## Verify before writing a line

```sql
SELECT fy, COUNT(*) FROM works GROUP BY fy ORDER BY fy;
```

`REFERENCE_DATE` is 15 September 2026, which sits inside **FY 2026-27**.
C4's calendar half compares spend-to-date against the share of the
*current* financial year elapsed — so if your newest works are FY
2025-26, there is no current year to measure and C4's first component
can never fire.

Two honest options if that query shows no 2026-27 rows: regenerate with
works in the current FY, or accept that C4 runs on its Q4-bunching half
only and **records the other half as skipped**. Do not quietly move
`REFERENCE_DATE` to fit the data — it is pinned for reproducibility and
half the DoD greps exist to keep it that way.

---

## Files

```
backend/
└── checks.py       ← NEW, this step
```

`config.py`, `models.py`, `db.py` unchanged. **No new thresholds may be
invented in `checks.py`** — every number it uses already exists in
`config.py`, and if one does not, it is added there first.

---

## The three hard prohibitions

Grepped in the Definition of Done. Each one, if violated, silently
invalidates the accuracy number rather than causing an error.

| Never read | Why |
|---|---|
| `works.planted_anomaly` | It is the answer key. Reading it makes recall fake, and a judge can catch it in one grep |
| `districts.is_hill_district`, `districts.default_area_type` | Generation hints. The work's own `terrain` and `area_type` are the truth; a flat road in a hill district must not be excused |
| `BASE_UNIT_COST`, `AREA_COST_MULTIPLIER`, `TERRAIN_COST_MULTIPLIER` | Our own generator's cost model. Scoring against it is marking our own homework |

C1 compares a work against **its actual peers in the data** — never
against a constant we chose.

---

## Architecture

### Load once, score in memory, write once

The naive shape — for each of 4,500 works, run a peer-group query — is
4,500 round trips plus 4,500 median computations, and it turns a
two-second script into minutes. That matters more than it sounds:
step 08 puts you in a tune-and-re-run loop you will execute twenty or
thirty times, and a slow `checks.py` makes that loop miserable enough
that you will stop tuning.

4,500 works is nothing in memory. The shape is:

```
1. One bulk read per table   → plain Python objects/dicts
2. Precompute every aggregate and index
3. Score everything in pure Python — no database access inside a check
4. One bulk write of scores, then reconcile alerts
```

**No check function may touch the session.** A check takes a context
object and returns a result. That makes each one unit-testable without a
database and guarantees the "load once" discipline cannot rot.

### Use `text()` for the bulk reads

Per the stack rules: SQLAlchemy ORM for CRUD, `text()` with bound
parameters for analytics. The reads here are analytical.

```python
rows = session.execute(text("""
    SELECT work_id, mp_id, district_id, constituency_id, work_type,
           terrain, area_type, quantity, estimated_cost, final_cost,
           recommended_on, sanctioned_on, expected_completion_on,
           completed_on, status, progress_pct, last_updated_on
    FROM works
""")).mappings().all()
```

Name every column. No `SELECT *` — a schema change must fail loudly.

### Precomputed indexes

Build these once, before scoring:

| Index | Shape | Feeds |
|---|---|---|
| `payments_by_work` | `work_id → sum(amount)` | C7 |
| `evidence_count_by_work` | `work_id → count` | C7 |
| `photo_hash_owners` | `photo_hash → [work_id, …]` | C7 duplicate photo |
| `last_progress_by_work` | `work_id → max(reported_on)` | C2b, C7 |
| `verified_complaints_by_work` | `work_id → count(distinct user_id)` | C6 |
| `mp_terms` | `mp_id → (term_start, term_end)` | C3 |
| `district_state` | `district_id → state_id` | peer ladder rung 2 |
| `PeerIndex` | see below | C1 |

`photo_hash_owners` is the one worth care: a hash appearing under two
different `work_id`s is the C7 duplicate-photo signal. Hashes appearing
twice under the *same* work are not — a work may legitimately have the
same photo attached twice.

---

## The check contract

Every check returns exactly one of three things. The distinction between
the last two is the whole graceful-degradation requirement.

```python
@dataclass(frozen=True)
class Finding:
    check: str        # "C1"
    points: int       # > 0, already clamped to that check's max
    reason: str       # a human sentence, with real numbers
    evidence: dict    # the numbers the UI charts

@dataclass(frozen=True)
class Skip:
    check: str
    why: str          # "no quantity recorded"

# and None — the check ran, found nothing, awarded zero
```

Three outcomes, three meanings:

- `Finding` → ran, something is off.
- `None` → **ran, nothing wrong.** This is a positive result.
- `Skip` → **could not run.** Missing field, peer group too small.

A check that cannot produce a readable `reason` may not award points.
A check that cannot run must say why. Never crash, never silently
score zero — a zero that means "clean" and a zero that means "we had no
data" are different facts, and conflating them is how a system starts
lying to an officer.

`Skip` reasons land in `scores.checks_skipped`, which is what lets the
alert page say *"5 of 8 checks ran; payment and evidence checks require
authenticated eSAKSHI data."* That sentence tells a judge you know
exactly what your system needs and that it degrades honestly.

---

## Work-level checks

Cost convention, everywhere: `cost = COALESCE(final_cost,
estimated_cost)`, `unit_cost = cost / quantity`. Never `final_cost`
alone — it is NULL for every unfinished work, which would drop exactly
the works most likely to be problems.

### C1 — cost outlier → `cost_points`, max 35

The core of the project.

**Peer group.** Walk `PEER_GROUP_LADDER` in order, stop at the first rung
with `>= PEER_GROUP_MIN_ROWS` (8) rows. If even `("work_type",)` falls
short → `Skip("peer group too small: 5 rows at the widest rung")`.

Build all five rungs once into a `PeerIndex` keyed by the tuple of
grouping values. Each entry holds `median`, `q1`, `q3`, `count`, and the
rung's name.

**Exclude the work being scored from its own peer statistics.** With 8
peers a single 6× outlier drags the median enough to partly excuse
itself. Cheap fix: compute the group's stats including everything, then
for each work recompute excluding it — or simply require the group to be
large enough that one row cannot dominate. State which you chose in a
comment.

**Fence first, then band.** These are two different scales and they can
disagree; the rule resolves it:

```
fence = q3 + C1_IQR_MULTIPLIER * (q3 - q1)

if unit_cost <= fence:
    return None                    # inside normal spread — zero, even at 2x median
points = C1_FENCE_POINTS           # 10, for clearing the fence
ratio = unit_cost / median
for multiple, band_points in C1_RATIO_BANDS:
    if ratio >= multiple:
        points = band_points
return Finding("C1", points, ...)
```

A work at 2× the median that sits inside the fence scores **zero**. In a
tightly clustered peer group, 2× can still be ordinary. Awarding ratio
points without clearing the fence is how a peer group of cheap borewells
starts flagging half of itself.

**Reason template:**

> Cost per km is ₹8.4 lakh against a median of ₹2.0 lakh for hilly metro
> roads (4.2×), above the normal range for 47 comparable works.

**Evidence:** `{value, median, q1, q3, fence, ratio, peer_count,
peer_level}`. `peer_level` is the rung name, so the UI can say what the
comparison was against. The frontend must never recompute a number that
is not in here.

### C2 — delay → `delay_points`, max 25

Days overdue while `status != "completed"`, measured from
`REFERENCE_DATE` against `sanctioned_on`. Band with `C2_DELAY_BANDS`.

`sanctioned_on` NULL → `Skip("not yet sanctioned")`. A work still at
`recommended` cannot be late; it has no clock running.

### C2b — predicted stall → `delay_points`, max 8

**Only runs if C2 awarded nothing.** Both write to `delay_points`, so a
badly overdue work that is also stale would be charged twice for one
problem. Enforce with an explicit guard, not by hoping the conditions
never overlap:

```python
c2 = check_c2_delay(ctx)
c2b = check_c2b_stall(ctx) if c2 is None else None
```

C2b is for works that are **not yet late** — that is what makes it an
early warning rather than a second delay penalty.

Fires when **both** hold:

- elapsed share of expected duration exceeds reported progress by more
  than `C2B_PROGRESS_SHORTFALL` (0.30), and
- no `progress_updates` row in `C2B_STALE_DAYS` (90).

Expected duration comes from `expected_completion_on` where stored,
falling back to `EXPECTED_DURATION_DAYS[(work_type, area_type)]`, then
`DEFAULT_DURATION_DAYS`.

No progress history at all → `Skip("no progress updates recorded")`.
That is the path your 400 deliberately data-less works exercise, and
step 08 must not count them as false positives.

### C3 — work compliance → `compliance_points`, max 15

Rule violations. **Highest single one, never stacked** — a work with two
impossible dates is one data-integrity problem, not two.

| Condition | Points |
|---|---|
| `completed_on < sanctioned_on` | 15 |
| `sanctioned_on < recommended_on` | 15 |
| any date after `REFERENCE_DATE` | 15 |
| `recommended_on` outside the MP's term | 12 |
| `work_type` or description matches `NOT_PERMITTED_WORK_CATEGORIES` | 15 |

Description matching is substring, case-insensitive, on a normalised
string. Keep it dumb and predictable — a fuzzy matcher that a judge
cannot reproduce by eye is worse than a crude one they can.

### C5 — duplicate → `duplicate_points`, max 20

Another work with the same `district_id`, same `work_type`, unit cost
within `C5_UNIT_COST_TOLERANCE` (10%), sanctioned within
`C5_WINDOW_DAYS` (60).

**Both works get the finding, each naming the other.** Neither is "the
original" — the system cannot know which, and asserting one would be an
accusation it is not entitled to make.

Compute pairs once by bucketing on `(district_id, work_type)` and
comparing within buckets, not with an O(n²) sweep across all 4,500.
Order pairs by `work_id` so the output is deterministic.

**Reason:** *"Near-identical to work #2841 in the same district — same
type, unit cost within 4%, sanctioned 23 days apart."*

### C6 — citizen reports → `public_points`, max 15

Count of **verified** complaints with distinct `user_id`. Band with
`C6_REPORT_BANDS` (1 → 5, 2–3 → 10, 4+ → 15). Hard cap.

Unverified complaints score nothing. They appear in the alert detail as
context, but an unverified report cannot move a number that triggers an
officer's visit — otherwise the score becomes a brigading target. The
`UNIQUE(work_id, user_id)` constraint is the other half of that
protection.

### C7 — paid, no proof of work → `evidence_points`, max 35

The ghost-asset check. Components **sum**, then clamp to 35. No single
component is conclusive; the combination is.

| Component | Points |
|---|---|
| `payment_ratio − progress_ratio` past `C7_PAYMENT_GAP_BANDS` | 10 / 18 / 25 |
| `status == completed` and zero evidence rows | 15 |
| No update in `C7_STALE_DAYS` (180) while payment ratio > 0.50 | 12 |
| Completed in under `C7_FAST_FRACTION` (0.15) of expected duration | 12 |
| A `photo_hash` also attached to a different work | 20 |

`payment_ratio = sum(payments.amount) / cost`, `progress_ratio =
progress_pct / 100`.

No payments rows → `Skip("no payment records")` for the gap component,
but the evidence-absence and duplicate-photo components can still run.
**Partial skips are per component, not per check** — record them
individually, or the alert page's "5 of 8 checks ran" line is wrong.

**Reason for the duplicate photo:** *"The completion photograph for this
work is also attached to work #1190."* State the fact. Do not speculate
about why.

---

## MP-level — C3-MP quota → `compliance_points`, max 25

**Which financial year?** `scores` is `UNIQUE(subject_type, subject_id)`,
so there is exactly one row per MP — a year must be chosen. Use the
**most recently completed financial year** present in `allocations`
(for `REFERENCE_DATE` 2026-09-15, that is FY 2025-26). Put the chosen FY
in the evidence dict so the UI can say which year it is talking about.

An in-progress year cannot be judged against an annual floor: an MP at
9% SC spend in month four is not in breach, they are in June.

- SC-area spend below `SC_AREA_FLOOR` (15%) of that year's released
  funds → up to `SC_SHORTFALL_MAX_POINTS` (15), scaled by the size of the
  shortfall.
- ST-area below `ST_AREA_FLOOR` (7.5%) → up to 10.
- **These two stack** (unlike C3's variants), because they are two
  separate statutory obligations.

Scaling rule, so it is reproducible: `points = round(max_points ×
(floor − actual) / floor)`, clamped to the max. Round half up, once, at
the end.

SC/ST spend is **derived** by summing works where `is_sc_area = 1` /
`is_st_area = 1` — never read from a column on `allocations`. Storing it
twice guarantees the two disagree.

**Never apply this to the MP's individual works.** Awarding a quota
shortfall to each of their works would flag every work that MP ever
recommended — a false-positive machine and the fastest way to lose
credibility in a demo.

---

## District-level — C4 utilisation → `utilisation_points`, max 15

Two components, they stack, cap at 15.

**Behind calendar** (`C4_BEHIND_CALENDAR_POINTS`, 10). Compare the
current FY's spend ratio against the share of the financial year
elapsed at `REFERENCE_DATE`:

```
year_elapsed = (REFERENCE_DATE − fy_start).days / 365
if (year_elapsed − spend_ratio) > C4_CALENDAR_TOLERANCE:   # 0.30
```

Measured against the calendar, **not** as a raw unspent balance. Under
the single-annual-instalment model the whole ₹5 crore lands in April and
is drawn down as needed, so a flat "below 50% spent" rule would flag
every district in the country every June — legitimately unspent. This
distinction is worth being able to say out loud; it is the kind of
domain detail that separates a team that read the guidelines from one
that did not.

**Q4 bunching** (`C4_Q4_BUNCHING_POINTS`, 8). More than
`C4_Q4_SPEND_CEILING` (60%) of a *completed* year's spend falling in
January–March. Money moved to avoid lapsing rather than because work was
done. This component needs a finished year, so it reads the same
completed FY that C3-MP uses.

**Routing.** Per `SUBJECT_ROUTING`, district and MP alerts go to the
**State** Officer, never solely to the district officer whose own
performance is in question.

---

## Assembling a score

```python
total = min(sum(f.points for f in findings), MAX_TOTAL_SCORE)
```

Per-check columns are clamped to **their own** maxima and stored
unclamped by the total. Work-level caps sum to 153 against a 100-point
ceiling, so a work with three serious problems and one with five both
read as 100 — but `cost_points`, `delay_points` and the rest preserve
the detail, which is exactly why those columns exist. Nothing is lost;
it is queryable, just not visible in the headline number.

`reasons_json` is an ordered list, highest points first, in the fixed
shape from `CLAUDE.md`. Sort deterministically — points descending, then
check id ascending — or two runs will produce different JSON for the
same score.

`checks_run` and `checks_skipped` are JSON arrays: the ids that ran, and
`{check, why}` for those that did not.

Money in reason sentences uses Indian conventions — ₹8.4 lakh, ₹1.2
crore — through one shared `format_rupees()` helper. Never a bare
`840000` in a sentence a human reads.

---

## Writing scores, and the alerts problem

### Scores: full rebuild

`DELETE FROM scores`, then bulk insert. Scores are pure computation with
no human state.

### Alerts: reconcile, never wipe

**This is the one place the obvious implementation loses data.**

`alerts` carries workflow state an officer put there — `status`,
`verdict`, `resolution_note`, `assigned_to`, `snoozed_until`,
`resolved_at`. Deleting and recreating the table on every run throws all
of it away. Run `checks.py` after an officer has spent a morning
resolving alerts and their work vanishes, silently.

Reconcile instead:

| Situation | Action |
|---|---|
| Subject newly at/above 25, no alert exists | Create, `status = "open"` |
| Alert exists, subject still at/above 25 | Update `severity` and the score link. **Preserve every workflow column** |
| Alert exists, subject now below 25 | Keep it. Do not delete — an officer may already be acting on it. Let it age out through the normal workflow |
| Alert exists and is `resolved` | Never touch it |

Severity from `SEVERITY_BANDS`, highest band first.

If a judge asks what happens when the nightly run collides with an
officer's open case, the answer is this table.

---

## Determinism

- `REFERENCE_DATE` only. **No `date.today()` or `datetime.now()`** — the
  `auth.py` exemption does not extend here. Nothing in the scoring path
  may know what time it is.
- Sort every list before iterating: works by `work_id`, findings by
  (points desc, check asc), duplicate pairs by `work_id`.
- Never iterate a `set` where order affects output.
- No randomness. No dict-ordering dependence.
- Float comparisons at band boundaries: use `>=` consistently and round
  once, at the end, never mid-computation.

---

## Output

Print a summary — this is the tuning loop's dashboard, so make it
readable at a glance:

```
Scored 4,500 works · 120 MPs · 60 districts   in 3.2s
  alerts: 312 (critical 24, high 88, medium 200)
  by check: C1 71  C2 96  C2b 44  C3 38  C5 40  C6 12  C7 63
  skipped:  C1 18 (peer group too small)  C2b 400 (no progress data)
```

---

## Definition of done

```bash
python -m backend.checks          # completes, prints summary
python -m backend.checks          # run again
```

Correctness:

- [ ] `scores` has exactly one row per work, per MP, per district
- [ ] Clean subjects have score rows too (most with `total_score` under 10)
- [ ] `alerts` rows exist only where `total_score >= 25`
- [ ] Every `alerts.severity` matches its score's `SEVERITY_BANDS` band
- [ ] No `total_score` above 100 or below 0
- [ ] Every per-check column is within that check's cap
- [ ] Every score with points > 0 has a non-empty `reasons_json`
- [ ] Every reason sentence contains at least one real number
- [ ] `checks_run` + `checks_skipped` together account for every applicable check

Determinism:

```bash
python -m backend.checks && sqlite3 backend/mplads.db \
  "SELECT subject_type,subject_id,total_score,reasons_json FROM scores ORDER BY subject_type,subject_id" > /tmp/a
python -m backend.checks && sqlite3 backend/mplads.db \
  "SELECT subject_type,subject_id,total_score,reasons_json FROM scores ORDER BY subject_type,subject_id" > /tmp/b
diff /tmp/a /tmp/b        # must be identical
```

Alert preservation:

- [ ] Manually set one alert to `status='resolved'` with a verdict, re-run `checks.py`, confirm it is untouched
- [ ] Manually set one to `acknowledged`, re-run, confirm status survives

Rule compliance:

```bash
grep -rn "planted_anomaly" backend/checks.py                      # empty
grep -rn "is_hill_district\|default_area_type" backend/checks.py  # empty
grep -rn "BASE_UNIT_COST\|COST_MULTIPLIER" backend/checks.py      # empty
grep -rn "date.today\|datetime.now" backend/checks.py             # empty
grep -rni "fraud\|scam\|corrupt" backend/checks.py                # empty
grep -rn "SELECT \*" backend/checks.py                            # empty
```

By eye — the test that actually matters:

- [ ] Open the top 10 scores. For each, read the reasons aloud. If you
      cannot explain why it scored what it scored using only those
      sentences, the check that failed to explain itself is broken,
      regardless of what the number says.
- [ ] Open 5 random works scoring 0. Confirm they are genuinely
      unremarkable and not just missing data that should have been a Skip.

---

## What this step does not do

- No recall or false-positive measurement — that is `evaluate.py`, and
  it comes immediately next.
- No API, no auth, no UI.
- No threshold tuning. Run it, read the numbers, *then* tune `config.py`
  and re-run. The first run's numbers will be unimpressive; that is
  expected and is what the loop is for.