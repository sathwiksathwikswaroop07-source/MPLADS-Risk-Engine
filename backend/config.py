"""Every threshold, point cap and tunable constant in the risk engine.

Nothing here is computed at import time except the database path. Step 03
must be able to retune any detection threshold by editing this file alone,
without touching checks.py.
"""

from datetime import date
from pathlib import Path

# ---------------------------------------------------------------------------
# The reference date
# ---------------------------------------------------------------------------

# Pinned, never moved. Every date calculation in the codebase reads this
# rather than asking the system clock for the current date; otherwise delay
# scores drift every day, the demo changes overnight, and the recall number
# on the slide stops matching what the app shows.
REFERENCE_DATE = date(2026, 9, 15)


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

# Resolved and absolute, so the engine finds the same file whatever the
# caller's working directory and whatever path the module was invoked by.
DB_PATH = Path(__file__).resolve().parent / "mplads.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"


# ---------------------------------------------------------------------------
# Work categories
# ---------------------------------------------------------------------------

# A peer group is always a single work_type, so units never mix within a
# comparison.
#
# bridge is measured in km rather than counted: span is most of what drives
# a bridge's cost, and counting would put a 40 m culvert and an 800 m river
# crossing in the same peer group.
WORK_TYPE_UNITS = {
    "road": "km",
    "drain": "km",
    "bridge": "km",
    "borewell": "count",
    "streetlight": "count",
    "hospital": "beds",
    "community_hall": "sqm",
    "school_wall": "sqm",
}
WORK_TYPES = tuple(WORK_TYPE_UNITS)

TERRAINS = ("plain", "hilly", "coastal")
AREA_TYPES = ("metro", "urban", "semi_urban", "rural")
WORK_STATUSES = ("recommended", "sanctioned", "in_progress", "completed")

# From the MPLADS guidelines. Re-verify against the current official text
# before final submission; the 2023 revision changed several provisions.
PERMITTED_WORK_CATEGORIES = (
    "drinking water",
    "education",
    "electricity",
    "health",
    "sanitation",
    "roads and pathways",
    "bridges",
    "irrigation",
    "community centres",
    "public libraries",
    "sports facilities",
    "non-conventional energy",
    "urban development",
    "animal husbandry",
)

# These are what C3 actually flags.
NOT_PERMITTED_WORK_CATEGORIES = (
    "office or residential buildings for government bodies",
    "memorials and statues",
    "places of religious worship",
    "land acquisition",
    "assets for individual benefit",
    "works on private land",
    "grants to commercial organisations",
)


# ---------------------------------------------------------------------------
# Expected duration, keyed by (work_type, area_type)
# ---------------------------------------------------------------------------

# Keyed by both dimensions, not by work_type alone: a metro road takes
# longer than a rural one for permissions and utility shifting, not for
# construction. Treating them the same makes every metro work look delayed.
#
# Used at sanction time to set works.expected_completion_on, which is stored
# rather than derived so the citizen page's "overdue by N days" and the
# delay check cannot disagree about what overdue means.
EXPECTED_DURATION_DAYS = {
    ("road", "metro"): 270,
    ("road", "urban"): 240,
    ("road", "semi_urban"): 210,
    ("road", "rural"): 180,
    ("drain", "metro"): 210,
    ("drain", "urban"): 180,
    ("drain", "semi_urban"): 150,
    ("drain", "rural"): 120,
    ("bridge", "metro"): 540,
    ("bridge", "urban"): 480,
    ("bridge", "semi_urban"): 420,
    ("bridge", "rural"): 365,
    ("borewell", "metro"): 90,
    ("borewell", "urban"): 75,
    ("borewell", "semi_urban"): 60,
    ("borewell", "rural"): 60,
    ("streetlight", "metro"): 120,
    ("streetlight", "urban"): 100,
    ("streetlight", "semi_urban"): 90,
    ("streetlight", "rural"): 75,
    ("hospital", "metro"): 730,
    ("hospital", "urban"): 640,
    ("hospital", "semi_urban"): 550,
    ("hospital", "rural"): 480,
    ("community_hall", "metro"): 420,
    ("community_hall", "urban"): 365,
    ("community_hall", "semi_urban"): 300,
    ("community_hall", "rural"): 270,
    ("school_wall", "metro"): 150,
    ("school_wall", "urban"): 120,
    ("school_wall", "semi_urban"): 100,
    ("school_wall", "rural"): 90,
}

# Defensive only. Every (work_type, area_type) pair above is populated, but
# a new work_type added without its four rows would otherwise raise
# KeyError deep inside the generator.
DEFAULT_DURATION_DAYS = 180


# ---------------------------------------------------------------------------
# Point caps
# ---------------------------------------------------------------------------

