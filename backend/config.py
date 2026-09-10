"""Every threshold, point cap and tunable constant in the risk engine.

Nothing here is computed at import time except the database path. Step 03
must be able to retune any detection threshold by editing this file alone,
without touching checks.py.
"""

import os
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
C3_MP_MAX_POINTS = 48   # quota compliance         (mp)
C4_MAX_POINTS = 15      # utilisation              (district)
C8_MAX_POINTS = 30      # vendor pricing conduct   (vendor)

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

# Breaching a floor is scored in two parts: a flat award for being under it
# at all, plus a component scaled by how far short the spend falls.
#
# The flat part is what makes the check useful. With a purely proportional
# award, an MP at a 5.5% SC share -- barely a third of the statutory floor --
# scored 15 * (0.15-0.055)/0.15 = 9, and the only way to reach the alert
# threshold was to miss BOTH floors almost entirely. A single unambiguous
# breach of a statutory floor could not reach an officer, which made the
# check decorative: the four MPs the generator plants under the SC floor were
# all detected and none of them alerted.
#
# A missed floor is a compliance fact that stands on its own, so it carries
# the flat award on its own. The scaled part still separates a near miss from
# spending nothing at all.
# Sized so that breaching one floor by a clear margin reaches
# ALERT_MIN_SCORE on its own: at a third of the SC floor the scaled part
# contributes about two thirds of its range, so 14 + 15*0.66 = 24-25. A
# member sitting just under a floor still scores below the threshold, which
# is the intended behaviour -- a near miss is a note for the next sanction
# round, not a case to open.
SC_SHORTFALL_BASE_POINTS = 14
SC_SHORTFALL_SCALED_POINTS = 15
ST_SHORTFALL_BASE_POINTS = 9
ST_SHORTFALL_SCALED_POINTS = 10


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
# C8 - vendor pricing and conduct
# ---------------------------------------------------------------------------

# Scored against the vendor, not their works. A contractor whose prices sit
# consistently above their peers is a procurement question; charging it to
# each individual work would flag every job that vendor ever won.
#
# Every threshold below sits ABOVE the spread measured on clean generated
# data, so the component identifies an outlier rather than the middle of the
# distribution:
#
#   price ratio (vendor median / work_type median)  clean p95 1.48, p99 1.59
#   concentration (share of a district+work_type)   clean p95 0.42, p99 0.50
#
# At these values the price component fires on 2 of 290 clean vendor+type
# pairs (0.7%) and concentration on 6 of 1478 eligible buckets (0.4%).

# A vendor needs this many works of a type before their median means
# anything -- a median of two is not a price.
C8_MIN_WORKS_FOR_PRICE = 4
C8_PRICE_RATIO_THRESHOLD = 1.60
# The heaviest component, and deliberately so: a contractor whose median
# price sits 1.6x above their peers across several jobs is the clearest
# procurement signal here. Weighted so that price plus one corroborating
# component clears ALERT_MIN_SCORE -- at 14 the strongest realistic pairing
# (overpriced, and works already flagged) summed to 24 and stayed silent one
# point below the threshold.
C8_PRICE_POINTS = 16

# Share of one district's works of one type. The floor matters more than the
# share: without it a two-work bucket reads 100% concentration on noise.
C8_MIN_WORKS_FOR_CONCENTRATION = 6
C8_CONCENTRATION_THRESHOLD = 0.60
# Nine, matching C8_PAYMENT_SHARE_POINTS and for the same reason: every
# corroborating component was sized so that price plus one summed to exactly
# 24, one point under ALERT_MIN_SCORE. A vendor priced 2.6x their peers who
# also holds 64% of a district's works of one type is the pairing this check
# is for, and it was being lost to rounding rather than to judgement.
C8_CONCENTRATION_POINTS = 9

# A vendor whose works keep turning up on the worklist. Reuses the scores
# already computed rather than re-deriving anything.
C8_MIN_WORKS_FOR_FLAG_RATE = 4
C8_FLAGGED_SHARE_THRESHOLD = 0.40
C8_FLAGGED_SHARE_POINTS = 10

