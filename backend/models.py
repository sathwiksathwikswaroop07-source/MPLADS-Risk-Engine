"""SQLAlchemy models for the MPLADS Risk Engine.

Sixteen tables in five groups: reference data, accounts, the scheme's core
records, the system's output, and the audit trail.

This module deliberately imports no engine, so a test harness can import it
without opening a connection. Engine plumbing lives in db.py.

Two conventions run through every table:

* Dates are ISO-8601 strings typed String, never Date or DateTime. SQLite
  has no date type, SQLAlchemy's date types add silent conversion, and ISO
  text sorts and compares correctly in both Python and SQL.
* Money is Integer rupees. No Float or Numeric for currency anywhere.

Column declaration order is normative: create_all emits columns in
declaration order and the schema tests check their positions.
"""

from sqlalchemy import (
    CheckConstraint,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# ===========================================================================
# Group A - Reference data (geography and people)
# ===========================================================================
# Referenced by ID everywhere else. Storing district as free text on every
# work makes filtering and role scoping unreliable the first time a name is
# spelled two ways.


class State(Base):
    __tablename__ = "states"

    state_id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    code = Column(String, nullable=False, unique=True)


class District(Base):
    __tablename__ = "districts"

    district_id = Column(Integer, primary_key=True)
    state_id = Column(Integer, ForeignKey("states.state_id"), nullable=False)
    name = Column(String, nullable=False)
    is_hill_district = Column(Integer, nullable=False, default=0)
    default_area_type = Column(String, nullable=False, default="rural")

    # is_hill_district and default_area_type are generation hints only. They
    # seed sensible defaults for a new work's terrain and area_type; the
    # values that matter for detection live on the work itself. Nothing in
    # checks.py may read either column -- doing so would excuse a flat road
    # in a hill district as expensive-by-terrain.
    __table_args__ = (
        UniqueConstraint("state_id", "name"),
        CheckConstraint("is_hill_district IN (0,1)"),
        CheckConstraint(
            "default_area_type IN ('metro','urban','semi_urban','rural')"
        ),
    )


class Constituency(Base):
    __tablename__ = "constituencies"

    constituency_id = Column(Integer, primary_key=True)
    state_id = Column(Integer, ForeignKey("states.state_id"), nullable=False)
    name = Column(String, nullable=False)
    house = Column(String, nullable=False)

    # A Rajya Sabha member has no constituency in the ordinary sense; those
    # rows use the state name with house = 'rajya_sabha'.
    __table_args__ = (
        UniqueConstraint("state_id", "name", "house"),
        CheckConstraint("house IN ('lok_sabha','rajya_sabha')"),
    )


class MP(Base):
    __tablename__ = "mps"

    mp_id = Column(Integer, primary_key=True)
    full_name = Column(String, nullable=False)
    house = Column(String, nullable=False)
    constituency_id = Column(
        Integer, ForeignKey("constituencies.constituency_id"), nullable=False
    )
    state_id = Column(Integer, ForeignKey("states.state_id"), nullable=False)
    # term_start/term_end are not decoration: a work recommended outside an
    # MP's term is a data-integrity flag in C3.
    term_start = Column(String, nullable=False)
    term_end = Column(String)
    is_active = Column(Integer, nullable=False, default=1)

    __table_args__ = (
        CheckConstraint("house IN ('lok_sabha','rajya_sabha')"),
        CheckConstraint("is_active IN (0,1)"),
    )


class Agency(Base):
    __tablename__ = "agencies"

    agency_id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    agency_type = Column(String, nullable=False)
    district_id = Column(
        Integer, ForeignKey("districts.district_id"), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "agency_type IN ('pwd','zilla_parishad','municipal','other')"
        ),
    )


class Vendor(Base):
    __tablename__ = "vendors"

    vendor_id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    district_id = Column(
        Integer, ForeignKey("districts.district_id"), nullable=False
    )
    # A hash, never a real or realistic PAN. This is generated data and must
    # not resemble a genuine identity document.
    pan_hash = Column(String)
    address = Column(String)
    registered_on = Column(String)
    is_active = Column(Integer, nullable=False, default=1)

    __table_args__ = (CheckConstraint("is_active IN (0,1)"),)


