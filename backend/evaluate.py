"""Measures the detection engine against the anomalies the generator planted.

Run `python -m backend.evaluate`. Reads only; writes nothing.

This is the one module permitted to read `works.planted_anomaly`. That column
is ground truth, and measuring against it is its entire purpose -- which is
also exactly why `checks.py` must never touch it. If the scoring code could
see the labels, the number this script prints would be measuring itself.

Two rates are reported per label, because they answer different questions and
differ sharply:

  detected  the checks scored it above zero -- the signal was seen at all
  alerted   it reached ALERT_MIN_SCORE and landed on an officer's worklist

Reporting only the second would understate detection; reporting only the first
would overstate what an officer actually sees. Several checks cap below the
alert threshold, so a work can be correctly identified and still not raise an
alert on its own -- a threshold decision, not a detection failure, and one the
two columns make visible instead of hiding.
"""

from __future__ import annotations

from sqlalchemy import text

from backend import config
from backend.db import get_session

# Where each planted label's ground truth lives, and which subject level the
# scores must be read at. Getting this pairing wrong is the classic
# polymorphic-id error: an MP-level anomaly compared against work scores would
# silently match unrelated rows.
WORK_LABELS = (
    "cost_overrun",
    "long_delay",
    "impossible_date",
    "ineligible_work",
    "duplicate_pair",
    "payment_ahead_of_work",
    "ghost_asset",
)

SUBJECT_LABELS = (
    ("mp", "quota_shortfall"),
    ("vendor", "vendor_overpricing"),
)


def load_work_truth(session) -> dict[str, list[tuple[int, int]]]:
    """label -> [(work_id, total_score)] for every planted work.

    Ground truth comes from two places, because a work has one
    planted_anomaly column and a handful of works carry two problems at once
    -- the stacked works that make the critical band reachable.

    The primary label stays in the column, so the ordinary per-label table and
    build_child_records' dispatch keep working unchanged. Each additional
    label is recorded in audit_log, exactly as MP and vendor ground truth
    already are, and merged back here.

    The alternative -- comma-joining labels into the column -- was rejected:
    it is read by exact equality in four places, so it would have produced a
    bogus "cost_overrun,ghost_asset" row in this table and quietly dropped
    recall for both real labels.

    A stacked work therefore appears under BOTH its labels, which is the
    honest accounting: each label's recall is measured over every work that
    genuinely carries it. It also means the per-label counts sum to more than
    the number of distinct planted works, which is why the totals below count
    distinct work_ids rather than adding the columns up.
    """
    rows = session.execute(text("""
        SELECT works.planted_anomaly AS label,
               works.work_id AS subject_id,
               COALESCE(scores.total_score, 0) AS total_score
        FROM works
        LEFT JOIN scores
               ON scores.subject_type = 'work'
              AND scores.subject_id = works.work_id
        WHERE works.planted_anomaly IS NOT NULL
        ORDER BY works.planted_anomaly, works.work_id
    """)).mappings().all()

    truth: dict[str, list[tuple[int, int]]] = {}
    for row in rows:
        truth.setdefault(row["label"], []).append(
            (row["subject_id"], row["total_score"]))

    # The secondary labels of the stacked works.
    extra = session.execute(text("""
        SELECT audit_log.detail AS label,
               audit_log.subject_id AS subject_id,
               COALESCE(scores.total_score, 0) AS total_score
        FROM audit_log
        LEFT JOIN scores
               ON scores.subject_type = 'work'
              AND scores.subject_id = audit_log.subject_id
        WHERE audit_log.action = 'planted_anomaly'
          AND audit_log.subject_type = 'work'
        ORDER BY audit_log.detail, audit_log.subject_id
    """)).mappings().all()

    for row in extra:
        truth.setdefault(row["label"], []).append(
            (row["subject_id"], row["total_score"]))
    return truth


def load_subject_truth(session, subject_type: str,
                       label: str) -> list[tuple[int, int]]:
    """[(subject_id, total_score)] for an MP- or vendor-level label.

    Ground truth comes from audit_log rather than a planted_anomaly column,
    because neither mps nor vendors has one -- see record_planted_subjects in
    generate_data.py.

    The scores join filters subject_type BEFORE matching subject_id. Without
    that filter a vendor score with subject_id = 3 would match MP 3 just as
    happily, and the failure would be silent.
    """
    rows = session.execute(text("""
        SELECT audit_log.subject_id AS subject_id,
               COALESCE(scores.total_score, 0) AS total_score
        FROM audit_log
        LEFT JOIN scores
               ON scores.subject_type = :subject_type
              AND scores.subject_id = audit_log.subject_id
        WHERE audit_log.action = 'planted_anomaly'
          AND audit_log.subject_type = :subject_type
          AND audit_log.detail = :label
        ORDER BY audit_log.subject_id
    """), {"subject_type": subject_type, "label": label}).mappings().all()
    return [(row["subject_id"], row["total_score"]) for row in rows]