# Share of a district's total payments reaching one vendor.
#
# Nine rather than eight for the same reason C8_PRICE_POINTS went from 14 to
# 16: price (16) plus this component summed to exactly 24 and stayed silent
# one point below ALERT_MIN_SCORE. A vendor priced 2.1x their peers across 24
# jobs who also draws 54% of a district's payments is precisely the pairing
# this check exists to surface, and it was being lost to rounding.
#
# Still sub-threshold on its own (9 < 25), so holding a large share of a
# small district's payments remains a note rather than a case -- which is the
# stated intent: no single C8 component may reach the threshold alone.
C8_MIN_DISTRICT_PAYMENT = 10_000_000   # ignore trivially small districts
C8_PAYMENT_SHARE_THRESHOLD = 0.45
C8_PAYMENT_SHARE_POINTS = 9


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

# Works carrying MORE THAN ONE problem at once, so the critical band is
# reachable at all.
#
# Every check caps well below 70: the largest single award is 35 (C1, C7).
# With one anomaly per work the ceiling is about 50, so SEVERITY_BANDS'
# critical rung -- and the --sev-critical tokens that style it -- were dead
# code against real data. A subject only earns 70 by being wrong in several
# independent ways at once, which is also the honest reading of "critical":
# not one severe number, but a work that fails several unrelated tests.
#
# The point columns are independent (C1, C3, C5, C6, C7 all run and write to
# different columns; only C2/C2b are mutually exclusive), so these sum for
# real rather than by coincidence.
#
# Kept deliberately small. Twelve of ~4500 works is about 0.3% -- enough that
# the band is populated and the worklist opens on a genuine one, few enough
# that it stays plausible. Each component is itself a real planted anomaly,
# so these are true positives: they must not move the false-positive rate.
PLANTED_STACKED_CRITICAL = 12

# The primary label goes in works.planted_anomaly; the rest are recorded in
# audit_log, exactly as MP and vendor ground truth already are. Ordered
# primary-first, the primary being whichever check awards the most.
# long_delay is deliberately NOT paired with ghost_asset: ghost_asset marks
# the work completed, and C2 exempts completed works (checks.py), so the
# delay label could never be earned. Labelling ground truth with a problem no
# check can find would depress that label's recall for a reason that has
# nothing to do with detection.
STACKED_CRITICAL_COMBINATIONS = (
    ("cost_overrun", "ghost_asset"),            # C1 35 + C7 ~27 + C6
    ("cost_overrun", "payment_ahead_of_work"),  # C1 35 + C7 ~25 + C6
    ("long_delay", "payment_ahead_of_work"),    # C2 25 + C7 ~25 + C6
)

# Verified citizen reports attached to each stacked work. C6 bands at
# 1 -> 5, 2-3 -> 10, 4+ -> 15, and two of the three combinations need that
# top band to clear 70. Planted as verified = 1 rather than left to the
# 65% coin flip the ordinary complaint pass uses: a critical count that
# moved with the random draw would not be reproducible.
STACKED_CRITICAL_COMPLAINTS = 4

# C1 is fence-first: a work must clear Q3 + 1.5*IQR before any ratio band
# applies, so in a tightly clustered peer group even a 3-6x multiple can
# score zero. That is correct behaviour and must not be weakened -- but a
# work planted to demonstrate the critical band should not depend on the
# spread of whichever peer group it happened to land in. Planting at the top
# of the range clears the fence in every peer group observed.
STACKED_COST_MULTIPLE_RANGE = (5.0, 6.0)

# Likewise pinned to C2's top band (540+ days) rather than the wider range
# the standalone long_delay label uses, so the delay component is a reliable
# 25 rather than sometimes 18.
STACKED_DELAY_DAYS_RANGE = (560, 700)

# Comfortably past C7_STALE_DAYS (180), so a fully paid record that has not
# been touched contributes its stale component too.
STACKED_STALE_DAYS = 220

# The districts the demo signs into, in order. One stacked work is pinned to
# each so the opening worklist actually has a critical row on it -- left to
# the shuffle these scatter one per district across the country and do.pune
# opens on a medium.
DEMO_DISTRICTS = ("Pune", "Nashik")

