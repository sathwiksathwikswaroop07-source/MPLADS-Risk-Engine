"""The detection checks and scoring.

Run `python -m backend.checks`. Deletes and rebuilds `scores` and `alerts`;
it never writes to `works` or any other table.

Every subject gets a scores row -- a clean work scoring 3 exactly as a
flagged one scoring 78. That is what lets the citizen listing and the officer
worklist read from the same place. An alert is a separate, thinner record
created only above ALERT_MIN_SCORE.

Three things this module must never do, each of which would quietly destroy
the number on the slide:

* Read the ground-truth anomaly label on a work. That column belongs to
  evaluate.py; scoring against it would make recall a measurement of itself.
* Read the generator's baseline cost tables or their multipliers. Detection
  compares a work against its actual peers in the data, never against the
  baseline we generated from -- otherwise we are marking our own homework.
* Read the hill-district or default-area-type hints on a district row. Those
  are generation hints. The work's own terrain and area_type are the truth,
  and reading the district's would excuse a flat road in a hill district.

Checks run at three levels -- work, mp, district -- and the levels never mix.
Awarding an MP's quota shortfall to each of their works would flag every work
that MP ever recommended: a false-positive machine.
"""

from __future__ import annotations

import json
import statistics
from datetime import date, timedelta

from sqlalchemy import text

from backend import config
from backend.db import get_session
from backend.models import Alert, Score

REF = config.REFERENCE_DATE


# ---------------------------------------------------------------------------
# Small shared helpers
# ---------------------------------------------------------------------------


def _iso(value: date) -> str:
    return value.isoformat()


def _days_since(iso_date: str) -> int:
    """Days from an ISO date to REFERENCE_DATE.

    The system clock is never consulted anywhere in this package.
    """
    return (REF - date.fromisoformat(iso_date)).days


def _rupees(amount: float) -> str:
    """Format rupees the way an Indian officer reads them: lakh and crore."""
    amount = float(amount)
    if amount >= 10_000_000:
        return f"Rs {amount / 10_000_000:.2f} crore"
    if amount >= 100_000:
        return f"Rs {amount / 100_000:.2f} lakh"
    return f"Rs {amount:,.0f}"


def _finding(check: str, points: int, reason: str, evidence: dict) -> dict:
    """One check's result.

    A check that cannot produce a human-readable reason may not award points,
    so reason is required rather than optional.
    """
    return {
        "check": check,
        "points": int(points),
        "reason": reason,
        "evidence": evidence,
    }


def _band_points(value: float, bands: tuple) -> int:
    """Highest (threshold, points) rung whose threshold `value` has reached.

    Bands are ascending, so this walks to the last one that qualifies.
    """
    awarded = 0
    for threshold, points in bands:
        if value >= threshold:
            awarded = points
    return awarded


def _severity(total: int) -> str | None:
    """Severity band, or None when the score is below the alert threshold."""
    for minimum, label in config.SEVERITY_BANDS:
        if total >= minimum:
            return label
    return None


class Subject:
    """Accumulates findings for one subject, then renders a scores row.

    Each check writes into exactly one of the seven point columns. Keeping
    that mapping here rather than at each call site means a new check cannot
    silently land in the wrong column.
    """

    COLUMN_FOR_CHECK = {
        "C1": "cost_points",
        "C2": "delay_points",
        "C2b": "delay_points",
        "C3": "compliance_points",
        "C3-MP": "compliance_points",
        "C5": "duplicate_points",
        "C6": "public_points",
        "C7": "evidence_points",
        "C4": "utilisation_points",
    }

    def __init__(self, subject_type: str, subject_id: int):
        self.subject_type = subject_type
        self.subject_id = subject_id
        self.findings: list[dict] = []
        self.ran: list[str] = []
        self.skipped: list[dict] = []

    def record(self, check: str, finding: dict | None) -> int:
        """Note that a check ran, and keep its finding if it awarded points."""
        self.ran.append(check)
        if finding is None or finding["points"] <= 0:
            return 0
        self.findings.append(finding)
        return finding["points"]

    def skip(self, check: str, reason: str) -> None:
        """A check that could not run says why, rather than scoring zero.

        The alert page reads this to say "5 of 8 checks ran; the
        payment-progress and evidence checks require authenticated eSAKSHI
        data."
        """
        self.skipped.append({"check": check, "reason": reason})

    def to_score(self) -> Score:
        columns = {name: 0 for name in set(self.COLUMN_FOR_CHECK.values())}
        for finding in self.findings:
            columns[self.COLUMN_FOR_CHECK[finding["check"]]] += finding["points"]

        total = min(sum(columns.values()), config.MAX_TOTAL_SCORE)

        # Sorted by points so the alert page leads with the biggest reason.
        reasons = sorted(
            self.findings, key=lambda f: (-f["points"], f["check"])
        )

        return Score(
            subject_type=self.subject_type,
            subject_id=self.subject_id,
            total_score=total,
            reasons_json=json.dumps(reasons),
            checks_run=json.dumps(self.ran),
            checks_skipped=json.dumps(self.skipped),
            scored_on=_iso(REF),
            **columns,
        )


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

