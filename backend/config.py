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

# Absolute, so the engine resolves the same file whatever the caller's cwd.
DATABASE_URL = f"sqlite:///{Path(__file__).parent / 'mplads.db'}"


# ---------------------------------------------------------------------------
# Work categories
# ---------------------------------------------------------------------------

# A peer group is always a single work_type, so units never mix within a
# comparison.
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


# ---------------------------------------------------------------------------
# Point caps
# ---------------------------------------------------------------------------

# No single check may award more than its cap, and total_score is clamped
# to 0-100 after summing.
C1_MAX_POINTS = 35   # cost outlier            (work)
C2_MAX_POINTS = 25   # delay                   (work)
C3_MAX_POINTS = 15   # work compliance         (work)
C5_MAX_POINTS = 20   # duplicate               (work)
C6_MAX_POINTS = 15   # citizen reports         (work)
C7_MAX_POINTS = 20   # paid, no proof of work  (work)
C3_MP_MAX_POINTS = 25   # quota compliance     (mp)
C4_MAX_POINTS = 15   # utilisation             (district)

MAX_TOTAL_SCORE = 100


# ---------------------------------------------------------------------------
# C1 — cost outlier
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
# C2 — delay
# ---------------------------------------------------------------------------

# (min_days, max_days, points). max_days of None means unbounded.
# Measured from REFERENCE_DATE while status != 'completed'.
C2_DELAY_BANDS = (
    (180, 364, 10),
    (365, 539, 18),
    (540, None, C2_MAX_POINTS),
)


# ---------------------------------------------------------------------------
# C5 — duplicate detection
# ---------------------------------------------------------------------------

C5_UNIT_COST_TOLERANCE = 0.10   # within 10% unit cost
C5_WINDOW_DAYS = 60             # sanctioned within 60 days of each other


# ---------------------------------------------------------------------------
# C6 — citizen reports
# ---------------------------------------------------------------------------

# (min_distinct_reporters, points). Only verified complaints count, and the
# UNIQUE(work_id, user_id) constraint is what makes the count meaningful.
C6_REPORT_BANDS = (
    (1, 5),
    (2, 10),
    (4, C6_MAX_POINTS),
)


# ---------------------------------------------------------------------------
# C3-MP — SC/ST quota compliance
# ---------------------------------------------------------------------------

SC_AREA_FLOOR = 0.15    # 15% of released funds
ST_AREA_FLOOR = 0.075   # 7.5% of released funds
SC_SHORTFALL_MAX_POINTS = 15
ST_SHORTFALL_MAX_POINTS = 10


# ---------------------------------------------------------------------------
# C4 — district utilisation
# ---------------------------------------------------------------------------

C4_UTILISATION_FLOOR = 0.50       # spent/released below this
C4_UTILISATION_POINTS = 10
C4_Q4_SPEND_CEILING = 0.60        # more than this share falling in Jan-Mar
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