def load_clean_work_scores(session) -> list[int]:
    """Scores of every work the generator did NOT plant.

    These are the false-positive population: each one that reaches the alert
    threshold is an officer sent to verify a work that was never anomalous.
    """
    rows = session.execute(text("""
        SELECT COALESCE(scores.total_score, 0) AS total_score
        FROM works
        LEFT JOIN scores
               ON scores.subject_type = 'work'
              AND scores.subject_id = works.work_id
        WHERE works.planted_anomaly IS NULL
        ORDER BY works.work_id
    """)).mappings().all()
    return [row["total_score"] for row in rows]


def summarise(scored: list[tuple[int, int]]) -> dict:
    """Detected and alerted counts for one label."""
    planted = len(scored)
    detected = sum(1 for _, score in scored if score > 0)
    alerted = sum(1 for _, score in scored
                  if score >= config.ALERT_MIN_SCORE)
    return {
        "planted": planted,
        "detected": detected,
        "alerted": alerted,
        "detected_rate": detected / planted if planted else 0.0,
        "recall": alerted / planted if planted else 0.0,
    }


def evaluate(session) -> dict:
    """Every label, plus the overall false-positive and precision figures."""
    work_truth = load_work_truth(session)

    labels = []
    for label in WORK_LABELS:
        labels.append(("work", label, summarise(work_truth.get(label, []))))
    for subject_type, label in SUBJECT_LABELS:
        labels.append((subject_type, label, summarise(
            load_subject_truth(session, subject_type, label))))

    clean = load_clean_work_scores(session)
    false_alerts = sum(1 for score in clean
                       if score >= config.ALERT_MIN_SCORE)

    planted_total = sum(row["planted"] for _, _, row in labels)

    # Counted over DISTINCT work_ids, not by adding the per-label columns up.
    # A stacked work appears under both of its labels -- correctly, since each
    # label's recall is measured over every work carrying it -- so summing the
    # columns would count those works twice and overstate both the planted
    # total and the catch rate.
    work_scores: dict[int, int] = {}
    for label in WORK_LABELS:
        for work_id, score in work_truth.get(label, []):
            work_scores[work_id] = score

    work_planted = len(work_scores)
    work_caught = sum(1 for score in work_scores.values()
                      if score >= config.ALERT_MIN_SCORE)

    return {
        "labels": labels,
        "clean_works": len(clean),
        "false_alerts": false_alerts,
        "false_positive_rate": false_alerts / len(clean) if clean else 0.0,
        "work_planted": work_planted,
        "work_caught": work_caught,
        "recall": work_caught / work_planted if work_planted else 0.0,
        # Of the alerts an officer opens, how many were genuinely planted.
        # The question they actually ask, and not answerable from recall.
        "precision": (work_caught / (work_caught + false_alerts)
                      if (work_caught + false_alerts) else 0.0),
        "planted_total": planted_total,
    }


def main() -> None:
    with get_session() as session:
        result = evaluate(session)

    print(f"Detection accuracy, alert threshold "
          f"{config.ALERT_MIN_SCORE}\n")

    print(f"  {'label':24} {'level':8} {'planted':>8} {'detected':>10} "
          f"{'alerted':>9} {'recall':>8}")
    for level, label, row in result["labels"]:
        print(f"  {label:24} {level:8} {row['planted']:>8} "
              f"{row['detected']:>9} ({row['detected_rate'] * 100:>3.0f}%) "
              f"{row['alerted']:>8} {row['recall'] * 100:>7.1f}%")

    print(f"\n  Work-level totals")
    print(f"    planted            {result['work_planted']:>6}")
    print(f"    reached an officer {result['work_caught']:>6}")
    print(f"    recall             {result['recall'] * 100:>5.1f}%")

    print(f"\n  False positives")
    print(f"    clean works        {result['clean_works']:>6}")
    print(f"    falsely alerted    {result['false_alerts']:>6}")
    print(f"    false-positive rate{result['false_positive_rate'] * 100:>5.2f}%")

    print(f"\n  Precision           {result['precision'] * 100:>5.1f}%"
          "   (of the alerts raised, how many were genuinely planted)")

    print("\n  detected = the checks scored it above zero.")
    print("  alerted  = it reached the threshold and an officer sees it.")
    print("  The gap is a threshold decision, not a detection failure:")
    print("  several checks cap below the alert threshold and need a second")
    print("  signal before a work reaches the worklist.")


if __name__ == "__main__":
    main()