# The state whose officer the demo signs in as. One planted quota shortfall
# is pinned here so that worklist actually holds the MP-level rows the beat
# is meant to show.
DEMO_STATE_CODE = "MH"

# Share of works flagged as falling in a Scheduled Caste or Scheduled Tribe
# area. The statutory floors are measured on SPEND, not on the number of
# works, so these must sit clear of SC_AREA_FLOOR and ST_AREA_FLOOR with
# room to spare: works vary in cost, so a flag rate merely equal to the
# floor leaves half the members under it by ordinary sampling noise.
#
# At 0.22 / 0.11 -- barely above the 0.15 / 0.075 floors -- 46 of 73 members
# breached the SC floor and 51 breached ST, so a compliance check meant to
# distinguish four planted members flagged most of the house.
#
# The margin has to cover the drag from utilisation as well. A flag rate
# converts to a share of SPEND, while the floors are measured against funds
# RELEASED, and median utilisation is about two thirds -- so a flag rate of
# f lands near 0.66*f against the floor. These are set so that even the
# lower tail of that distribution clears the floor, leaving the members the
# generator deliberately pushes under it as the ones the check finds.
SC_AREA_WORK_SHARE = 0.50
ST_AREA_WORK_SHARE = 0.26

# Some works must be generated with progress_pct = 0 and no
# progress_updates rows, so the graceful-degradation path is exercised by
# the data rather than only by intention.
WORKS_WITHOUT_PROGRESS_DATA = 400


# --- The cost model -------------------------------------------------------
#
# Baselines live here, not inside the generator, because evaluate.py needs to
# know what "normal" was in order to plant a work at 4x normal.
#
# checks.py must NEVER read these three tables. Detection compares a work
# against its actual peers in the data; scoring against the baseline we
# generated from would be marking our own homework, and the recall number
# would mean nothing.

# Rupees per unit of `quantity`, before the multipliers below. Units follow
# WORK_TYPE_UNITS: km, count, beds or sqm.
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

# Lognormal sigma applied to every clean work's cost. Bounded on both sides,
# and the bound was measured rather than guessed. The C1 fence (Q3 + 1.5*IQR)
# flags 1-4% of clean rows whatever sigma is chosen -- that is inherent to a
# right-skewed distribution. What matters is where those rows land after,
# because C1 is fence-gate then ratio-band:
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

# Financial years the dataset spans. Straddles SINGLE_INSTALMENT_FROM so both
# release models are exercised.
FISCAL_YEARS = ("2022-23", "2023-24", "2024-25", "2025-26")


# --- The cost index -------------------------------------------------------
#
# Construction costs rise year on year. Without this the dataset is flat in
# nominal terms, which is not what any real cost series looks like, and it
# hides a real detection problem: C1's peer ladder has no year dimension, so
# a 2024-25 work is compared against 2022-23 peers at face value and looks
# expensive purely for being recent.
#
# READ BY BOTH generate_data.py (to inflate) AND checks.py (to deflate back
# to constant prices before comparing peers).
#
# That dual use is a deliberate, narrow exception to the rule that checks.py
# must not read the generator's cost tables, and the distinction is real:
#
#   BASE_UNIT_COST is OUR INVENTED ANSWER. Scoring against it would be
#   marking our own homework -- the recall number would measure how well we
#   reproduced our own baseline.
#
#   COST_INDEX is a PUBLISHED ECONOMIC FACT. A real deployment would take
#   these figures from the WPI construction series rather than from us. An
#   officer deflating two years to constant prices before comparing them is
#   doing ordinary analysis, not consulting the answer key.
#
# Base year 2022-23 = 1.00; the index is what a work's money is worth
# relative to that year.
ANNUAL_COST_ESCALATION = 0.06
COST_INDEX_BASE_FY = "2022-23"
COST_INDEX = {
    "2022-23": 1.0000,
    "2023-24": 1.0600,
    "2024-25": 1.1236,
    "2025-26": 1.1910,
}


# --- Vendor overpricing ---------------------------------------------------