# Columns are named individually, never wildcarded. ORDER BY is not
# decoration either: without it SQLite may return rows in any order and two
# runs could differ.
#
# The ground-truth anomaly label is deliberately absent from this list. It
# belongs to evaluate.py and must never reach a check.
_WORKS_SQL = text("""
    SELECT works.work_id, works.mp_id, works.constituency_id,
           works.district_id, districts.state_id AS state_id,
           works.fy, works.work_type, works.description, works.terrain,
           works.area_type, works.quantity, works.unit,
           COALESCE(works.final_cost, works.estimated_cost) AS cost,
           works.final_cost, works.estimated_cost,
           works.recommended_on, works.sanctioned_on,
           works.expected_completion_on, works.completed_on, works.status,
           works.progress_pct, works.last_updated_on,
           works.is_sc_area, works.is_st_area
    FROM works
    JOIN districts ON districts.district_id = works.district_id
    ORDER BY works.work_id
""")


def load_works(session) -> list[dict]:
    """Every work, with its state_id joined on for peer-ladder rung 2."""
    return [dict(row) for row in
            session.execute(_WORKS_SQL).mappings().all()]


def load_payment_totals(session) -> dict[int, int]:
    """work_id -> rupees paid across all tranches."""
    rows = session.execute(text("""
        SELECT work_id, SUM(amount) AS paid
        FROM payments GROUP BY work_id ORDER BY work_id
    """)).mappings().all()
    return {row["work_id"]: row["paid"] or 0 for row in rows}


def load_evidence_counts(session) -> dict[int, int]:
    """work_id -> number of evidence rows. Absence is itself the signal."""
    rows = session.execute(text("""
        SELECT work_id, COUNT(*) AS n
        FROM evidence GROUP BY work_id ORDER BY work_id
    """)).mappings().all()
    return {row["work_id"]: row["n"] for row in rows}


def load_progress_counts(session) -> dict[int, int]:
    """work_id -> number of progress_updates rows.

    Zero means the history is absent, which is a reason to SKIP the checks
    that need it -- not to score them zero.
    """
    rows = session.execute(text("""
        SELECT work_id, COUNT(*) AS n
        FROM progress_updates GROUP BY work_id ORDER BY work_id
    """)).mappings().all()
    return {row["work_id"]: row["n"] for row in rows}


def load_verified_complaint_counts(session) -> dict[int, int]:
    """work_id -> distinct verified reporters.

    UNIQUE(work_id, user_id) on complaints is what makes this count
    meaningful: one person cannot inflate a score by filing repeatedly.
    """
    rows = session.execute(text("""
        SELECT work_id, COUNT(DISTINCT user_id) AS n
        FROM complaints WHERE verified = 1
        GROUP BY work_id ORDER BY work_id
    """)).mappings().all()
    return {row["work_id"]: row["n"] for row in rows}


def load_shared_photo_hashes(session) -> dict[int, list[int]]:
    """work_id -> other work_ids submitting the same photograph.

    A self-join on evidence.photo_hash, which idx_evidence_hash exists for.
    The same completion photo filed as proof for two works is the hardest
    component of C7 to explain away.
    """
    rows = session.execute(text("""
        SELECT a.work_id AS work_id, b.work_id AS other_id
        FROM evidence a
        JOIN evidence b
          ON a.photo_hash = b.photo_hash
         AND a.work_id <> b.work_id
        WHERE a.photo_hash IS NOT NULL
        ORDER BY a.work_id, b.work_id
    """)).mappings().all()
    shared: dict[int, list[int]] = {}
    for row in rows:
        others = shared.setdefault(row["work_id"], [])
        if row["other_id"] not in others:
            others.append(row["other_id"])
    return shared


# ---------------------------------------------------------------------------
# C1 -- cost outlier, and the peer-group ladder
# ---------------------------------------------------------------------------


class PeerGroups:
    """Unit-cost distributions for every rung of the peer ladder.

    Built once from the works already in memory rather than by re-querying
    per work: 4,500 works each walking a five-rung ladder is 22,500 grouped
    aggregations, and the answers only depend on the rung key.

    The ladder is tried in order and stops at the first rung holding at least
    PEER_GROUP_MIN_ROWS. area_type is given up after district deliberately --
    urbanisation explains more cost variance than geography does, so it earns
    its place for one rung longer.
    """

    def __init__(self, works: list[dict]):
        self.rungs: list[tuple[tuple[str, ...], dict]] = []
        for fields in config.PEER_GROUP_LADDER:
            groups: dict[tuple, list[float]] = {}
            for work in works:
                unit_cost = _unit_cost(work)
                if unit_cost is None:
                    continue
                groups.setdefault(
                    tuple(work[field] for field in fields), []
                ).append(unit_cost)
            self.rungs.append((fields, groups))

    def for_work(self, work: dict):
        """First rung with enough peers: (level_name, sorted unit costs).

        Returns (None, None) when even the last rung falls short -- with
        fewer than eight rows a median is noise, so C1 skips rather than
        guessing.
        """
        for fields, groups in self.rungs:
            key = tuple(work[field] for field in fields)
            values = groups.get(key)
            if values and len(values) >= config.PEER_GROUP_MIN_ROWS:
                return "+".join(fields), sorted(values)
        return None, None


