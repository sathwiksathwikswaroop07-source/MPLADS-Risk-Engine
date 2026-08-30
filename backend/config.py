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


# ===========================================================================
# Generation parameters -- read by generate_data.py ONLY
# ===========================================================================
# checks.py must never import anything below this line. Detection compares a
# work against its actual peers in the data; scoring against the baseline we
# generated from would be marking our own homework and the recall number
# would mean nothing.


# ---------------------------------------------------------------------------
# Baseline unit costs
# ---------------------------------------------------------------------------

# Rupees per unit of `quantity`, before area and terrain multipliers. Units
# follow WORK_TYPE_UNITS above: km, count, beds or sqm.
#
# These live here rather than inside the generator because evaluate.py needs
# to know what "normal" was in order to plant a work at 4x normal.
BASE_UNIT_COST = {
    "road": 4_500_000,          # per km
    "drain": 2_200_000,         # per km
    "bridge": 28_000_000,       # per km
    "borewell": 145_000,        # per borewell
    "streetlight": 18_000,      # per pole
    "hospital": 1_400_000,      # per bed
    "community_hall": 16_000,   # per sqm
    "school_wall": 2_400,       # per sqm
}

# Land, labour, utility shifting and traffic-window working all cost more in
# a metro than in a village.
AREA_COST_MULTIPLIER = {
    "metro": 1.55,
    "urban": 1.25,
    "semi_urban": 1.05,
    "rural": 1.00,
}

# Haulage and access, not construction technique.
TERRAIN_COST_MULTIPLIER = {
    "plain": 1.00,
    "coastal": 1.12,
    "hilly": 1.35,
}

# Lognormal sigma applied to every clean work's cost.
#
# Bounded on both sides, and the bound is measured rather than guessed. The
# C1 fence (Q3 + 1.5*IQR) flags 1-4% of clean rows whatever sigma is chosen
# -- that is inherent to a right-skewed distribution. What matters is where
# those rows land afterwards, because C1 is fence-gate then ratio-band:
#
#   sigma   clears fence   -> 10 pts only   -> 20+ pts
#    0.20        1.47%           1.40%          0.08%
#    0.28        2.03%           1.50%          0.53%
#    0.35        2.52%           0.61%          1.91%
#    0.45        3.33%           0.05%          3.28%
#
# A clean work clearing only the fence scores 10, well under ALERT_MIN_SCORE,
# so it gets a scores row and no alert. At 0.35+ clean rows start passing 2x
# the median too and earn alert-grade points. Below 0.25 costs look
# implausibly uniform. 0.28 sits in the usable window.
COST_NOISE_SIGMA = 0.28


# ---------------------------------------------------------------------------
# Volume
# ---------------------------------------------------------------------------

# One seed for the whole run. Determinism is a hard requirement: the recall
# number on the slide has to match what the app shows tomorrow.
RANDOM_SEED = 20260915

# CLAUDE.md requires 4000-5000 works. Three dimensions plus district makes
# peer-ladder rung 1 small, so the dataset has to be large enough that most
# comparisons land on rung 3 (work_type + terrain + area_type).
TARGET_WORK_COUNT = 4_500

# Financial years the dataset spans. Straddles SINGLE_INSTALMENT_FROM so both
# release models are exercised.
FISCAL_YEARS = ("2022-23", "2023-24", "2024-25", "2025-26")

# Works with progress_pct = 0 and no progress_updates rows, so step 03's
# graceful-degradation path is exercised by the data rather than by
# intention. These must record a skip, never silently score zero.
SPARSE_DATA_WORK_COUNT = 120


# ---------------------------------------------------------------------------
# Planted anomalies
# ---------------------------------------------------------------------------

# Ground truth for evaluate.py, written into works.planted_anomaly.
# ~290 planted out of ~4500; everything else must be clean.
#
# duplicate_pair counts WORKS, not pairs: 40 works = 20 pairs.
# quota_shortfall is MP-level and writes no work-level label at all.
PLANTED_ANOMALY_COUNTS = {
    "cost_overrun": 60,
    "long_delay": 80,
    "impossible_date": 20,
    "ineligible_work": 20,
    "duplicate_pair": 40,
    "payment_ahead_of_work": 40,
    "ghost_asset": 30,
}

QUOTA_SHORTFALL_MP_COUNT = 4

# cost_overrun works are planted at this multiple of the config baseline,
# which approximates the peer median. Comfortably past C1's 4x top band.
COST_OVERRUN_MULTIPLE_RANGE = (3.0, 6.0)

# long_delay works are sanctioned this many days before REFERENCE_DATE and
# left unfinished. Spans C2's 365-539 and 540+ bands.
LONG_DELAY_DAYS_RANGE = (400, 700)

# payment_ahead_of_work: money far ahead of the build.
PAYMENT_AHEAD_RATIO_RANGE = (0.75, 0.95)
PAYMENT_AHEAD_PROGRESS_RANGE = (0.10, 0.30)


# ---------------------------------------------------------------------------
# Clean-row guard rails
# ---------------------------------------------------------------------------

# Everything below exists to stop the generator manufacturing false
# positives. If clean rows trip checks the false-positive rate is real, and
# the honest response is to loosen thresholds rather than hide it.

# C2 awards from 180 days. Clean unfinished works stay inside that window, so
# no clean row can earn delay points at all.
CLEAN_MAX_DAYS_SINCE_SANCTION = 150

# C7 fires when the payment ratio leads the progress ratio by more than 0.20.
CLEAN_MAX_PAYMENT_PROGRESS_GAP = 0.12

# C5 pairs works in the same district and work_type whose unit costs are
# within 10% and whose sanction dates are within 60 days.
#
# At 4500 works over ~50 districts and 8 work types this collides by chance
# roughly 455 times -- 23x the 20 planted pairs -- which would swamp the
# signal entirely. Widening the cost spread is not enough (log-sd 0.55 still
# leaves ~278). So clean works are actively de-collided after generation:
# any clean pair inside both bands has one work's cost nudged outside the
# band by this margin, before anomalies are planted.
C5_DECOLLIDE_MARGIN = 0.18

# The de-collision sweep repeats until no collision remains, because moving
# one cost out of a band can drop it into another work's band. A single pass
# only got 455 down to 116. Each sweep strictly reduces collisions so the
# loop terminates on its own; this bound is a safety net, not the exit.
C5_DECOLLIDE_MAX_SWEEPS = 12