# ===========================================================================
# Group B - Accounts and access
# ===========================================================================


class User(Base):
    """Everyone who can log in, including citizens.

    Separate from mps: an MP is a person in the scheme, a user is a login.
    One MP may have no login; one login may be a clerk acting for a district.

    scope_type + scope_id decide which rows are visible. role decides which
    actions are allowed. Keeping the two separate is what stops the role
    system becoming unmaintainable.
    """

    __tablename__ = "users"

    user_id = Column(Integer, primary_key=True)
    username = Column(String, nullable=False, unique=True)
    password_hash = Column(String, nullable=False)  # werkzeug - never plaintext
    full_name = Column(String, nullable=False)
    role = Column(String, nullable=False)
    scope_type = Column(String, nullable=False)
    # Deliberately NOT a ForeignKey: the target table depends on scope_type
    # (constituency / district / state / national), so no single FK can
    # express it. Validated in auth.py at step 05. Do not "fix" this.
    scope_id = Column(Integer)
    mp_id = Column(Integer, ForeignKey("mps.mp_id"))  # only for role = 'mp'
    is_active = Column(Integer, nullable=False, default=1)
    created_at = Column(String, nullable=False)
    last_login_at = Column(String)

    __table_args__ = (
        CheckConstraint(
            "role IN ('citizen','mp','district_officer','state_officer',"
            "'ministry')"
        ),
        CheckConstraint(
            "scope_type IN ('constituency','district','state','national')"
        ),
        CheckConstraint("is_active IN (0,1)"),
    )


# ===========================================================================
# Group C - The scheme's core records
# ===========================================================================


class Allocation(Base):
    """One row per MP per financial year.

    No SC/ST spend columns: those are derived by summing works where
    is_sc_area = 1 / is_st_area = 1. Storing them alongside the derived sum
    guarantees the two eventually disagree.
    """

    __tablename__ = "allocations"

    allocation_id = Column(Integer, primary_key=True)
    mp_id = Column(Integer, ForeignKey("mps.mp_id"), nullable=False)
    fy = Column(String, nullable=False)
    entitlement = Column(Integer, nullable=False)
    released = Column(Integer, nullable=False)
    spent = Column(Integer, nullable=False)
    released_on = Column(String)

    __table_args__ = (UniqueConstraint("mp_id", "fy"),)