def _unit_cost(work: dict) -> float | None:
    """Cost per unit of quantity.

    Cost is always COALESCE(final_cost, estimated_cost) -- never final_cost
    alone, which is NULL for every unfinished work and would silently exclude
    exactly the ones most likely to be problems.
    """
    if not work["quantity"] or work["quantity"] <= 0:
        return None
    if work["cost"] is None or work["cost"] <= 0:
        return None
    return work["cost"] / work["quantity"]


def check_c1_cost_outlier(work: dict, peers: PeerGroups, subject: Subject):
    """Unit cost against the peer-group median, gated by the IQR fence.

    Fence first, then band. A work inside Q3 + 1.5*IQR scores zero even at
    twice the median -- in a tightly clustered peer group 2x can still be
    ordinary, and awarding ratio points there is how a peer group of cheap
    borewells starts flagging half of itself. Once past the fence, award the
    higher of the fence points and whatever the ratio band gives.
    """
    unit_cost = _unit_cost(work)
    if unit_cost is None:
        subject.skip("C1", "No quantity or cost recorded, so there is no "
                           "unit cost to compare.")
        return None

    level, values = peers.for_work(work)
    if values is None:
        subject.skip("C1", "Fewer than "
                           f"{config.PEER_GROUP_MIN_ROWS} comparable works "
                           "exist, which is too few for a reliable median.")
        return None

    median = statistics.median(values)
    if median <= 0:
        subject.skip("C1", "Comparable works have no usable cost.")
        return None

    quartiles = statistics.quantiles(values, n=4) if len(values) >= 4 else None
    if quartiles is None:
        subject.skip("C1", "Too few comparable works to compute a fence.")
        return None

    q1, q3 = quartiles[0], quartiles[2]
    fence = q3 + config.C1_IQR_MULTIPLIER * (q3 - q1)

    if unit_cost <= fence:
        return None

    ratio = unit_cost / median
    points = max(config.C1_FENCE_POINTS,
                 _band_points(ratio, config.C1_RATIO_BANDS))
    points = min(points, config.C1_MAX_POINTS)

    reason = (
        f"Cost per {work['unit']} is {_rupees(unit_cost)} against a median of "
        f"{_rupees(median)} for {len(values)} comparable works ({ratio:.1f}x). "
        "This is above the range those works occupy and needs verification."
    )
    return _finding("C1", points, reason, {
        "value": round(unit_cost, 2),
        "median": round(median, 2),
        "ratio": round(ratio, 2),
        "fence": round(fence, 2),
        "q1": round(q1, 2),
        "q3": round(q3, 2),
        "peer_count": len(values),
        "peer_level": level,
        "unit": work["unit"],
    })


# ---------------------------------------------------------------------------
# C2 / C2b -- delay, and predicted stall
# ---------------------------------------------------------------------------


def check_c2_delay(work: dict, subject: Subject):
    """Time since sanction while the work is still not complete."""
    if work["status"] == "completed":
        return None
    if not work["sanctioned_on"]:
        subject.skip("C2", "Not sanctioned yet, so there is no delay to "
                           "measure.")
        return None

    days = _days_since(work["sanctioned_on"])
    points = 0
    for minimum, maximum, band_points in config.C2_DELAY_BANDS:
        if days >= minimum and (maximum is None or days <= maximum):
            points = band_points
            break
    if points <= 0:
        return None

    overdue_note = ""
    if work["expected_completion_on"]:
        overdue = _days_since(work["expected_completion_on"])
        if overdue > 0:
            overdue_note = (f" It was expected by "
                            f"{work['expected_completion_on']}, "
                            f"{overdue} days ago.")

    reason = (
        f"Sanctioned {days} days ago and still {work['status'].replace('_', ' ')} "
        f"at {work['progress_pct']:.0f}% progress.{overdue_note}"
    )
    return _finding("C2", min(points, config.C2_MAX_POINTS), reason, {
        "days_since_sanction": days,
        "sanctioned_on": work["sanctioned_on"],
        "expected_completion_on": work["expected_completion_on"],
        "progress_pct": work["progress_pct"],
        "status": work["status"],
    })