# No single check may award more than its cap, and total_score is clamped
# to 0-100 after summing.
C1_MAX_POINTS = 35      # cost outlier             (work)
C2_MAX_POINTS = 25      # delay                    (work)
C2B_MAX_POINTS = 8      # predicted stall          (work)
C3_MAX_POINTS = 15      # work compliance          (work)
C5_MAX_POINTS = 20      # duplicate                (work)
C6_MAX_POINTS = 15      # citizen reports          (work)
C7_MAX_POINTS = 35      # paid, no proof of work   (work)
C3_MP_MAX_POINTS = 25   # quota compliance         (mp)
C4_MAX_POINTS = 15      # utilisation              (district)

MAX_TOTAL_SCORE = 100


# ---------------------------------------------------------------------------
# C1 - cost outlier
# ---------------------------------------------------------------------------

# Points scale with distance past the upper IQR fence (Q3 + 1.5 * IQR).
# Each entry is (median_multiple, points); the first rung is the fence
# itself rather than a multiple of the median.
C1_IQR_MULTIPLIER = 1.5
C1_FENCE_POINTS = 10
C1_RATIO_BANDS = (
    (2.0, 20),
    (3.0, 28),
    (4.0, C1_MAX_POINTS),
)


# ---------------------------------------------------------------------------
# C2 - delay
# ---------------------------------------------------------------------------

# (min_days, max_days, points). max_days of None means unbounded.
# Measured from REFERENCE_DATE while status != 'completed'.
C2_DELAY_BANDS = (
    (180, 364, 10),
    (365, 539, 18),
    (540, None, C2_MAX_POINTS),
)


# ---------------------------------------------------------------------------
# C2b - predicted stall
# ---------------------------------------------------------------------------

# Not yet late, but on track to be. This is the "early warning mechanism"
# the problem statement asks for, and it is what separates "already a
# problem" from "about to become one".
#
# Fires when a work's reported progress is this far below what the elapsed
# share of its expected duration implies, AND nobody has touched the record
# in C2B_STALE_DAYS. Both conditions, not either.
C2B_STALE_DAYS = 90
C2B_PROGRESS_SHORTFALL = 0.30


# ---------------------------------------------------------------------------
# C5 - duplicate detection
# ---------------------------------------------------------------------------

C5_UNIT_COST_TOLERANCE = 0.10   # within 10% unit cost
C5_WINDOW_DAYS = 60             # sanctioned within 60 days of each other


# ---------------------------------------------------------------------------
# C6 - citizen reports
# ---------------------------------------------------------------------------

# (min_distinct_reporters, points). Only verified complaints count, and the
# UNIQUE(work_id, user_id) constraint is what makes the count meaningful.
C6_REPORT_BANDS = (
    (1, 5),
    (2, 10),
    (4, C6_MAX_POINTS),
)


# ---------------------------------------------------------------------------
# C7 - paid, no proof of work
# ---------------------------------------------------------------------------

# The ghost-asset check. Components are summed, then capped at
# C7_MAX_POINTS. No single component is conclusive; the combination is.

# Money moving ahead of work. gap = payment_ratio - progress_ratio, where
# payment_ratio is sum(payments.amount) / cost. Ascending, like the others.
C7_PAYMENT_GAP_BANDS = (
    (0.20, 10),
    (0.35, 18),
    (0.50, 25),
)

# Marked completed with zero rows in the evidence table -- no photo, no
# completion certificate, no handover record. The CAG's most common finding.
C7_COMPLETED_NO_EVIDENCE = 15

# Nobody has touched the record in this long while most of the money has
# gone. Works whether or not progress_pct is meaningful, which is why it is
# the fallback when progress reporting is absent.
C7_STALE_DAYS = 180
C7_STALE_MIN_PAYMENT_RATIO = 0.50
C7_STALE_WHILE_PAID = 12

# Completed in less than this fraction of its expected duration -- a 10 km
# road finished eight days after sanction.
C7_FAST_FRACTION = 0.15
C7_IMPLAUSIBLY_FAST = 12

# The same completion photograph submitted as proof for another work.
# A self-join on evidence.photo_hash; the hardest component to explain away.
C7_DUPLICATE_PHOTO = 20


# ---------------------------------------------------------------------------
# C3-MP - SC/ST quota compliance
# ---------------------------------------------------------------------------

SC_AREA_FLOOR = 0.15    # 15% of released funds
ST_AREA_FLOOR = 0.075   # 7.5% of released funds
SC_SHORTFALL_MAX_POINTS = 15
ST_SHORTFALL_MAX_POINTS = 10


# ---------------------------------------------------------------------------
# C4 - district utilisation
# ---------------------------------------------------------------------------