class Work(Base):
    """The central table. Twenty-seven columns.

    Cost convention: always COALESCE(final_cost, estimated_cost), never
    final_cost alone -- it is NULL for every unfinished work, which would
    silently exclude exactly the works most likely to be problems.

    planted_anomaly exists only so evaluate.py can measure recall. It must
    never be read by checks.py, and must be excluded from every response
    model in step 04.
    """

    __tablename__ = "works"

    work_id = Column(Integer, primary_key=True)
    mp_id = Column(Integer, ForeignKey("mps.mp_id"), nullable=False)
    constituency_id = Column(
        Integer, ForeignKey("constituencies.constituency_id"), nullable=False
    )
    district_id = Column(
        Integer, ForeignKey("districts.district_id"), nullable=False
    )
    agency_id = Column(Integer, ForeignKey("agencies.agency_id"))  # pre-sanction
    vendor_id = Column(Integer, ForeignKey("vendors.vendor_id"))   # pre-award
    fy = Column(String, nullable=False)
    work_type = Column(String, nullable=False)
    description = Column(String, nullable=False)
    terrain = Column(String, nullable=False)
    # Urbanisation, independent of terrain: Mumbai is coastal and metro,
    # Shimla is hilly and urban. A metro road legitimately costs several
    # times a rural one, so comparing them without this manufactures false
    # positives. Seeded from districts.default_area_type but stored per work,
    # because one district contains both a metro core and rural talukas.
    area_type = Column(String, nullable=False)
    quantity = Column(Float, nullable=False)
    unit = Column(String, nullable=False)
    estimated_cost = Column(Integer, nullable=False)
    final_cost = Column(Integer)
    # The gap between recommended_on and sanctioned_on is the District
    # Authority's sanction lag -- a distinct signal from execution delay.
    recommended_on = Column(String, nullable=False)
    sanctioned_on = Column(String)
    # Stored, not computed. Set at sanction time as sanctioned_on +
    # EXPECTED_DURATION_DAYS[(work_type, area_type)]. Stored rather than
    # derived because the citizen page shows "overdue by N days" and
    # checks.py computes delay from the same figure; deriving it twice
    # guarantees the two eventually disagree about what overdue means.
    expected_completion_on = Column(String)
    completed_on = Column(String)
    status = Column(String, nullable=False)
    # May be zero or stale; checks must handle that rather than assume it is
    # populated.
    progress_pct = Column(Float, nullable=False, default=0)
    # When the record was last touched at all. A work nobody has updated in
    # 400 days while money moved is worth verifying whether or not
    # progress_pct is meaningful.
    last_updated_on = Column(String, nullable=False)
    lat = Column(Float)
    lon = Column(Float)
    is_sc_area = Column(Integer, nullable=False, default=0)
    is_st_area = Column(Integer, nullable=False, default=0)
    planted_anomaly = Column(String)

    __table_args__ = (
        CheckConstraint(
            "status IN ('recommended','sanctioned','in_progress','completed')"
        ),
        CheckConstraint("terrain IN ('plain','hilly','coastal')"),
        CheckConstraint("area_type IN ('metro','urban','semi_urban','rural')"),
        CheckConstraint("unit IN ('km','count','sqm','beds')"),
        CheckConstraint("progress_pct BETWEEN 0 AND 100"),
        CheckConstraint("is_sc_area IN (0,1)"),
        CheckConstraint("is_st_area IN (0,1)"),
        # Column order matches the peer-group ladder, so each rung is a
        # prefix of this index.
        Index("idx_works_peer", "work_type", "terrain", "area_type",
              "district_id"),
        Index("idx_works_mp", "mp_id", "fy"),
        Index("idx_works_district", "district_id", "status"),
        Index("idx_works_constituency", "constituency_id"),
    )


class Payment(Base):
    """One row per tranche.

    Without this table there is no payment-versus-progress gap, which is the
    strongest signal available for a work that was paid for but not built.
    """

    __tablename__ = "payments"

    payment_id = Column(Integer, primary_key=True)
    work_id = Column(Integer, ForeignKey("works.work_id"), nullable=False)
    vendor_id = Column(Integer, ForeignKey("vendors.vendor_id"))
    tranche_no = Column(Integer, nullable=False)
    amount = Column(Integer, nullable=False)
    paid_on = Column(String, nullable=False)
    progress_pct_at_payment = Column(Float)
    voucher_ref = Column(String)

    __table_args__ = (
        UniqueConstraint("work_id", "tranche_no"),
        CheckConstraint("amount > 0"),
        Index("idx_payments_work", "work_id"),
    )


class ProgressUpdate(Base):
    """The history of the progress field, not just its current value.

    A misstated progress number is hard to spot; a number that jumped from
    20 to 90 in one day, or whose whole history was entered on a single
    afternoon, is not.
    """

    __tablename__ = "progress_updates"

    update_id = Column(Integer, primary_key=True)
    work_id = Column(Integer, ForeignKey("works.work_id"), nullable=False)
    progress_pct = Column(Float, nullable=False)
    reported_on = Column(String, nullable=False)
    reported_by = Column(String)
    note = Column(String)

    __table_args__ = (
        CheckConstraint("progress_pct BETWEEN 0 AND 100"),
        Index("idx_progress_work", "work_id", "reported_on"),
    )