def check_c2b_predicted_stall(work: dict, progress_rows: int,
                              subject: Subject):
    """Not yet late, but on course to be -- the early-warning check.

    Only runs when C2 awarded nothing. Both write delay_points, so a work
    that is very overdue AND stale would otherwise be charged twice for one
    problem. The caller enforces that with an explicit guard.

    Needs two things together, not either: progress meaningfully below what
    the elapsed share of the expected duration implies, and nobody having
    touched the record in C2B_STALE_DAYS.
    """
    if work["status"] in ("completed", "recommended"):
        return None
    if not work["sanctioned_on"] or not work["expected_completion_on"]:
        subject.skip("C2b", "No sanction or expected completion date, so "
                            "expected progress cannot be estimated.")
        return None
    if progress_rows == 0:
        subject.skip("C2b", "No progress history has been reported for this "
                            "work, so it cannot be compared with schedule.")
        return None

    planned_days = (date.fromisoformat(work["expected_completion_on"])
                    - date.fromisoformat(work["sanctioned_on"])).days
    if planned_days <= 0:
        subject.skip("C2b", "Expected completion is not after sanction, so "
                            "the schedule is unusable.")
        return None

    elapsed_share = min(1.0, _days_since(work["sanctioned_on"]) / planned_days)
    actual_share = (work["progress_pct"] or 0) / 100.0
    shortfall = elapsed_share - actual_share
    stale_days = _days_since(work["last_updated_on"])

    if shortfall < config.C2B_PROGRESS_SHORTFALL:
        return None
    if stale_days < config.C2B_STALE_DAYS:
        return None

    reason = (
        f"About {elapsed_share * 100:.0f}% of the allowed time has passed but "
        f"progress is {actual_share * 100:.0f}%, and the record has not been "
        f"updated in {stale_days} days. Not yet overdue, but on course to be."
    )
    return _finding("C2b", config.C2B_MAX_POINTS, reason, {
        "elapsed_share": round(elapsed_share, 3),
        "progress_share": round(actual_share, 3),
        "shortfall": round(shortfall, 3),
        "stale_days": stale_days,
        "expected_completion_on": work["expected_completion_on"],
    })


# ---------------------------------------------------------------------------
# C3 -- work compliance
# ---------------------------------------------------------------------------


def check_c3_compliance(work: dict, mp_terms: dict, subject: Subject):
    """Data-integrity and eligibility problems on the record itself.

    Highest single finding, never stacked: one work with a date ordering
    problem has one compliance problem, not four.
    """
    findings = []

    recommended = work["recommended_on"]
    sanctioned = work["sanctioned_on"]
    completed = work["completed_on"]

    if completed and sanctioned and completed < sanctioned:
        findings.append((config.C3_MAX_POINTS,
                         f"Recorded as completed on {completed}, which is "
                         f"before it was sanctioned on {sanctioned}.",
                         {"issue": "completed_before_sanctioned",
                          "completed_on": completed,
                          "sanctioned_on": sanctioned}))

    if sanctioned and recommended and sanctioned < recommended:
        findings.append((config.C3_MAX_POINTS,
                         f"Sanctioned on {sanctioned}, which is before it was "
                         f"recommended on {recommended}.",
                         {"issue": "sanctioned_before_recommended",
                          "sanctioned_on": sanctioned,
                          "recommended_on": recommended}))

    reference = _iso(REF)
    for label, value in (("recommended", recommended),
                         ("sanctioned", sanctioned),
                         ("completed", completed)):
        if value and value > reference:
            findings.append((config.C3_MAX_POINTS,
                             f"The {label} date {value} is in the future.",
                             {"issue": "future_date", "field": label,
                              "value": value}))

    term = mp_terms.get(work["mp_id"])
    if term and recommended:
        start, end = term
        if recommended < start or (end and recommended > end):
            findings.append((config.C3_MAX_POINTS,
                             f"Recommended on {recommended}, outside the "
                             f"recommending member's term "
                             f"({start} to {end or 'present'}).",
                             {"issue": "outside_mp_term",
                              "recommended_on": recommended,
                              "term_start": start, "term_end": end}))

    description = (work["description"] or "").lower()
    for category in config.NOT_PERMITTED_WORK_CATEGORIES:
        if category in description:
            findings.append((config.C3_MAX_POINTS,
                             f"The description refers to \"{category}\", "
                             "which is not a permitted category under the "
                             "scheme guidelines.",
                             {"issue": "not_permitted_category",
                              "category": category}))
            break

    if not findings:
        return None

    points, reason, evidence = max(findings, key=lambda f: f[0])
    return _finding("C3", min(points, config.C3_MAX_POINTS), reason, evidence)


# ---------------------------------------------------------------------------
# C5 -- duplicate works
# ---------------------------------------------------------------------------


def build_duplicate_index(works: list[dict]) -> dict[int, list[dict]]:
    """work_id -> near-identical twins in the same district and work_type.

    Same district, same type, unit cost within C5_UNIT_COST_TOLERANCE, and
    sanctioned within C5_WINDOW_DAYS of each other. Both works are indexed,
    so each one's alert can name the other -- neither is "the duplicate".
    """
    buckets: dict[tuple, list[dict]] = {}
    for work in works:
        if not work["sanctioned_on"] or _unit_cost(work) is None:
            continue
        buckets.setdefault(
            (work["district_id"], work["work_type"]), []).append(work)

    matches: dict[int, list[dict]] = {}
    for key in sorted(buckets):
        bucket = sorted(buckets[key], key=lambda w: (w["sanctioned_on"],
                                                     w["work_id"]))
        for index, work in enumerate(bucket):
            for other in bucket[index + 1:]:
                gap = (date.fromisoformat(other["sanctioned_on"])
                       - date.fromisoformat(work["sanctioned_on"])).days
                if gap > config.C5_WINDOW_DAYS:
                    break
                unit_a, unit_b = _unit_cost(work), _unit_cost(other)
                spread = abs(unit_a - unit_b) / min(unit_a, unit_b)
                if spread >= config.C5_UNIT_COST_TOLERANCE:
                    continue
                pair = {"gap_days": gap, "cost_spread": round(spread, 4)}
                matches.setdefault(work["work_id"], []).append(
                    {**pair, "other": other})
                matches.setdefault(other["work_id"], []).append(
                    {**pair, "other": work})
    return matches