# Measured AGAINST THE CALENDAR, not as a raw unspent balance.
#
# Since April 2023 the whole annual entitlement lands at the start of the
# financial year and is drawn down as needed. A flat "spent/released below
# 50%" rule would therefore flag every district in the country every June,
# legitimately unspent. Instead, compare the spend ratio with the share of
# the financial year that has elapsed: three months in, 25% spent is on
# track and 5% is not.
C4_CALENDAR_TOLERANCE = 0.30      # spend ratio this far behind year elapsed
C4_BEHIND_CALENDAR_POINTS = 10

# March rush: a disproportionate share of the year's spend falling in the
# final quarter, which usually means money moved to avoid lapsing rather
# than because work was done.
C4_Q4_SPEND_CEILING = 0.60
C4_Q4_BUNCHING_POINTS = 8


# ---------------------------------------------------------------------------
# Peer group ladder for C1
# ---------------------------------------------------------------------------

PEER_GROUP_MIN_ROWS = 8

# Tried in order; stop at the first rung with at least PEER_GROUP_MIN_ROWS
# rows. If even the last rung falls short, skip C1, award zero, and record
# the reason in scores.checks_skipped -- do not guess from a median of three.
#
# area_type is given up after district deliberately: urbanisation explains
# more cost variance than geography does, so it is worth keeping longer.
PEER_GROUP_LADDER = (
    ("work_type", "terrain", "area_type", "district_id"),
    ("work_type", "terrain", "area_type", "state_id"),
    ("work_type", "terrain", "area_type"),
    ("work_type", "area_type"),
    ("work_type",),
)


# ---------------------------------------------------------------------------
# Severity
# ---------------------------------------------------------------------------

# Below ALERT_MIN_SCORE a subject still gets a scores row, but no alert.
ALERT_MIN_SCORE = 25

# (min_score, severity), highest band first.
SEVERITY_BANDS = (
    (70, "critical"),
    (45, "high"),
    (ALERT_MIN_SCORE, "medium"),
)


# ---------------------------------------------------------------------------
# Scheme parameters
# ---------------------------------------------------------------------------

# Since 1 April 2023 the annual entitlement is released as a single annual
# instalment, not two of Rs 2.5 crore. Model years either side of that
# change correctly if the dataset spans them.
ANNUAL_ENTITLEMENT = 50_000_000          # Rs 5 crore, in rupees
SINGLE_INSTALMENT_FROM = date(2023, 4, 1)
HALF_INSTALMENT = ANNUAL_ENTITLEMENT // 2


# ---------------------------------------------------------------------------
# Data generation (step 02)
# ---------------------------------------------------------------------------

# Fixed seed. Determinism is a project rule: the same command must rebuild
# the same database, or the recall number stops being reproducible.
RANDOM_SEED = 26102

# The peer ladder has three dimensions plus district. At 2000 works its
# first rung averages three rows, which is not a median -- C1 would skip
# almost everything. 4500 puts most comparisons on rung 3 with a real
# sample behind them.
TARGET_WORK_COUNT = 4500

# Planted with a ground-truth label in works.planted_anomaly, so
# evaluate.py can report recall per category. Roughly 290 of 4500.
#
# Everything not listed here must be genuinely clean. If clean rows also
# trip checks, the false-positive rate is real and the fix is to loosen
# thresholds, not to hide it.
PLANTED_ANOMALY_COUNTS = {
    "cost_overrun": 60,           # unit cost 3-6x the peer median
    "long_delay": 80,             # sanctioned 400-700 days ago, unfinished
    "impossible_date": 20,        # completed_on before sanctioned_on
    "ineligible_work": 20,        # category from the not-permitted list
    "duplicate_pair": 40,         # 20 pairs, near-identical within 60 days
    "payment_ahead_of_work": 40,  # payment ratio 0.75-0.95, progress 0.10-0.30
    "ghost_asset": 30,            # complete, fully paid, no evidence rows
}
PLANTED_QUOTA_SHORTFALL_MPS = 4   # MPs forced under the 15% SC floor

# Some works must be generated with progress_pct = 0 and no
# progress_updates rows, so the graceful-degradation path is exercised by
# the data rather than only by intention.
WORKS_WITHOUT_PROGRESS_DATA = 400


# ---------------------------------------------------------------------------
# Authentication (step 05)
# ---------------------------------------------------------------------------

JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 12

# Read from the environment at runtime and never stored here or committed.
# PyJWT warns below 32 bytes for HS256.
JWT_SECRET_ENV_VAR = "JWT_SECRET"
JWT_MIN_SECRET_BYTES = 32

# Roles that may act on alerts. MPs and the Ministry are view-only: under
# the scheme an MP recommends works while the District Authority sanctions,
# executes and verifies them, so letting an MP close an alert on their own
# constituency's work would invert the accountability the scheme rests on.
ALERT_ACTOR_ROLES = ("district_officer", "state_officer")

# Alerts about an MP or a district are routed to the State Officer, never
# only to the person the alert is about.
SUBJECT_ROUTING = {
    "work": "district_officer",
    "mp": "state_officer",
    "district": "state_officer",
}