class Evidence(Base):
    """Photographs and documents attached to a work.

    The absence of rows here is itself the signal: a work marked complete
    with no evidence row is exactly what needs verification.
    """

    __tablename__ = "evidence"

    evidence_id = Column(Integer, primary_key=True)
    work_id = Column(Integer, ForeignKey("works.work_id"), nullable=False)
    kind = Column(String, nullable=False)
    file_path = Column(String)
    photo_hash = Column(String)  # perceptual hash - duplicate photo detection
    exif_lat = Column(Float)
    exif_lon = Column(Float)
    stage = Column(String)
    captured_at = Column(String)
    uploaded_at = Column(String, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "kind IN ('photo','completion_cert','handover','utilisation_cert')"
        ),
        CheckConstraint("stage IS NULL OR stage IN ('before','during','after')"),
        Index("idx_evidence_work", "work_id", "kind"),
        # The reused-photo check is a self-join on this.
        Index("idx_evidence_hash", "photo_hash"),
    )


# ===========================================================================
# Group D - Output of the system
# ===========================================================================


class Score(Base):
    """One row per subject per scoring run, for every subject.

    A clean work scoring 3 gets a row exactly as a flagged one scoring 78
    does. That is what lets the citizen project listing and the officer
    worklist read from the same place.

    The per-check columns are queryable in a way reasons_json is not:
    "which districts have a delay problem specifically" is a GROUP BY, and
    the dashboard's flags-by-type chart needs no JSON parsing. reasons_json
    stays for the sentences the UI prints; the columns carry the numbers.

    checks.py deletes and rebuilds this table on each run. Score history is
    out of scope for the prototype, though this shape would support it by
    dropping the unique constraint later.
    """

    __tablename__ = "scores"

    score_id = Column(Integer, primary_key=True)
    subject_type = Column(String, nullable=False)
    # Deliberately NOT a ForeignKey: the target table is polymorphic
    # (work / mp / district / vendor). Never join on this without first
    # filtering subject_type -- a district score with subject_id = 3 would
    # otherwise silently match work_id = 3. Do not "fix" this.
    subject_id = Column(Integer, nullable=False)
    total_score = Column(Integer, nullable=False)
    cost_points = Column(Integer, nullable=False, default=0)          # C1
    delay_points = Column(Integer, nullable=False, default=0)         # C2, C2b
    compliance_points = Column(Integer, nullable=False, default=0)    # C3, C3-MP
    duplicate_points = Column(Integer, nullable=False, default=0)     # C5
    public_points = Column(Integer, nullable=False, default=0)        # C6
    evidence_points = Column(Integer, nullable=False, default=0)      # C7
    utilisation_points = Column(Integer, nullable=False, default=0)   # C4
    reasons_json = Column(Text, nullable=False)
    checks_run = Column(Text, nullable=False)
    # A check whose required fields are absent records why here rather than
    # silently scoring zero, so the alert page can say "3 of 8 checks ran".
    checks_skipped = Column(Text, nullable=False)
    scored_on = Column(String, nullable=False)

    __table_args__ = (
        UniqueConstraint("subject_type", "subject_id"),
        CheckConstraint(
            "subject_type IN ('work','mp','district','vendor')"
        ),
        CheckConstraint("total_score BETWEEN 0 AND 100"),
        CheckConstraint("cost_points >= 0"),
        CheckConstraint("delay_points >= 0"),
        CheckConstraint("compliance_points >= 0"),
        CheckConstraint("duplicate_points >= 0"),
        CheckConstraint("public_points >= 0"),
        CheckConstraint("evidence_points >= 0"),
        CheckConstraint("utilisation_points >= 0"),
        Index("idx_scores_subj", "subject_type", "subject_id"),
        # The worklist sort.
        Index("idx_scores_total", "subject_type", "total_score"),
    )