def check_c5_duplicate(work: dict, duplicates: dict, subject: Subject):
    """A near-identical work sanctioned in the same district at the same time."""
    twins = duplicates.get(work["work_id"])
    if not twins:
        return None

    twin = min(twins, key=lambda t: t["other"]["work_id"])
    other = twin["other"]
    reason = (
        f"Closely matches work #{other['work_id']} in the same district: same "
        f"type ({work['work_type']}), unit cost within "
        f"{twin['cost_spread'] * 100:.0f}%, sanctioned {twin['gap_days']} days "
        "apart. One of the two may be a repeat entry and needs verification."
    )
    return _finding("C5", config.C5_MAX_POINTS, reason, {
        "other_work_id": other["work_id"],
        "other_description": other["description"],
        "gap_days": twin["gap_days"],
        "cost_spread": twin["cost_spread"],
        "match_count": len(twins),
    })


# ---------------------------------------------------------------------------
# C6 -- citizen reports
# ---------------------------------------------------------------------------


def check_c6_reports(work: dict, complaint_counts: dict, subject: Subject):
    """Distinct verified complaints from the public.

    Only verified rows count, and UNIQUE(work_id, user_id) means one person
    cannot inflate the number by filing repeatedly.
    """
    reporters = complaint_counts.get(work["work_id"], 0)
    if reporters <= 0:
        return None

    points = min(_band_points(reporters, config.C6_REPORT_BANDS),
                 config.C6_MAX_POINTS)
    if points <= 0:
        return None

    people = "person has" if reporters == 1 else "people have"
    reason = (f"{reporters} verified {people} reported a problem with this "
              "work.")
    return _finding("C6", points, reason, {"verified_reporters": reporters})


# ---------------------------------------------------------------------------
# C7 -- paid, but no proof of work
# ---------------------------------------------------------------------------


def check_c7_ghost_asset(work: dict, paid: int, evidence_rows: int,
                         shared_photos: list, subject: Subject):
    """Money moved without matching proof that the asset exists.

    Components are summed and then capped: no single one is conclusive, but
    a work that is fully paid, marked complete, has no photograph and has not
    been touched in six months is a different proposition from one that is
    merely a little ahead on payment.
    """
    cost = work["cost"]
    if not cost or cost <= 0:
        subject.skip("C7", "No cost recorded, so payment cannot be compared "
                           "with progress.")
        return None

    components = []
    total = 0

    payment_ratio = paid / cost if paid else 0.0
    progress_ratio = (work["progress_pct"] or 0) / 100.0

    if paid:
        gap = payment_ratio - progress_ratio
        gap_points = _band_points(gap, config.C7_PAYMENT_GAP_BANDS)
        if gap_points:
            total += gap_points
            components.append(
                f"{payment_ratio * 100:.0f}% of the cost has been paid against "
                f"{progress_ratio * 100:.0f}% reported progress")
    else:
        # No payment rows is not evidence of anything -- it is missing data.
        subject.skip("C7", "No payment records, so the payment-versus-"
                           "progress comparison could not run.")

    if work["status"] == "completed" and evidence_rows == 0:
        total += config.C7_COMPLETED_NO_EVIDENCE
        components.append(
            "it is marked complete but carries no photograph, completion "
            "certificate or handover record")

    if (payment_ratio > config.C7_STALE_MIN_PAYMENT_RATIO
            and _days_since(work["last_updated_on"]) >= config.C7_STALE_DAYS):
        total += config.C7_STALE_WHILE_PAID
        components.append(
            f"the record has not been updated in "
            f"{_days_since(work['last_updated_on'])} days while most of the "
            "money has gone")

    if work["completed_on"] and work["sanctioned_on"]:
        planned = config.EXPECTED_DURATION_DAYS.get(
            (work["work_type"], work["area_type"]))
        actual = (date.fromisoformat(work["completed_on"])
                  - date.fromisoformat(work["sanctioned_on"])).days
        if planned and 0 <= actual < planned * config.C7_FAST_FRACTION:
            total += config.C7_IMPLAUSIBLY_FAST
            components.append(
                f"it was completed in {actual} days against an expected "
                f"{planned}")

    if shared_photos:
        total += config.C7_DUPLICATE_PHOTO
        others = ", ".join(f"#{wid}" for wid in sorted(shared_photos)[:3])
        components.append(
            f"its photograph is also filed as proof for work {others}")

    if total <= 0:
        return None

    points = min(total, config.C7_MAX_POINTS)
    reason = ("Payment is ahead of demonstrated work: "
              + "; ".join(components) + ". This needs verification on site.")
    return _finding("C7", points, reason, {
        "payment_ratio": round(payment_ratio, 3),
        "progress_ratio": round(progress_ratio, 3),
        "gap": round(payment_ratio - progress_ratio, 3),
        "paid": paid,
        "cost": cost,
        "evidence_rows": evidence_rows,
        "stale_days": _days_since(work["last_updated_on"]),
        "shared_photo_work_ids": sorted(shared_photos),
        "raw_points": total,
        "components": len(components),
    })