# Vendors whose works are priced well above their peers. Labelled on the
# VENDOR, never on each work: marking every work would credit C1 with
# catching something C8 is meant to catch, and inflate C1's recall.
#
# Clean vendor price ratios reach 1.80 at the very top, so a planted vendor
# has to sit clearly above that to be separable at all.
PLANTED_VENDOR_OVERPRICING = 6
VENDOR_OVERPRICING_MULTIPLE_RANGE = (2.0, 2.6)


# --- How each anomaly is planted ------------------------------------------

# cost_overrun works are planted at this multiple of the config baseline,
# which approximates the peer median. Comfortably past C1's 4x top band.
COST_OVERRUN_MULTIPLE_RANGE = (3.0, 6.0)

# long_delay works are sanctioned this many days before REFERENCE_DATE and
# left unfinished. Spans C2's 365-539 and 540+ bands.
LONG_DELAY_DAYS_RANGE = (400, 700)

# payment_ahead_of_work: money far ahead of the build.
PAYMENT_AHEAD_RATIO_RANGE = (0.75, 0.95)
PAYMENT_AHEAD_PROGRESS_RANGE = (0.10, 0.30)


# --- Clean-row guard rails ------------------------------------------------
#
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
# leaves ~278). So clean works are actively de-collided after generation.
C5_DECOLLIDE_MARGIN = 0.18

# The sweep repeats until no collision remains, because moving one cost out
# of a band can drop it into another work's band. Fixing pairs one at a time
# also oscillates -- the same collisions re-fixed on every sweep, forever --
# so the sweep clears a work against its whole neighbourhood at once, and
# downward, since pushing costs up trips C1's fence instead. This bound is a
# safety net, not the exit.
C5_DECOLLIDE_MAX_SWEEPS = 12


# ---------------------------------------------------------------------------
# Authentication (step 05)
# ---------------------------------------------------------------------------

JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 12

# Read from the environment at runtime and never stored here or committed.
# PyJWT warns below 32 bytes for HS256.
JWT_SECRET_ENV_VAR = "JWT_SECRET"
JWT_MIN_SECRET_BYTES = 32

# Project root -- the directory above backend/.
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def load_env_file(path: Path = ENV_FILE) -> None:
    """Load KEY=value lines from .env into the environment, if it exists.

    An exported shell variable lives only in the shell that ran the export,
    so every new terminal loses JWT_SECRET and the app refuses to start. That
    is a real trip hazard mid-demo, when the shell being used is rarely the
    one the secret was generated in.

    A real environment variable always wins, so CI and a deployment override
    the file rather than fight it. The file is gitignored: the secret must
    never be committed. Written by hand rather than pulling in python-dotenv,
    which would be a dependency for fifteen lines.
    """
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        # Never clobber a variable the caller set deliberately.
        os.environ.setdefault(key, value)


load_env_file()

# ---------------------------------------------------------------------------
# CORS origins
# ---------------------------------------------------------------------------

# The Vite dev server, always allowed so a fresh clone runs with no config.
DEV_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
)

# A deployment adds its own frontend origin here, comma-separated:
#   CORS_ORIGINS=https://kavach-web.onrender.com
# Kept in the environment rather than the source so the backend does not need
# a code change (and a redeploy) when the frontend URL changes.
CORS_ORIGINS_ENV_VAR = "CORS_ORIGINS"


def cors_allow_origins() -> list[str]:
    """Dev origins plus any set in CORS_ORIGINS, de-duplicated in order.

    A trailing slash is stripped: browsers send the Origin header without one,
    so "https://site.com/" in the variable would silently never match and the
    failure would look like a CORS bug rather than a typo.
    """
    origins = list(DEV_ORIGINS)
    for raw in os.environ.get(CORS_ORIGINS_ENV_VAR, "").split(","):
        origin = raw.strip().rstrip("/")
        if origin and origin not in origins:
            origins.append(origin)
    return origins


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
    # A vendor operates in exactly one district, so their pricing conduct is
    # the District Officer's to review -- they are the ones who tender to
    # them. Unlike the MP and district rows above, this is not an alert about
    # the recipient themselves, so there is no conflict in routing it locally.
    "vendor": "district_officer",
}