class Alert(Base):
    """A thin workflow record pointing at a score.

    Created only when total_score >= 25. Below that the subject still gets a
    scores row, but no alert.

    verdict and resolution_note are not optional decoration: an officer must
    not be able to clear a large alert with a bare "visited" button. Both are
    required when status moves to resolved -- enforced in the API at step 04,
    not in the schema, so the constraint stays readable.

    snoozed_until is the honest alternative to a dismiss button: the alert
    returns instead of disappearing.
    """

    __tablename__ = "alerts"

    alert_id = Column(Integer, primary_key=True)
    score_id = Column(
        Integer, ForeignKey("scores.score_id"), nullable=False, unique=True
    )
    severity = Column(String, nullable=False)
    status = Column(String, nullable=False, default="open")
    verdict = Column(String)
    resolution_note = Column(String)
    snoozed_until = Column(String)
    assigned_to = Column(Integer, ForeignKey("users.user_id"))
    created_at = Column(String, nullable=False)
    resolved_at = Column(String)

    __table_args__ = (
        CheckConstraint("severity IN ('critical','high','medium')"),
        CheckConstraint(
            "status IN ('open','acknowledged','escalated','resolved')"
        ),
        CheckConstraint(
            "verdict IS NULL OR verdict IN ('substantiated',"
            "'not_substantiated','could_not_verify')"
        ),
        Index("idx_alerts_open", "status", "severity"),
    )


class Complaint(Base):
    """Public reports, filed by a logged-in citizen.

    UNIQUE(work_id, user_id) -- one complaint per citizen per work. That
    constraint is what makes C6's distinct-reporter count meaningful and
    stops one person inflating a score.

    Never store a raw phone number or device ID anywhere. This is a
    government platform handling reports about named public figures; treat
    identifying data as a liability.
    """

    __tablename__ = "complaints"

    complaint_id = Column(Integer, primary_key=True)
    work_id = Column(Integer, ForeignKey("works.work_id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    # Named `text`; take care not to shadow sqlalchemy.text where both are
    # needed -- import it as `from sqlalchemy import text as sql_text`.
    text = Column(String, nullable=False)
    photo_path = Column(String)
    lat = Column(Float)
    lon = Column(Float)
    verified = Column(Integer, nullable=False, default=0)
    verified_by = Column(Integer, ForeignKey("users.user_id"))
    created_at = Column(String, nullable=False)

    __table_args__ = (
        UniqueConstraint("work_id", "user_id"),
        CheckConstraint("verified IN (0,1)"),
        Index("idx_complaints_work", "work_id", "verified"),
    )


class Rating(Base):
    """A citizen's 1-5 star rating of a completed work.

    UNIQUE(work_id, user_id) for the same reason complaints carry it: one
    person must not be able to move an average by rating repeatedly.

    Deliberately NOT an input to any check. An unverified public rating
    driving a risk score would be an accusation the system has not earned --
    and it would be trivially brigadable. It is context for a human reading
    the page, and context for the officer deciding whether to visit.
    """

    __tablename__ = "ratings"

    rating_id = Column(Integer, primary_key=True)
    work_id = Column(Integer, ForeignKey("works.work_id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    stars = Column(Integer, nullable=False)
    comment = Column(String)
    created_at = Column(String, nullable=False)

    __table_args__ = (
        UniqueConstraint("work_id", "user_id"),
        CheckConstraint("stars BETWEEN 1 AND 5"),
        Index("idx_ratings_work", "work_id"),
    )


# ===========================================================================
# Group E - Accountability
# ===========================================================================


class AuditLog(Base):
    """Every state-changing action.

    Append-only. Nothing in the codebase may UPDATE or DELETE from it.
    """

    __tablename__ = "audit_log"

    log_id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.user_id"))  # NULL for system
    action = Column(String, nullable=False)
    # subject_type + subject_id say what the action was done to -- an alert,
    # a work, an MP -- or NULL for actions with no target, such as login.
    # Polymorphic, so deliberately NOT a ForeignKey. Do not "fix" this.
    subject_type = Column(String)
    subject_id = Column(Integer)
    detail = Column(String)
    created_at = Column(String, nullable=False)