# ---------------------------------------------------------------------------
# C3-MP -- SC/ST quota compliance, at the MP level
# ---------------------------------------------------------------------------


def check_c3_mp_quota(mp_row: dict, subject: Subject):
    """Share of released funds spent in SC and ST areas.

    A compliance fact, not an accusation, and deliberately scored against the
    MP rather than against their works: awarding it to each work would flag
    every work that member ever recommended.

    The two shortfalls stack -- they are separate statutory floors.
    """
    released = mp_row["released"] or 0
    if released <= 0:
        subject.skip("C3-MP", "No funds released yet for this member, so the "
                              "quota shares cannot be computed.")
        return None

    findings = []
    total = 0

    for label, spent, floor, cap in (
        ("Scheduled Caste", mp_row["sc_spent"] or 0,
         config.SC_AREA_FLOOR, config.SC_SHORTFALL_MAX_POINTS),
        ("Scheduled Tribe", mp_row["st_spent"] or 0,
         config.ST_AREA_FLOOR, config.ST_SHORTFALL_MAX_POINTS),
    ):
        share = spent / released
        if share >= floor:
            continue
        # Scaled by how far short it falls, so a near miss is not treated
        # like spending nothing at all.
        shortfall = (floor - share) / floor
        points = int(round(cap * min(1.0, shortfall)))
        if points <= 0:
            continue
        total += points
        findings.append(
            f"{label} area spend is {share * 100:.1f}% of released funds "
            f"against a floor of {floor * 100:.1f}%")

    if total <= 0:
        return None

    reason = ("Quota shortfall: " + "; ".join(findings)
              + ". This is a compliance gap for the district authority to "
                "address in the coming sanctions.")
    return _finding("C3-MP", min(total, config.C3_MP_MAX_POINTS), reason, {
        "released": released,
        "sc_spent": mp_row["sc_spent"] or 0,
        "st_spent": mp_row["st_spent"] or 0,
        "sc_share": round((mp_row["sc_spent"] or 0) / released, 4),
        "st_share": round((mp_row["st_spent"] or 0) / released, 4),
        "sc_floor": config.SC_AREA_FLOOR,
        "st_floor": config.ST_AREA_FLOOR,
    })


# ---------------------------------------------------------------------------
# C4 -- district utilisation
# ---------------------------------------------------------------------------


def check_c4_utilisation(district_row: dict, subject: Subject):
    """Spend measured against the calendar, not as a raw unspent balance.

    Since April 2023 the whole annual entitlement lands at the start of the
    financial year and is drawn down as needed, so a flat "below 50% spent"
    rule would flag every district in the country every June, entirely
    legitimately. Compare the spend ratio with the share of the year that has
    actually elapsed instead.
    """
    released = district_row["released"] or 0
    if released <= 0:
        subject.skip("C4", "No funds released to this district in the "
                           "current year.")
        return None

    total = 0
    parts = []

    spend_ratio = (district_row["spent"] or 0) / released
    elapsed = district_row["year_elapsed"]
    behind = elapsed - spend_ratio
    if behind >= config.C4_CALENDAR_TOLERANCE:
        total += config.C4_BEHIND_CALENDAR_POINTS
        parts.append(
            f"{spend_ratio * 100:.0f}% of released funds are spent with "
            f"{elapsed * 100:.0f}% of the financial year elapsed")

    q4_share = district_row["q4_share"]
    if q4_share is not None and q4_share > config.C4_Q4_SPEND_CEILING:
        total += config.C4_Q4_BUNCHING_POINTS
        parts.append(
            f"{q4_share * 100:.0f}% of the year's spend fell in January to "
            "March")

    if total <= 0:
        return None

    reason = ("Utilisation is out of step with the calendar: "
              + "; ".join(parts) + ".")
    return _finding("C4", min(total, config.C4_MAX_POINTS), reason, {
        "spend_ratio": round(spend_ratio, 3),
        "year_elapsed": round(elapsed, 3),
        "behind_by": round(behind, 3),
        "q4_share": None if q4_share is None else round(q4_share, 3),
        "released": released,
        "spent": district_row["spent"] or 0,
    })


# ---------------------------------------------------------------------------
# MP and district aggregates
# ---------------------------------------------------------------------------

# SC/ST spend is derived by summing works, never stored on allocations.
# Keeping it in two places guarantees the two eventually disagree.
_MP_AGGREGATE_SQL = text("""
    SELECT mps.mp_id,
           COALESCE(rel.released, 0) AS released,
           COALESCE(sc.spent, 0) AS sc_spent,
           COALESCE(st.spent, 0) AS st_spent
    FROM mps
    LEFT JOIN (
        SELECT mp_id, SUM(released) AS released
        FROM allocations GROUP BY mp_id
    ) AS rel ON rel.mp_id = mps.mp_id
    LEFT JOIN (
        SELECT mp_id, SUM(COALESCE(final_cost, estimated_cost)) AS spent
        FROM works WHERE is_sc_area = 1 AND status <> 'recommended'
        GROUP BY mp_id
    ) AS sc ON sc.mp_id = mps.mp_id
    LEFT JOIN (
        SELECT mp_id, SUM(COALESCE(final_cost, estimated_cost)) AS spent
        FROM works WHERE is_st_area = 1 AND status <> 'recommended'
        GROUP BY mp_id
    ) AS st ON st.mp_id = mps.mp_id
    ORDER BY mps.mp_id
""")

# Utilisation is judged against the calendar, so the current financial year
# is what matters -- an earlier year's underspend is history, not a live
# signal.
# A district's funds are those of the members who actually commission works
# there, found through works.district_id. Going via the state instead would
# credit every district in Maharashtra with all ten of its members'
# entitlements and make the ratio meaningless.
_DISTRICT_AGGREGATE_SQL = text("""
    SELECT districts.district_id,
           COALESCE(SUM(a.released), 0) AS released,
           COALESCE(SUM(a.spent), 0) AS spent
    FROM districts
    LEFT JOIN (
        SELECT DISTINCT district_id, mp_id FROM works
    ) AS dm ON dm.district_id = districts.district_id
    LEFT JOIN allocations a
           ON a.mp_id = dm.mp_id AND a.fy = :fy
    GROUP BY districts.district_id
    ORDER BY districts.district_id
""")

_DISTRICT_SPEND_SQL = text("""
    SELECT district_id,
           SUM(COALESCE(final_cost, estimated_cost)) AS total,
           SUM(CASE WHEN CAST(substr(sanctioned_on, 6, 2) AS INTEGER)
                         IN (1, 2, 3)
                    THEN COALESCE(final_cost, estimated_cost) ELSE 0 END)
               AS q4_total
    FROM works
    WHERE fy = :fy AND sanctioned_on IS NOT NULL
    GROUP BY district_id
    ORDER BY district_id
""")


def calendar_fy() -> str:
    """The financial year REFERENCE_DATE falls in. April to March."""
    year = REF.year if REF.month >= 4 else REF.year - 1
    return f"{year}-{str(year + 1)[2:]}"


def utilisation_fy(session) -> str:
    """The latest financial year that actually has allocations.

    Not simply the calendar year: REFERENCE_DATE sits in 2026-27 while the
    dataset runs to 2025-26, and scoring a year with no rows would make C4
    skip every district in the country -- technically correct and completely
    useless. Judging the most recent year with data is the honest reading of
    "how is this district doing".

    Requires spend, not merely a release: 2025-26 has money released against
    every member but no works recorded yet, and judging that year would score
    every district as 0% utilised on an accounting gap rather than a real one.
    """
    latest = session.execute(text(
        "SELECT MAX(fy) AS fy FROM allocations WHERE released > 0 AND spent > 0"
    )).scalar()
    return latest or calendar_fy()


def year_elapsed_share(fy: str) -> float:
    """How much of `fy` had elapsed by REFERENCE_DATE.

    A year already finished counts as fully elapsed, which is what makes
    "behind the calendar" meaningful for a closed year.
    """
    start_year = int(fy[:4])
    start = date(start_year, 4, 1)
    end = date(start_year + 1, 3, 31)
    return min(1.0, max(0.0, (REF - start).days / (end - start).days))


# ---------------------------------------------------------------------------
# Scoring one subject at a time
# ---------------------------------------------------------------------------


def _guarded(subject: Subject, check: str, fn, *args):
    """Run one check; a bug degrades to a skip rather than killing the run.

    Scoring 4,500 works should not be an all-or-nothing operation: one
    malformed row must not cost the officer the entire worklist.
    """
    try:
        return fn(*args)
    except Exception as exc:  # noqa: BLE001 - deliberate catch-all
        subject.skip(check, f"Could not be evaluated ({type(exc).__name__}).")
        return None


def score_work(work: dict, ctx: dict) -> Score:
    """The six work-level checks, in a fixed order."""
    subject = Subject("work", work["work_id"])

    subject.record("C1", _guarded(subject, "C1", check_c1_cost_outlier,
                                  work, ctx["peers"], subject))

    c2_points = subject.record("C2", _guarded(subject, "C2", check_c2_delay,
                                              work, subject))

    # C2 and C2b both write delay_points, so a very overdue work that is also
    # stale would be charged twice for one problem. C2b is the early warning
    # for works that are NOT YET late -- hence the explicit guard rather than
    # trusting the conditions never to overlap.
    if c2_points == 0:
        subject.record("C2b", _guarded(
            subject, "C2b", check_c2b_predicted_stall, work,
            ctx["progress_counts"].get(work["work_id"], 0), subject))

    subject.record("C3", _guarded(subject, "C3", check_c3_compliance,
                                  work, ctx["mp_terms"], subject))
    subject.record("C5", _guarded(subject, "C5", check_c5_duplicate,
                                  work, ctx["duplicates"], subject))
    subject.record("C6", _guarded(subject, "C6", check_c6_reports,
                                  work, ctx["complaints"], subject))
    subject.record("C7", _guarded(
        subject, "C7", check_c7_ghost_asset, work,
        ctx["payments"].get(work["work_id"], 0),
        ctx["evidence_counts"].get(work["work_id"], 0),
        ctx["shared_photos"].get(work["work_id"], []), subject))

    return subject.to_score()


def score_mp(mp_row: dict) -> Score:
    subject = Subject("mp", mp_row["mp_id"])
    subject.record("C3-MP", _guarded(subject, "C3-MP", check_c3_mp_quota,
                                     mp_row, subject))
    return subject.to_score()


def score_district(district_row: dict) -> Score:
    subject = Subject("district", district_row["district_id"])
    subject.record("C4", _guarded(subject, "C4", check_c4_utilisation,
                                  district_row, subject))
    return subject.to_score()


# ---------------------------------------------------------------------------
# The polymorphic join, in one place
# ---------------------------------------------------------------------------

# scores.subject_id is deliberately not a ForeignKey -- its target table
# varies by row. That sets a trap which fails SILENTLY: a district score with
# subject_id = 3 matches work_id = 3 just as happily.
#
# So the type filter and the join live in one function and cannot be
# separated by a later edit. Step 04 must call this rather than writing its
# own join.
_SUBJECT_TABLE = {
    "work": ("works", "work_id"),
    "mp": ("mps", "mp_id"),
    "district": ("districts", "district_id"),
}


def subject_join_sql(subject_type: str, columns: str) -> text:
    """Scores joined to their real subject table, type-filtered first."""
    table, key = _SUBJECT_TABLE[subject_type]
    return text(f"""
        SELECT {columns}
        FROM scores
        JOIN {table} ON {table}.{key} = scores.subject_id
        WHERE scores.subject_type = :subject_type
    """)


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


def run_checks(session) -> dict:
    """Score every work, MP and district; rebuild scores and alerts."""
    works = load_works(session)

    ctx = {
        "peers": PeerGroups(works),
        "payments": load_payment_totals(session),
        "evidence_counts": load_evidence_counts(session),
        "progress_counts": load_progress_counts(session),
        "complaints": load_verified_complaint_counts(session),
        "shared_photos": load_shared_photo_hashes(session),
        "duplicates": build_duplicate_index(works),
        "mp_terms": {
            row["mp_id"]: (row["term_start"], row["term_end"])
            for row in session.execute(text(
                "SELECT mp_id, term_start, term_end FROM mps ORDER BY mp_id"
            )).mappings().all()
        },
    }

    scores = [score_work(work, ctx) for work in works]

    for row in session.execute(_MP_AGGREGATE_SQL).mappings().all():
        scores.append(score_mp(dict(row)))

    fy = utilisation_fy(session)
    elapsed = year_elapsed_share(fy)
    spend = {row["district_id"]: row for row in session.execute(
        _DISTRICT_SPEND_SQL, {"fy": fy}).mappings().all()}

    for row in session.execute(_DISTRICT_AGGREGATE_SQL,
                               {"fy": fy}).mappings().all():
        district = dict(row)
        totals = spend.get(district["district_id"])
        district["year_elapsed"] = elapsed
        district["q4_share"] = (
            (totals["q4_total"] / totals["total"])
            if totals and totals["total"] else None
        )
        scores.append(score_district(district))

    # Alerts reference scores, so they go first -- the FK pragma is live.
    session.execute(text("DELETE FROM alerts"))
    session.execute(text("DELETE FROM scores"))
    session.flush()

    session.add_all(scores)
    session.flush()  # assigns score_id

    alerts = []
    for score in scores:
        severity = _severity(score.total_score)
        if severity is None:
            continue
        alerts.append(Alert(
            score_id=score.score_id,
            severity=severity,
            status="open",
            # Left NULL deliberately. Routing follows subject_type and the
            # officer's own scope from their token; writing a user_id here
            # would freeze one officer into a batch job.
            assigned_to=None,
            created_at=_iso(REF),
        ))
    session.add_all(alerts)

    return {"scores": scores, "alerts": alerts}


def main() -> None:
    with get_session() as session:
        result = run_checks(session)
        scores, alerts = result["scores"], result["alerts"]

        by_type: dict[str, int] = {}
        for score in scores:
            by_type[score.subject_type] = by_type.get(score.subject_type, 0) + 1
        by_severity: dict[str, int] = {}
        for alert in alerts:
            by_severity[alert.severity] = by_severity.get(alert.severity, 0) + 1

        skipped = sum(1 for s in scores if json.loads(s.checks_skipped))
        top = sorted(scores,
                     key=lambda s: (-s.total_score, s.subject_type,
                                    s.subject_id))[:10]

        print(f"Scored {len(scores)} subjects, raised {len(alerts)} alerts\n")
        print("  Subjects")
        for subject_type in sorted(by_type):
            print(f"    {subject_type:12} {by_type[subject_type]:>6}")

        print("\n  Alerts by severity")
        for severity in ("critical", "high", "medium"):
            print(f"    {severity:12} {by_severity.get(severity, 0):>6}")

        print(f"\n  Subjects with at least one skipped check: {skipped}")

        print("\n  Top 10 by score")
        for score in top:
            reasons = json.loads(score.reasons_json)
            lead = reasons[0]["check"] if reasons else "-"
            print(f"    {score.total_score:>3}  {score.subject_type}/"
                  f"{score.subject_id:<6} led by {lead}")


if __name__ == "__main__":
    main()
