"""Builds mplads.db: reference data, ~4500 works, and ~290 planted anomalies.

Run `python -m backend.generate_data`. Drops and recreates every table, so it
is always safe to re-run.

Two properties matter more than realism here.

**Determinism.** Two runs must produce byte-identical data, or the recall
number on the slide stops matching the app tomorrow. Everything random comes
from one seeded Random instance threaded through every function; nothing
reads the global `random` module, and no collection is iterated in
set/dict-insertion order where that order could vary.

**Clean rows must stay clean.** ~290 works carry a planted_anomaly label and
everything else must pass every check in step 03. A clean row that trips a
check is a real false positive, and the honest response is to loosen the
threshold rather than hide it -- so the generator actively avoids
manufacturing them. The guard rails are in config.py under "Clean-row guard
rails"; the subtle one is the C5 de-collision pass in _decollide_duplicates.
"""

from __future__ import annotations

import hashlib
import random
from datetime import date, timedelta

from faker import Faker
from werkzeug.security import generate_password_hash

from backend import config
from backend.db import get_session, init_db
from backend.models import (
    Agency,
    Allocation,
    AuditLog,
    Complaint,
    Constituency,
    District,
    Evidence,
    MP,
    Payment,
    ProgressUpdate,
    State,
    User,
    Vendor,
    Work,
)

# Every demo account uses this. Prototype only -- real accounts would be
# provisioned by the Ministry.
DEMO_PASSWORD = "mplads2026"


# ---------------------------------------------------------------------------
# Geography
# ---------------------------------------------------------------------------

# Real state and district names, copied from the public eSAKSHI dashboard to
# make the dataset credible. CLAUDE.md permits this; the MP and vendor names
# attached to them are generated.
#
# Tuples, not sets or dicts: iteration order is part of determinism.
GEOGRAPHY = (
    ("Maharashtra", "MH", (
        ("Pune", 0, "metro"),
        ("Mumbai Suburban", 0, "metro"),
        ("Nashik", 0, "urban"),
        ("Nagpur", 0, "urban"),
        ("Satara", 1, "rural"),
        ("Ratnagiri", 0, "rural"),
        ("Solapur", 0, "semi_urban"),
        ("Ahmednagar", 0, "rural"),
    )),
    ("Karnataka", "KA", (
        ("Bengaluru Urban", 0, "metro"),
        ("Mysuru", 0, "urban"),
        ("Belagavi", 0, "semi_urban"),
        ("Kodagu", 1, "rural"),
        ("Dakshina Kannada", 0, "urban"),
        ("Kalaburagi", 0, "rural"),
    )),
    ("Tamil Nadu", "TN", (
        ("Chennai", 0, "metro"),
        ("Coimbatore", 0, "urban"),
        ("Madurai", 0, "urban"),
        ("Nilgiris", 1, "rural"),
        ("Thanjavur", 0, "semi_urban"),
        ("Kanyakumari", 0, "rural"),
    )),
    ("Uttar Pradesh", "UP", (
        ("Lucknow", 0, "metro"),
        ("Varanasi", 0, "urban"),
        ("Gorakhpur", 0, "semi_urban"),
        ("Jhansi", 0, "rural"),
        ("Bareilly", 0, "semi_urban"),
        ("Sonbhadra", 1, "rural"),
    )),
    ("Kerala", "KL", (
        ("Thiruvananthapuram", 0, "urban"),
        ("Ernakulam", 0, "metro"),
        ("Idukki", 1, "rural"),
        ("Kozhikode", 0, "urban"),
        ("Alappuzha", 0, "semi_urban"),
    )),
    ("Himachal Pradesh", "HP", (
        ("Shimla", 1, "urban"),
        ("Kangra", 1, "rural"),
        ("Mandi", 1, "rural"),
        ("Kullu", 1, "rural"),
    )),
    ("Gujarat", "GJ", (
        ("Ahmedabad", 0, "metro"),
        ("Surat", 0, "urban"),
        ("Rajkot", 0, "semi_urban"),
        ("Kutch", 0, "rural"),
        ("Valsad", 0, "rural"),
    )),
    ("West Bengal", "WB", (
        ("Kolkata", 0, "metro"),
        ("Darjeeling", 1, "rural"),
        ("Howrah", 0, "urban"),
        ("Purba Medinipur", 0, "rural"),
        ("Bardhaman", 0, "semi_urban"),
    )),
    ("Assam", "AS", (
        ("Kamrup Metropolitan", 0, "urban"),
        ("Dibrugarh", 0, "semi_urban"),
        ("Karbi Anglong", 1, "rural"),
        ("Cachar", 0, "rural"),
    )),
    ("Rajasthan", "RJ", (
        ("Jaipur", 0, "metro"),
        ("Jodhpur", 0, "urban"),
        ("Udaipur", 0, "semi_urban"),
        ("Barmer", 0, "rural"),
    )),
)

# Districts whose terrain skews coastal. Terrain lives on the work, not the
# district -- this only weights the draw.
COASTAL_DISTRICTS = frozenset({
    "Mumbai Suburban", "Ratnagiri", "Dakshina Kannada", "Chennai",
    "Kanyakumari", "Ernakulam", "Alappuzha", "Kozhikode", "Surat",
    "Valsad", "Kutch", "Kolkata", "Purba Medinipur", "Thiruvananthapuram",
})

AGENCY_TYPES = ("pwd", "zilla_parishad", "municipal", "other")

# Quantity ranges per work_type, in that type's unit.
#
# Sized so a work costs what an MPLADS work actually costs -- lakhs, not
# crores. The scheme releases Rs 5 crore per MP per year and a member
# recommends of the order of 25 works against it, so the average work has to
# land near Rs 20 lakh for the arithmetic to be possible at all.
#
# These were too large by roughly an order of magnitude: a 6 km road at
# Rs 45 lakh/km came to Rs 2.7 crore, over half of one member's annual
# entitlement on a single work, and a 31-bed hospital came to Rs 4.3 crore.
# Total spend per MP-FY reached Rs 44 crore against a Rs 5 crore release --
# 8.8x the statutory ceiling. Every allocation then clamped to spent ==
# released, which made district utilisation exactly 1.0 everywhere and left
# C4 unable to fire on any district in the country.
QUANTITY_RANGES = {
    "road": (0.08, 0.9),          # km
    "drain": (0.06, 0.5),         # km
    "bridge": (0.008, 0.05),      # km
    "borewell": (1, 4),           # count
    "streetlight": (10, 60),      # count
    "hospital": (1, 5),           # beds
    "community_hall": (40, 180),  # sqm
    "school_wall": (80, 450),     # sqm
}

# Sampling weights. Rural and plain dominate, as they do in the scheme, but
# nothing is so rare that its rung-3 peer group falls under
# PEER_GROUP_MIN_ROWS and pushes C1 down the ladder for every work in it.
WORK_TYPE_WEIGHTS = (
    ("road", 26), ("drain", 14), ("borewell", 16), ("streetlight", 15),
    ("community_hall", 10), ("school_wall", 11), ("hospital", 4),
    ("bridge", 4),
)

DESCRIPTION_TEMPLATES = {
    "road": ("Construction of CC road at {place}",
             "Widening and strengthening of approach road, {place}",
             "Bituminous surfacing of village road near {place}"),
    "drain": ("Construction of RCC storm water drain, {place}",
              "Covered drainage work at {place}"),
    "bridge": ("Construction of minor bridge across nala at {place}",
               "Culvert and causeway work near {place}"),
    "borewell": ("Sinking of borewell with hand pump at {place}",
                 "Drinking water borewell and platform, {place}"),
    "streetlight": ("Installation of LED street lights at {place}",
                    "Solar street lighting for {place} village"),
    "hospital": ("Additional beds and ward at PHC {place}",
                 "Upgradation of ward block, CHC {place}"),
    "community_hall": ("Construction of community hall at {place}",
                       "Multipurpose community centre, {place}"),
    "school_wall": ("Compound wall for Zilla Parishad school, {place}",
                    "Boundary wall and gate at school, {place}"),
}


def _weighted_choice(rng: random.Random, weighted: tuple) -> str:
    """Pick from ((value, weight), ...). Kept explicit so the draw is seeded."""
    total = sum(weight for _, weight in weighted)
    roll = rng.uniform(0, total)
    upto = 0.0
    for value, weight in weighted:
        upto += weight
        if roll <= upto:
            return value
    return weighted[-1][0]


def _iso(value: date) -> str:
    """Dates are ISO-8601 strings everywhere. SQLite has no date type."""
    return value.isoformat()


def _fy_window(fy: str) -> tuple[date, date]:
    """Indian financial year "2024-25" -> 1 Apr 2024 .. 31 Mar 2025."""
    start_year = int(fy[:4])
    return date(start_year, 4, 1), date(start_year + 1, 3, 31)


# ---------------------------------------------------------------------------
# Phase 2 -- reference data
# ---------------------------------------------------------------------------


def build_geography(session, rng, fake):
    """states -> districts -> constituencies -> mps. Returns the built rows.

    Flushes as it goes so foreign keys resolve: a district needs its state's
    autoincrement id before it can reference it.
    """
    states, districts, constituencies, mps = [], [], [], []

    for state_name, code, district_specs in GEOGRAPHY:
        state = State(name=state_name, code=code)
        session.add(state)
        session.flush()
        states.append(state)

        state_districts = []
        for district_name, is_hill, default_area in district_specs:
            district = District(
                state_id=state.state_id,
                name=district_name,
                is_hill_district=is_hill,
                default_area_type=default_area,
            )
            session.add(district)
            state_districts.append(district)
        session.flush()
        districts.extend(state_districts)

        # One Lok Sabha constituency per district keeps the mapping legible,
        # plus two Rajya Sabha seats per state. A Rajya Sabha member has no
        # constituency in the ordinary sense, so those rows use the state
        # name.
        for district in state_districts:
            constituency = Constituency(
                state_id=state.state_id,
                name=district.name,
                house="lok_sabha",
            )
            session.add(constituency)
            constituencies.append(constituency)

        for seat in (1, 2):
            constituency = Constituency(
                state_id=state.state_id,
                name=f"{state_name} RS-{seat}",
                house="rajya_sabha",
            )
            session.add(constituency)
            constituencies.append(constituency)
        session.flush()

    # One MP per constituency. term_start/term_end are not decoration: C3
    # flags a work recommended outside its MP's term.
    for constituency in constituencies:
        if constituency.house == "lok_sabha":
            term_start, term_end = date(2019, 5, 30), date(2029, 5, 29)
        else:
            term_start, term_end = date(2020, 4, 3), date(2032, 4, 2)

        mp = MP(
            full_name=fake.name(),
            house=constituency.house,
            constituency_id=constituency.constituency_id,
            state_id=constituency.state_id,
            term_start=_iso(term_start),
            term_end=_iso(term_end),
            is_active=1,
        )
        session.add(mp)
        mps.append(mp)
    session.flush()

    return states, districts, constituencies, mps


def build_agencies_and_vendors(session, rng, fake, districts):
    """Implementing agencies and private contractors, per district.

    An agency tenders, a vendor executes -- distinct entities, distinct
    tables.
    """
    agencies, vendors = [], []

    for district in districts:
        for agency_type in AGENCY_TYPES[:3]:
            label = {
                "pwd": "Public Works Division",
                "zilla_parishad": "Zilla Parishad",
                "municipal": "Municipal Corporation",
            }[agency_type]
            agency = Agency(
                name=f"{label}, {district.name}",
                agency_type=agency_type,
                district_id=district.district_id,
            )
            session.add(agency)
            agencies.append(agency)

        for _ in range(rng.randint(4, 7)):
            name = f"{fake.last_name()} {rng.choice(('Constructions', 'Infra Works', 'Enterprises', 'Builders', 'Contractors'))}"
            # A hash, never a realistic PAN. This is generated data and must
            # not resemble a genuine identity document.
            pan_hash = hashlib.sha256(
                f"{name}|{district.name}|{rng.random()}".encode()
            ).hexdigest()[:32]
            vendor = Vendor(
                name=name,
                district_id=district.district_id,
                pan_hash=pan_hash,
                address=f"{fake.street_address()}, {district.name}",
                registered_on=_iso(date(2015, 1, 1) + timedelta(days=rng.randint(0, 2800))),
                is_active=1,
            )
            session.add(vendor)
            vendors.append(vendor)

    session.flush()
    return agencies, vendors


# ---------------------------------------------------------------------------
# Phase 3 -- users
# ---------------------------------------------------------------------------


def build_users(session, rng, fake, states, districts, constituencies, mps):
    """Demo logins. Roles are provisioned here and nowhere else.

    There is no signup form offering "district officer" and no endpoint
    anywhere writes users.role. In production officer accounts would come
    from the Ministry and citizens from Aadhaar-verified registration.

    role decides which actions are allowed; scope_type + scope_id decide
    which rows are visible. The two are deliberately separate.
    """
    users = []
    created = _iso(config.REFERENCE_DATE - timedelta(days=400))
    password_hash = generate_password_hash(DEMO_PASSWORD)

    def add(username, full_name, role, scope_type, scope_id, mp_id=None):
        user = User(
            username=username,
            password_hash=password_hash,
            full_name=full_name,
            role=role,
            scope_type=scope_type,
            scope_id=scope_id,
            mp_id=mp_id,
            is_active=1,
            created_at=created,
            last_login_at=None,
        )
        session.add(user)
        users.append(user)
        return user

    by_name = {d.name: d for d in districts}

    # The demo script depends on these two: log in as do.pune, then as
    # do.nashik, and the worklists differ. Pasting Pune's alert URL into
    # Nashik's session must 404 -- not 403, so the response does not confirm
    # that the alert exists. The alert is hidden, not refused.
    add("do.pune", "District Officer, Pune", "district_officer",
        "district", by_name["Pune"].district_id)
    add("do.nashik", "District Officer, Nashik", "district_officer",
        "district", by_name["Nashik"].district_id)

    # A district officer for every remaining district, so no alert is
    # unroutable.
    for district in districts:
        if district.name in ("Pune", "Nashik"):
            continue
        slug = district.name.lower().replace(" ", "")
        add(f"do.{slug}", f"District Officer, {district.name}",
            "district_officer", "district", district.district_id)

    # MP-quota and district-utilisation alerts route to the State Officer,
    # never to the person the alert is about.
    for state in states:
        add(f"so.{state.code.lower()}", f"State Officer, {state.name}",
            "state_officer", "state", state.state_id)

    add("ministry.mospi", "MoSPI Monitoring Cell", "ministry", "national", None)

    # A handful of MP logins. An MP is a person in the scheme (mps); a user
    # is a login. Keep them separate: the slug below is cosmetic, and
    # users.mp_id remains the only link to the person.
    #
    # Named after the seat rather than the member -- mp.pune reads as an
    # account on a projector where mp7 reads as test data, and a seat
    # outlives whoever holds it.
    constituency_names = {c.constituency_id: c.name for c in constituencies}
    taken = set()
    for mp in mps[:6]:
        seat = constituency_names[mp.constituency_id].lower()
        seat = seat.replace(" ", "").replace("-", "")
        slug = f"mp.{seat}"
        # Seat names are unique per state, not nationally; fall back to the
        # id rather than silently colliding on a UNIQUE column.
        if slug in taken:
            slug = f"mp.{seat}{mp.mp_id}"
        taken.add(slug)
        add(slug, mp.full_name, "mp", "constituency", mp.constituency_id,
            mp_id=mp.mp_id)

    # Citizens file complaints; C6 counts distinct verified reporters, and
    # UNIQUE(work_id, user_id) stops one person inflating a score.
    for index in range(60):
        add(f"citizen{index + 1:03d}", fake.name(), "citizen",
            "constituency", rng.choice(constituencies).constituency_id)

    session.flush()
    return users


# ---------------------------------------------------------------------------
# Phase 4 -- allocations
# ---------------------------------------------------------------------------


def build_allocations(session, rng, mps):
    """One row per MP per financial year. UNIQUE(mp_id, fy).

    `spent` is a placeholder here and is rewritten from the actual works in
    reconcile_allocations() once works exist. No SC/ST columns: those are
    derived by summing works, and storing them twice guarantees they
    disagree.
    """
    allocations = []
    for mp in mps:
        for fy in config.FISCAL_YEARS:
            fy_start, _ = _fy_window(fy)
            # Since 1 April 2023 the entitlement is released as a single
            # annual instalment rather than two of Rs 2.5 crore. The dataset
            # straddles the change, so both models appear.
            if fy_start >= config.SINGLE_INSTALMENT_FROM:
                released = config.ANNUAL_ENTITLEMENT
                released_on = fy_start + timedelta(days=rng.randint(5, 45))
            else:
                released = config.ANNUAL_ENTITLEMENT // 2 * 2
                released_on = fy_start + timedelta(days=rng.randint(5, 30))

            # A future financial year has an entitlement but no release yet.
            if fy_start > config.REFERENCE_DATE:
                released, released_on = 0, None

            allocations.append(Allocation(
                mp_id=mp.mp_id,
                fy=fy,
                entitlement=config.ANNUAL_ENTITLEMENT,
                released=released,
                spent=0,
                released_on=_iso(released_on) if released_on else None,
            ))
    session.add_all(allocations)
    session.flush()
    return allocations


# ---------------------------------------------------------------------------
# Phase 5 -- works
# ---------------------------------------------------------------------------


def _pick_terrain(rng, district):
    """Terrain is a property of the work, not the district.

    districts.is_hill_district only weights the draw -- it is a generation
    hint and nothing in checks.py may read it. A flat road in a hill
    district must not inherit "hilly" and be excused as expensive-by-terrain.
    """
    if district.is_hill_district:
        return _weighted_choice(rng, (("hilly", 78), ("plain", 22)))
    if district.name in COASTAL_DISTRICTS:
        return _weighted_choice(rng, (("coastal", 62), ("plain", 38)))
    return _weighted_choice(rng, (("plain", 88), ("hilly", 7), ("coastal", 5)))


def _pick_area_type(rng, district):
    """Seeded from the district default, then varied.

    A district like Pune contains both a metro core and rural talukas, so
    the work carries its own area_type.
    """
    default = district.default_area_type
    neighbours = {
        "metro": (("metro", 62), ("urban", 26), ("semi_urban", 12)),
        "urban": (("urban", 58), ("semi_urban", 24), ("metro", 8), ("rural", 10)),
        "semi_urban": (("semi_urban", 56), ("rural", 28), ("urban", 16)),
        "rural": (("rural", 74), ("semi_urban", 22), ("urban", 4)),
    }[default]
    return _weighted_choice(rng, neighbours)


def _unit_cost(rng, work_type, terrain, area_type, fy, sigma=None):
    """Baseline cost per unit, escalated to `fy`, with lognormal noise.

    The baseline tables live in config.py, never inline here -- evaluate.py
    needs to know what "normal" was in order to plant a work at 4x normal.
    checks.py must never read them: detection compares a work against its
    actual peers, not against a constant we chose.

    The COST_INDEX multiplier is applied here rather than later so that every
    downstream consumer -- planted anomalies and the C5 de-collision sweep
    included -- works in the same escalated money. De-colliding pre-inflation
    costs and then inflating them would reintroduce the collisions the sweep
    had just removed.
    """
    base = (
        config.BASE_UNIT_COST[work_type]
        * config.AREA_COST_MULTIPLIER[area_type]
        * config.TERRAIN_COST_MULTIPLIER[terrain]
        * config.COST_INDEX[fy]
    )
    noise = rng.lognormvariate(0, config.COST_NOISE_SIGMA if sigma is None else sigma)
    return base * noise


def _lifecycle(rng, recommended_on, work_type, area_type):
    """Decide status and every date that follows from it.

    Returns the tuple of lifecycle fields. The invariants that hold for
    every clean row, each protecting a check it would otherwise trip:

      recommended_on <= sanctioned_on <= completed_on   (C3)
      no date after REFERENCE_DATE                      (C3)
      unfinished works sanctioned < 180 days ago        (C2)

    expected_completion_on is stored rather than derived, so the citizen
    page's "overdue by N days" and the delay check cannot disagree about
    what overdue means.
    """
    ref = config.REFERENCE_DATE
    days_since_recommend = (ref - recommended_on).days

    # Still awaiting sanction.
    if days_since_recommend < 45 or rng.random() < 0.06:
        return "recommended", None, None, None, None, 0.0, recommended_on

    sanction_lag = rng.randint(20, 120)
    sanctioned_on = recommended_on + timedelta(days=sanction_lag)
    if sanctioned_on > ref:
        return "recommended", None, None, None, None, 0.0, recommended_on

    duration = config.EXPECTED_DURATION_DAYS[(work_type, area_type)]
    expected_completion_on = sanctioned_on + timedelta(days=duration)
    days_since_sanction = (ref - sanctioned_on).days

    # Completed: finished on or before the reference date, and -- for a
    # clean row -- not implausibly fast, which C7 would flag.
    completed_early_enough = sanctioned_on + timedelta(
        days=int(duration * rng.uniform(0.55, 1.05))
    )
    if completed_early_enough <= ref and rng.random() < 0.62:
        completed_on = completed_early_enough
        last_updated_on = completed_on + timedelta(days=rng.randint(0, 20))
        return (
            "completed", sanctioned_on, expected_completion_on, completed_on,
            None, 100.0, min(last_updated_on, ref),
        )

    # Unfinished. C2 awards from 180 days since sanction, so a clean row
    # stays inside CLEAN_MAX_DAYS_SINCE_SANCTION. This is the guard rail
    # that keeps clean works off the delay check entirely.
    if days_since_sanction > config.CLEAN_MAX_DAYS_SINCE_SANCTION:
        shift = days_since_sanction - rng.randint(30, config.CLEAN_MAX_DAYS_SINCE_SANCTION)
        sanctioned_on = sanctioned_on + timedelta(days=shift)
        expected_completion_on = sanctioned_on + timedelta(days=duration)
        days_since_sanction = (ref - sanctioned_on).days

    status = "in_progress" if days_since_sanction > 25 else "sanctioned"
    progress = 0.0
    if status == "in_progress":
        # Roughly on track for elapsed time, so C2b's "behind schedule"
        # condition does not fire either.
        expected_fraction = min(0.95, days_since_sanction / duration)
        progress = round(max(3.0, expected_fraction * 100 * rng.uniform(0.85, 1.15)), 1)
        progress = min(progress, 95.0)

    # C2b also needs a stale record; clean rows are updated recently.
    last_updated_on = ref - timedelta(days=rng.randint(1, 55))
    if last_updated_on < sanctioned_on:
        last_updated_on = sanctioned_on

    return (status, sanctioned_on, expected_completion_on, None, None,
            progress, last_updated_on)


def build_works(session, rng, fake, districts, constituencies, mps, agencies,
                vendors):
    """~4500 clean works. Anomalies are planted afterwards, not here.

    Every work gets its own terrain and area_type -- both axes live on the
    work, because Mumbai is coastal and metro while Shimla is hilly and
    urban.
    """
    agencies_by_district = {}
    for agency in agencies:
        agencies_by_district.setdefault(agency.district_id, []).append(agency)
    vendors_by_district = {}
    for vendor in vendors:
        vendors_by_district.setdefault(vendor.district_id, []).append(vendor)

    constituency_by_id = {c.constituency_id: c for c in constituencies}
    lok_sabha_mps = [mp for mp in mps if mp.house == "lok_sabha"]

    # A Lok Sabha MP's works sit in the district of the same name.
    district_by_name = {d.name: d for d in districts}
    mp_district = {}
    for mp in lok_sabha_mps:
        name = constituency_by_id[mp.constituency_id].name
        mp_district[mp.mp_id] = district_by_name[name]

    works = []
    for _ in range(config.TARGET_WORK_COUNT):
        mp = rng.choice(lok_sabha_mps)
        district = mp_district[mp.mp_id]
        work_type = _weighted_choice(rng, WORK_TYPE_WEIGHTS)
        terrain = _pick_terrain(rng, district)
        area_type = _pick_area_type(rng, district)

        low, high = QUANTITY_RANGES[work_type]
        unit = config.WORK_TYPE_UNITS[work_type]
        quantity = (
            float(rng.randint(int(low), int(high)))
            if unit == "count" or work_type == "hospital"
            else round(rng.uniform(low, high), 2)
        )

        fy = rng.choice(config.FISCAL_YEARS[:-1])
        fy_start, fy_end = _fy_window(fy)
        recommended_on = fy_start + timedelta(
            days=rng.randint(0, (min(fy_end, config.REFERENCE_DATE) - fy_start).days)
        )

        (status, sanctioned_on, expected_completion_on, completed_on,
         final_cost, progress_pct, last_updated_on) = _lifecycle(
            rng, recommended_on, work_type, area_type)

        estimated_cost = int(round(
            _unit_cost(rng, work_type, terrain, area_type, fy) * quantity))
        if status == "completed":
            # Small honest variation between estimate and final bill.
            final_cost = int(round(estimated_cost * rng.uniform(0.96, 1.08)))

        place = fake.city()
        description = rng.choice(DESCRIPTION_TEMPLATES[work_type]).format(place=place)

        district_agencies = agencies_by_district[district.district_id]
        district_vendors = vendors_by_district[district.district_id]

        work = Work(
            mp_id=mp.mp_id,
            constituency_id=mp.constituency_id,
            district_id=district.district_id,
            agency_id=(rng.choice(district_agencies).agency_id
                       if status != "recommended" else None),
            vendor_id=(rng.choice(district_vendors).vendor_id
                       if status in ("in_progress", "completed") else None),
            fy=fy,
            work_type=work_type,
            description=description,
            terrain=terrain,
            area_type=area_type,
            quantity=quantity,
            unit=unit,
            estimated_cost=estimated_cost,
            final_cost=final_cost,
            recommended_on=_iso(recommended_on),
            sanctioned_on=_iso(sanctioned_on) if sanctioned_on else None,
            expected_completion_on=(_iso(expected_completion_on)
                                    if expected_completion_on else None),
            completed_on=_iso(completed_on) if completed_on else None,
            status=status,
            progress_pct=progress_pct,
            last_updated_on=_iso(last_updated_on),
            lat=round(rng.uniform(8.2, 33.5), 5),
            lon=round(rng.uniform(69.5, 94.5), 5),
            is_sc_area=1 if rng.random() < config.SC_AREA_WORK_SHARE else 0,
            is_st_area=1 if rng.random() < config.ST_AREA_WORK_SHARE else 0,
            planted_anomaly=None,
        )
        works.append(work)

    session.add_all(works)
    session.flush()
    return works


def _cost_of(work):
    """The cost convention, everywhere: COALESCE(final_cost, estimated_cost).

    Never final_cost alone -- it is NULL for every unfinished work, which
    would silently exclude exactly the works most likely to be problems.
    """
    return work.final_cost if work.final_cost is not None else work.estimated_cost


def _real_unit_cost_of(nominal_cost, work):
    """Constant-price unit cost for a candidate nominal cost."""
    return nominal_cost / work.quantity / config.COST_INDEX[work.fy]


def _real_unit_cost(work):
    """Unit cost in constant base-year prices -- what C5 actually compares.

    The de-collision sweep has to work in the same currency the check does.
    Comparing nominal cost here while checks.py deflates would let two works
    in different financial years sit 18% apart in cash terms, be declared
    clear, and then land inside the 10% band once both are brought to
    constant prices. Measured: 87 clean pairs collided that way.
    """
    return _cost_of(work) / work.quantity / config.COST_INDEX[work.fy]


def decollide_duplicates(works):
    """Break accidental C5 duplicate pairs among clean works.

    C5 pairs two works in the same district and work_type whose unit costs
    are within 10% and whose sanction dates are within 60 days. At 4500
    works over ~50 districts and 8 work types that happens by chance roughly
    455 times -- about 23x the 20 pairs actually planted -- which would
    swamp the signal and make the false-positive rate meaningless.

    Widening the cost spread does not fix it (log-sd 0.55 still leaves
    ~278), and widening it far enough would start tripping C1 instead. So
    collisions are removed directly: walk each (district, work_type) bucket
    in sanction order and push any colliding work's cost outside the band.

    Runs BEFORE anomalies are planted, so the planted pairs survive as the
    only duplicates in the data.

    Iterates to a fixed point rather than sweeping once: moving a cost out of
    one band can drop it into another work's band, so a single forward pass
    leaves a long tail of collisions it created itself (measured: 455 down to
    116, not to zero). Each sweep is deterministic and strictly reduces the
    collision count, so the loop terminates; the bound is a safety net.
    """
    buckets = {}
    for work in works:
        if work.sanctioned_on is None:
            continue
        # A planted work is never nudged -- duplicate_pair depends on its
        # twin staying inside the band, and moving a cost_overrun's cost
        # would undo the anomaly. They still take part as comparison
        # partners, so a clean work is moved away from a planted one.
        buckets.setdefault((work.district_id, work.work_type), []).append(work)

    nudged = 0
    tolerance = config.C5_UNIT_COST_TOLERANCE
    factor = 1.0 + config.C5_DECOLLIDE_MARGIN

    for _sweep in range(config.C5_DECOLLIDE_MAX_SWEEPS):
        collisions = 0
        for key in sorted(buckets):
            # Re-sort every sweep from the CURRENT sanction dates. Planting
            # rewrites sanctioned_on for long_delay works, and the `break`
            # below is only valid on a list sorted by the dates it is
            # actually comparing -- a stale order makes it skip real
            # collisions.
            bucket = sorted(buckets[key], key=lambda w: (w.sanctioned_on, w.work_id))
            for i, work in enumerate(bucket):
                for other in bucket[i + 1:]:
                    gap = (date.fromisoformat(other.sanctioned_on)
                           - date.fromisoformat(work.sanctioned_on)).days
                    if gap > config.C5_WINDOW_DAYS:
                        break  # sorted by date, so nothing later can collide

                    unit_a = _real_unit_cost(work)
                    unit_b = _real_unit_cost(other)
                    if min(unit_a, unit_b) <= 0:
                        continue
                    if abs(unit_a - unit_b) / min(unit_a, unit_b) >= tolerance:
                        continue
                    if other.planted_anomaly is not None:
                        # `other` is the one that gets moved, and a planted
                        # work must keep the cost its anomaly gave it.
                        continue

                    # Move `other` clear of EVERY partner it can be compared
                    # against, not just `work`.
                    #
                    # Fixing one pair at a time oscillates: push X off Y and
                    # it lands on Z, push it back and it lands on Y again.
                    # Measured, that cycles forever -- the same four
                    # collisions re-fixed on all twelve sweeps. So collect
                    # the whole neighbourhood and pick a cost outside all of
                    # their bands at once.
                    #
                    # Downward, below the cheapest neighbour: pushing costs
                    # up instead piles works into the peer group's upper
                    # tail and trips C1's fence, trading one false positive
                    # for another (measured: C1's 2x-median rate went 0.64%
                    # -> 2.25%). Monotonic in one direction, so no cycling.
                    neighbours = []
                    for candidate in bucket:
                        if candidate is other:
                            continue
                        span = abs((date.fromisoformat(candidate.sanctioned_on)
                                    - date.fromisoformat(other.sanctioned_on)).days)
                        if span > config.C5_WINDOW_DAYS:
                            continue
                        unit = _real_unit_cost(candidate)
                        if unit > 0:
                            neighbours.append(unit)

                    target = min(neighbours) if neighbours else unit_a
                    step = factor
                    while True:
                        # target is in constant prices; the column stores
                        # nominal money, so re-inflate before writing.
                        new_cost = max(1, int(round(
                            target / step * other.quantity
                            * config.COST_INDEX[other.fy])))
                        settled = _real_unit_cost_of(new_cost, other)
                        # Rounding to whole rupees over a small quantity can
                        # pull the result back inside a band, so confirm it
                        # cleared all of them before accepting it.
                        if all(abs(settled - unit) / min(settled, unit) >= tolerance
                               for unit in neighbours) or not neighbours:
                            break
                        step *= 1.5

                    if other.final_cost is not None:
                        other.final_cost = new_cost
                    else:
                        other.estimated_cost = new_cost
                    collisions += 1
                    nudged += 1

        if collisions == 0:
            break

    return nudged


# ---------------------------------------------------------------------------
# Phase 6 -- planted anomalies
# ---------------------------------------------------------------------------


def plant_anomalies(session, rng, works, mps, districts, agencies, vendors):
    """Mutate ~290 works into known anomalies and label them.

    planted_anomaly exists only so evaluate.py can measure recall. checks.py
    must never read it and the API must never return it.

    Each label breaks exactly one clean-row invariant, so recall per label
    maps to a single check.
    """
    counts = config.PLANTED_ANOMALY_COUNTS
    pool = [w for w in works if w.planted_anomaly is None]
    rng.shuffle(pool)
    cursor = 0

    def take(n, predicate=None):
        """Claim n unlabelled works, optionally matching a predicate."""
        nonlocal cursor
        chosen = []
        while len(chosen) < n and cursor < len(pool):
            work = pool[cursor]
            cursor += 1
            if work.planted_anomaly is not None:
                continue
            if predicate and not predicate(work):
                continue
            chosen.append(work)
        return chosen

    ref = config.REFERENCE_DATE

    # cost_overrun -- unit cost 3-6x the baseline, which approximates the
    # peer median. Breaks: unit cost inside the peer IQR fence. Check: C1.
    low, high = config.COST_OVERRUN_MULTIPLE_RANGE
    for work in take(counts["cost_overrun"]):
        multiple = rng.uniform(low, high)
        if work.final_cost is not None:
            work.final_cost = int(round(work.final_cost * multiple))
        work.estimated_cost = int(round(work.estimated_cost * multiple))
        work.planted_anomaly = "cost_overrun"

    # long_delay -- sanctioned 400-700 days ago, still unfinished.
    # Breaks: unfinished works sanctioned < 180 days ago. Check: C2.
    low, high = config.LONG_DELAY_DAYS_RANGE
    for work in take(counts["long_delay"],
                     lambda w: w.status in ("sanctioned", "in_progress")):
        days = rng.randint(low, high)
        sanctioned_on = ref - timedelta(days=days)
        recommended_on = sanctioned_on - timedelta(days=rng.randint(20, 90))
        duration = config.EXPECTED_DURATION_DAYS[(work.work_type, work.area_type)]
        work.recommended_on = _iso(recommended_on)
        work.sanctioned_on = _iso(sanctioned_on)
        work.expected_completion_on = _iso(sanctioned_on + timedelta(days=duration))
        work.completed_on = None
        work.status = "in_progress"
        work.progress_pct = round(rng.uniform(10, 55), 1)
        work.last_updated_on = _iso(ref - timedelta(days=rng.randint(60, 200)))
        work.planted_anomaly = "long_delay"

    # impossible_date -- completed before it was sanctioned.
    # Breaks: recommended_on <= sanctioned_on <= completed_on. Check: C3.
    for work in take(counts["impossible_date"],
                     lambda w: w.sanctioned_on is not None):
        sanctioned_on = date.fromisoformat(work.sanctioned_on)
        work.completed_on = _iso(sanctioned_on - timedelta(days=rng.randint(5, 60)))
        work.status = "completed"
        work.progress_pct = 100.0
        if work.final_cost is None:
            work.final_cost = int(round(work.estimated_cost * rng.uniform(0.97, 1.06)))
        work.planted_anomaly = "impossible_date"

    # ineligible_work -- a category the scheme does not permit.
    # Breaks: work_type never from NOT_PERMITTED_WORK_CATEGORIES. Check: C3.
    for work in take(counts["ineligible_work"]):
        category = rng.choice(config.NOT_PERMITTED_WORK_CATEGORIES)
        work.description = f"{work.description} -- {category}"
        work.planted_anomaly = "ineligible_work"

    # duplicate_pair -- a near-identical twin in the same district and
    # work_type, within 60 days and 10% unit cost. Breaks: the de-collision
    # invariant, deliberately. Check: C5. Alerts both works, each naming the
    # other, so both halves carry the label.
    pair_count = counts["duplicate_pair"] // 2
    twins = []
    for work in take(pair_count, lambda w: w.sanctioned_on is not None):
        sanctioned_on = date.fromisoformat(work.sanctioned_on)
        twin_sanctioned = sanctioned_on + timedelta(days=rng.randint(3, 50))
        if twin_sanctioned > ref:
            twin_sanctioned = sanctioned_on - timedelta(days=rng.randint(3, 50))
        duration = config.EXPECTED_DURATION_DAYS[(work.work_type, work.area_type)]

        twin = Work(
            mp_id=work.mp_id,
            constituency_id=work.constituency_id,
            district_id=work.district_id,
            agency_id=work.agency_id,
            vendor_id=work.vendor_id,
            fy=work.fy,
            work_type=work.work_type,
            description=work.description,
            terrain=work.terrain,
            area_type=work.area_type,
            quantity=work.quantity,
            unit=work.unit,
            # Within the 10% band that C5 looks for.
            estimated_cost=int(round(work.estimated_cost * rng.uniform(0.94, 1.06))),
            final_cost=None,
            recommended_on=_iso(twin_sanctioned - timedelta(days=rng.randint(20, 60))),
            sanctioned_on=_iso(twin_sanctioned),
            expected_completion_on=_iso(twin_sanctioned + timedelta(days=duration)),
            completed_on=None,
            status="in_progress",
            progress_pct=round(rng.uniform(15, 70), 1),
            last_updated_on=_iso(ref - timedelta(days=rng.randint(5, 60))),
            lat=work.lat,
            lon=work.lon,
            is_sc_area=work.is_sc_area,
            is_st_area=work.is_st_area,
            planted_anomaly="duplicate_pair",
        )
        work.planted_anomaly = "duplicate_pair"
        twins.append(twin)

    session.add_all(twins)
    session.flush()
    works.extend(twins)

    # payment_ahead_of_work and ghost_asset are labelled here; their
    # payment, progress and evidence rows are written in build_child_records,
    # which reads the label.
    for work in take(counts["payment_ahead_of_work"],
                     lambda w: w.status == "in_progress"):
        work.progress_pct = round(
            rng.uniform(*config.PAYMENT_AHEAD_PROGRESS_RANGE) * 100, 1)
        work.planted_anomaly = "payment_ahead_of_work"

    # ghost_asset -- marked complete, fully paid, no evidence at all.
    # Breaks: completed works have >=1 evidence row. Check: C7.
    for work in take(counts["ghost_asset"],
                     lambda w: w.sanctioned_on is not None):
        sanctioned_on = date.fromisoformat(work.sanctioned_on)
        completed_on = sanctioned_on + timedelta(days=rng.randint(20, 90))
        if completed_on > ref:
            completed_on = ref - timedelta(days=rng.randint(5, 40))
        work.status = "completed"
        work.completed_on = _iso(max(completed_on, sanctioned_on))
        work.progress_pct = 100.0
        if work.final_cost is None:
            work.final_cost = int(round(work.estimated_cost * rng.uniform(0.98, 1.05)))
        work.last_updated_on = work.completed_on
        work.planted_anomaly = "ghost_asset"

    by_name = {d.name: d.district_id for d in districts}
    demo_district_ids = [by_name[name] for name in config.DEMO_DISTRICTS
                         if name in by_name]
    stacked = _plant_stacked_critical(rng, take, ref, demo_district_ids)

    session.flush()
    return works, stacked


def _plant_stacked_critical(rng, take, ref, demo_district_ids=()):
    """Works carrying two problems at once, so the critical band is reachable.

    Every check caps well below 70 -- the largest single award is 35 -- so
    with one anomaly per work nothing ever reached critical and the band was
    dead. A subject earns 70 by being wrong in several independent ways at
    once, which is the honest reading of the word.

    Returns [(work, [labels...])], primary label first. The primary is always
    the C7 one, and that is not cosmetic: build_child_records dispatches on
    works.planted_anomaly to decide the payment ratio and whether to withhold
    evidence, so the label it reads has to be the one whose signal lives in
    the child rows. The cost and delay labels are pure column mutations on the
    work itself and need no such cooperation, which is why they can be the
    secondary label without losing anything.
    """
    combinations = config.STACKED_CRITICAL_COMBINATIONS
    per_combination = config.PLANTED_STACKED_CRITICAL // len(combinations)
    stacked = []

    # The demo opens on do.pune and moves to do.nashik, so each of those two
    # districts needs one of these to land in it. Left to the shuffle they
    # scatter one per district across the country and the opening worklist
    # has no critical row on it at all.
    demo_queue = list(demo_district_ids)

    for index, (first, second) in enumerate(combinations):
        # The C7 label leads, whichever side of the pair it is on.
        primary, secondary = (second, first) if second in (
            "ghost_asset", "payment_ahead_of_work") else (first, second)

        # One pinned district per combination, while any remain.
        pinned = demo_queue.pop(0) if demo_queue else None
        chosen = []
        if pinned is not None:
            chosen = take(1, lambda w, d=pinned: w.district_id == d
                          and w.sanctioned_on is not None
                          and w.vendor_id is not None)

        chosen += take(per_combination - len(chosen),
                       lambda w: w.sanctioned_on is not None
                       and w.vendor_id is not None)

        for work in chosen:
            if secondary == "cost_overrun":
                multiple = rng.uniform(*config.STACKED_COST_MULTIPLE_RANGE)
                work.estimated_cost = int(round(work.estimated_cost * multiple))
                if work.final_cost is not None:
                    work.final_cost = int(round(work.final_cost * multiple))

            elif secondary == "long_delay":
                days = rng.randint(*config.STACKED_DELAY_DAYS_RANGE)
                sanctioned_on = ref - timedelta(days=days)
                duration = config.EXPECTED_DURATION_DAYS[
                    (work.work_type, work.area_type)]
                work.recommended_on = _iso(
                    sanctioned_on - timedelta(days=rng.randint(20, 90)))
                work.sanctioned_on = _iso(sanctioned_on)
                work.expected_completion_on = _iso(
                    sanctioned_on + timedelta(days=duration))

            if primary == "ghost_asset":
                # Complete, fully paid, and no evidence will be written.
                sanctioned_on = date.fromisoformat(work.sanctioned_on)
                completed_on = sanctioned_on + timedelta(days=rng.randint(20, 90))
                if completed_on > ref:
                    completed_on = ref - timedelta(days=rng.randint(5, 40))
                work.status = "completed"
                work.completed_on = _iso(max(completed_on, sanctioned_on))
                work.progress_pct = 100.0
                if work.final_cost is None:
                    work.final_cost = int(round(
                        work.estimated_cost * rng.uniform(0.98, 1.05)))
                # Older than C7_STALE_DAYS while fully paid, so the
                # stale-while-paid component lands on top of the missing
                # evidence rather than the record looking freshly touched.
                work.last_updated_on = _iso(min(
                    date.fromisoformat(work.completed_on),
                    ref - timedelta(days=config.STACKED_STALE_DAYS)))
            else:
                work.status = "in_progress"
                work.completed_on = None
                work.progress_pct = round(
                    rng.uniform(*config.PAYMENT_AHEAD_PROGRESS_RANGE) * 100, 1)

            work.planted_anomaly = primary
            stacked.append((work, [primary, secondary]))

    return stacked


# ---------------------------------------------------------------------------
# Phase 6b -- vendor overpricing
# ---------------------------------------------------------------------------


def plant_vendor_overpricing(session, rng, works, vendors):
    """Make a few vendors price consistently above their peers.

    Returns the chosen vendor_ids -- the label lives on the VENDOR, not on
    each work. Marking every one of their works would credit C1 with catching
    something C8 exists to catch, and would inflate C1's recall for a
    procurement pattern no single work demonstrates.

    Their works will also trip C1 individually, which is correct: the same
    fact is legitimately visible at two levels. evaluate.py must count them
    against the vendor label.

    Only clean works are repriced, so a vendor's inflation never overwrites
    an existing anomaly and the per-label counts stay exact.
    """
    by_vendor = {}
    for work in works:
        if work.vendor_id is None or work.planted_anomaly is not None:
            continue
        by_vendor.setdefault(work.vendor_id, []).append(work)

    # Enough works to make a median meaningful, or the check cannot see it.
    eligible = sorted(
        vid for vid, rows in by_vendor.items()
        if len(rows) >= config.C8_MIN_WORKS_FOR_PRICE * 2
    )
    chosen = rng.sample(eligible, min(config.PLANTED_VENDOR_OVERPRICING,
                                      len(eligible)))

    low, high = config.VENDOR_OVERPRICING_MULTIPLE_RANGE
    for vendor_id in sorted(chosen):
        for work in sorted(by_vendor[vendor_id], key=lambda w: w.work_id):
            multiple = rng.uniform(low, high)
            work.estimated_cost = int(round(work.estimated_cost * multiple))
            if work.final_cost is not None:
                work.final_cost = int(round(work.final_cost * multiple))

    session.flush()
    return sorted(chosen)


# ---------------------------------------------------------------------------
# Phase 7 -- payments, progress history, evidence, complaints
# ---------------------------------------------------------------------------


def build_child_records(session, rng, fake, works, users, sparse_work_ids,
                        stacked=()):
    """Money, progress history and proof, keyed off each work's label.

    Clean rows keep the payment ratio within CLEAN_MAX_PAYMENT_PROGRESS_GAP
    of the progress ratio, so C7 does not fire on them.

    Evidence matters by its absence: a completed work with no rows here is
    exactly what needs verification.
    """
    payments, updates, evidence = [], [], []
    ref = config.REFERENCE_DATE

    for work in works:
        label = work.planted_anomaly
        cost = _cost_of(work)
        progress_ratio = (work.progress_pct or 0) / 100.0

        if work.sanctioned_on is None:
            continue
        sanctioned_on = date.fromisoformat(work.sanctioned_on)

        # --- payment ratio -------------------------------------------------
        if label == "payment_ahead_of_work":
            paid_ratio = rng.uniform(*config.PAYMENT_AHEAD_RATIO_RANGE)
        elif label == "ghost_asset":
            paid_ratio = 1.0
        elif work.status == "completed":
            paid_ratio = 1.0
        elif work.status == "in_progress":
            # Slightly behind the build, never ahead of it.
            paid_ratio = max(0.0, progress_ratio
                             - rng.uniform(0.0, config.CLEAN_MAX_PAYMENT_PROGRESS_GAP))
        else:
            paid_ratio = 0.0

        if paid_ratio > 0:
            tranches = 1 if paid_ratio < 0.4 else rng.randint(2, 3)
            remaining = paid_ratio
            for tranche_no in range(1, tranches + 1):
                share = (remaining if tranche_no == tranches
                         else remaining * rng.uniform(0.4, 0.6))
                remaining -= share
                amount = int(round(cost * share))
                if amount <= 0:
                    continue
                paid_on = sanctioned_on + timedelta(
                    days=rng.randint(15, max(20, (ref - sanctioned_on).days)))
                payments.append(Payment(
                    work_id=work.work_id,
                    vendor_id=work.vendor_id,
                    tranche_no=tranche_no,
                    amount=amount,
                    paid_on=_iso(min(paid_on, ref)),
                    progress_pct_at_payment=work.progress_pct,
                    voucher_ref=f"VCH/{work.fy[:4]}/{work.work_id:06d}/{tranche_no}",
                ))

        # --- progress history ----------------------------------------------
        # Deliberately skipped for the sparse slice, so step 03's
        # graceful-degradation path is exercised by the data.
        if work.work_id not in sparse_work_ids and work.progress_pct:
            steps = rng.randint(2, 5)
            for step in range(1, steps + 1):
                pct = round(work.progress_pct * step / steps, 1)
                reported_on = sanctioned_on + timedelta(
                    days=int((ref - sanctioned_on).days * step / (steps + 1)))
                updates.append(ProgressUpdate(
                    work_id=work.work_id,
                    progress_pct=pct,
                    reported_on=_iso(min(reported_on, ref)),
                    reported_by=rng.choice(("agency", "district_office", "site_engineer")),
                    note=None,
                ))

        # --- evidence -------------------------------------------------------
        # ghost_asset gets nothing at all -- that absence is the signal.
        if label == "ghost_asset":
            continue
        if work.status == "completed":
            kinds = ("photo", "completion_cert", "utilisation_cert")
        elif work.status == "in_progress" and rng.random() < 0.72:
            kinds = ("photo",)
        else:
            kinds = ()

        for kind in kinds:
            captured_at = date.fromisoformat(work.completed_on or work.last_updated_on)
            evidence.append(Evidence(
                work_id=work.work_id,
                kind=kind,
                file_path=f"evidence/{work.work_id:06d}/{kind}.jpg",
                photo_hash=(hashlib.sha256(
                    f"{work.work_id}|{kind}".encode()).hexdigest()[:24]
                    if kind == "photo" else None),
                exif_lat=work.lat,
                exif_lon=work.lon,
                stage=("after" if work.status == "completed" else "during")
                if kind == "photo" else None,
                captured_at=_iso(captured_at),
                uploaded_at=_iso(min(captured_at + timedelta(days=rng.randint(0, 6)), ref)),
            ))

    session.add_all(payments)
    session.add_all(updates)
    session.add_all(evidence)
    session.flush()

    # --- complaints ---------------------------------------------------------
    # UNIQUE(work_id, user_id): one complaint per citizen per work, which is
    # what makes C6's distinct-reporter count meaningful.
    citizens = [u for u in users if u.role == "citizen"]
    officers = [u for u in users if u.role in ("district_officer", "state_officer")]
    complaints = []

    # Weighted toward works that already look troubled, as real reports are
    # -- but never onto a clean work, which would stack C6 on top of any
    # incidental C1 fence hit and manufacture a false-positive alert.
    # The stacked works are handled separately below, with a fixed number of
    # verified reports, so they must not also draw a random count here.
    stacked_ids = {w.work_id for w, _ in stacked}

    candidates = [w for w in works if w.planted_anomaly in
                  ("ghost_asset", "long_delay", "payment_ahead_of_work")
                  and w.work_id not in stacked_ids]
    rng.shuffle(candidates)

    for work in candidates[:90]:
        for citizen in rng.sample(citizens, rng.randint(1, 4)):
            complaints.append(Complaint(
                work_id=work.work_id,
                user_id=citizen.user_id,
                text=rng.choice((
                    "Work has not progressed for several months.",
                    "Site appears incomplete despite completion notice.",
                    "Requesting verification of this work.",
                    "No activity observed at the location.",
                )),
                photo_path=None,
                lat=work.lat,
                lon=work.lon,
                verified=1 if rng.random() < 0.65 else 0,
                verified_by=rng.choice(officers).user_id if officers else None,
                created_at=_iso(ref - timedelta(days=rng.randint(10, 300))),
            ))

    # The stacked works need C6's top band (4+ distinct verified reporters)
    # to clear 70, so the count is fixed and verified = 1 outright rather
    # than left to the coin flip above. A critical count that moved with the
    # random draw would not be reproducible, and reproducibility is the whole
    # reason REFERENCE_DATE and RANDOM_SEED are pinned.
    for work, _labels in stacked:
        for citizen in rng.sample(citizens, config.STACKED_CRITICAL_COMPLAINTS):
            complaints.append(Complaint(
                work_id=work.work_id,
                user_id=citizen.user_id,
                text=rng.choice((
                    "Work has not progressed for several months.",
                    "Site appears incomplete despite completion notice.",
                    "Requesting verification of this work.",
                    "No activity observed at the location.",
                )),
                photo_path=None,
                lat=work.lat,
                lon=work.lon,
                verified=1,
                verified_by=rng.choice(officers).user_id if officers else None,
                created_at=_iso(ref - timedelta(days=rng.randint(10, 300))),
            ))

    session.add_all(complaints)
    session.flush()
    return payments, updates, evidence, complaints


# ---------------------------------------------------------------------------
# Phase 6b -- MP quota shortfall, and reconciling allocations
# ---------------------------------------------------------------------------


def reconcile_allocations(session, rng, works, allocations, mps,
                          demo_state_id=None):
    """Set allocations.spent from the works, then force 4 MPs under the SC floor.

    quota_shortfall is an MP-level anomaly: it writes no work-level label,
    because C3-MP scores the MP and recall must be measured against the same
    subject type. Awarding it to each of the MP's works would flag every
    work that MP ever recommended -- a false-positive machine.
    """
    spent = {}
    for work in works:
        if work.status == "recommended":
            continue
        spent[(work.mp_id, work.fy)] = spent.get((work.mp_id, work.fy), 0) + _cost_of(work)

    # The min() is a bound, not a correction: a member cannot draw more than
    # was released to them. It should almost never bind now that works are
    # sized realistically against the entitlement. When it bound routinely it
    # silently pinned spent == released for every allocation, so the spend
    # ratio was 1.0 everywhere, and C4 -- which compares that ratio with the
    # share of the year elapsed -- could not fire on any district.
    for allocation in allocations:
        allocation.spent = min(
            spent.get((allocation.mp_id, allocation.fy), 0), allocation.released)

    # Force the SC-area share below the 15% floor for a few MPs by clearing
    # the flag on their SC works.
    #
    # The target is a fraction of RELEASED funds, because that is the
    # denominator C3-MP measures against. Taking it from total work cost
    # instead leaves the planting silently ineffective: works routinely cost
    # several times what was released in any one year, so a target set at 40%
    # of the floor-times-total-cost still lands comfortably above the floor
    # once divided by released, and every planted MP passes the check.
    released_by_mp = {}
    for allocation in allocations:
        released_by_mp[allocation.mp_id] = (
            released_by_mp.get(allocation.mp_id, 0) + allocation.released)

    eligible = sorted(
        mp_id for mp_id in {w.mp_id for w in works}
        if released_by_mp.get(mp_id, 0) > 0
    )

    # One of them must sit in the demo's state. MP-quota alerts route to the
    # State Officer, and the demo signs in as so.mh to show exactly the rows
    # a district officer does not get -- left to chance all four landed in
    # other states and that worklist had nothing on it.
    demo_state = {mp.mp_id for mp in mps
                  if mp.state_id == demo_state_id} & set(eligible)
    pinned = [min(demo_state)] if demo_state else []
    rest = rng.sample([m for m in eligible if m not in pinned],
                      config.PLANTED_QUOTA_SHORTFALL_MPS - len(pinned))
    shortfall_mps = sorted(pinned + rest)
    for mp_id in shortfall_mps:
        mp_works = [w for w in works
                    if w.mp_id == mp_id and w.is_sc_area == 1
                    and w.status != "recommended"]
        # Well under the floor, so the shortfall is unambiguous rather than
        # sitting on the boundary where rounding decides the outcome.
        #
        # At 0.4 the planted share landed near 6% against a 15% floor, which
        # scored just under the alert threshold for a member who met the ST
        # floor -- the anomaly was real, detected, and still invisible to an
        # officer. A fifth of the floor is decisively short.
        target = released_by_mp[mp_id] * config.SC_AREA_FLOOR * 0.2
        running = 0
        for work in sorted(mp_works, key=lambda w: w.work_id):
            if running + _cost_of(work) <= target:
                running += _cost_of(work)
            else:
                work.is_sc_area = 0

    session.flush()
    return shortfall_mps


def record_planted_subjects(session, subject_type: str, label: str,
                            subject_ids: list[int]) -> None:
    """Persist which MPs or vendors were planted, so recall can be measured.

    works.planted_anomaly carries the ground truth for the seven work-level
    labels, but quota_shortfall is chosen per MP and vendor_overpricing per
    vendor, and neither table has such a column. Without a record the ids are
    discarded at the end of generation and evaluate.py has nothing to compare
    against -- it cannot infer them from the scores, because far more MPs
    cross the alert threshold than were ever planted.

    audit_log is the right home: it already exists for system provenance,
    takes a NULL user_id for actions the system took itself, and its
    subject_type/subject_id pair is already polymorphic.
    """
    session.add_all([
        AuditLog(
            user_id=None,
            action="planted_anomaly",
            subject_type=subject_type,
            subject_id=subject_id,
            detail=label,
            created_at=_iso(config.REFERENCE_DATE),
        )
        for subject_id in sorted(subject_ids)
    ])
    session.flush()


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def generate() -> dict:
    """Build the whole database. Returns row counts for the summary block."""
    # One seeded instance, threaded through every function. Nothing here
    # touches the global `random` module, and Faker is seeded separately
    # because it keeps its own generator.
    rng = random.Random(config.RANDOM_SEED)
    fake = Faker("en_IN")
    Faker.seed(config.RANDOM_SEED)

    init_db()

    with get_session() as session:
        states, districts, constituencies, mps = build_geography(session, rng, fake)
        agencies, vendors = build_agencies_and_vendors(
            session, rng, fake, districts)
        users = build_users(
            session, rng, fake, states, districts, constituencies, mps)
        allocations = build_allocations(session, rng, mps)

        works = build_works(session, rng, fake, districts, constituencies,
                            mps, agencies, vendors)

        # Before anomalies, so the planted duplicate pairs survive as the
        # only ones in the data.
        nudged = decollide_duplicates(works)
        session.flush()

        works, stacked = plant_anomalies(session, rng, works, mps, districts,
                                         agencies, vendors)

        # Before the de-collision sweep, so repriced works are de-collided
        # like any other. These works stay unlabelled -- the anomaly belongs
        # to the vendor, not to any one job.
        overpriced_vendors = plant_vendor_overpricing(
            session, rng, works, vendors)

        # Again, because planting rewrites costs and sanction dates
        # (cost_overrun, long_delay, impossible_date) and so creates fresh
        # collisions among clean works. This pass skips planted works
        # entirely, so the 20 planted pairs survive it.
        nudged += decollide_duplicates(works)
        session.flush()

        # The graceful-degradation slice: progress_pct = 0 and no
        # progress_updates rows. Picked from clean works only, so a skipped
        # check never coincides with a planted anomaly.
        clean_in_progress = sorted(
            (w for w in works
             if w.planted_anomaly is None and w.status == "in_progress"),
            key=lambda w: w.work_id)
        sparse = rng.sample(
            clean_in_progress,
            min(config.WORKS_WITHOUT_PROGRESS_DATA, len(clean_in_progress)))
        for work in sparse:
            work.progress_pct = 0.0
        sparse_ids = {w.work_id for w in sparse}
        session.flush()

        payments, updates, evidence, complaints = build_child_records(
            session, rng, fake, works, users, sparse_ids, stacked)
        demo_state = next((s for s in states
                           if s.code == config.DEMO_STATE_CODE), None)
        shortfall_mps = reconcile_allocations(
            session, rng, works, allocations, mps,
            demo_state.state_id if demo_state else None)

        # Ground truth for the two subject-level anomalies, which have no
        # planted_anomaly column to live in.
        record_planted_subjects(session, "mp", "quota_shortfall",
                                shortfall_mps)
        record_planted_subjects(session, "vendor", "vendor_overpricing",
                                overpriced_vendors)

        # Secondary labels of the stacked works, for the same reason: a work
        # has one planted_anomaly column and these carry two problems. The
        # primary label stays in the column so the existing per-label table
        # and build_child_records' dispatch keep working; the extra label is
        # recorded here and merged back by evaluate.py, so each component
        # label is still measured on every work that actually carries it.
        secondary = {}
        for work, labels in stacked:
            for label in labels[1:]:
                secondary.setdefault(label, []).append(work.work_id)
        for label, work_ids in sorted(secondary.items()):
            record_planted_subjects(session, "work", label, sorted(work_ids))

        planted = {}
        for work in works:
            if work.planted_anomaly:
                planted[work.planted_anomaly] = planted.get(work.planted_anomaly, 0) + 1

        stacked_by_primary = {}
        for _work, labels in stacked:
            stacked_by_primary[labels[0]] = stacked_by_primary.get(labels[0], 0) + 1

        return {
            "states": len(states),
            "districts": len(districts),
            "constituencies": len(constituencies),
            "mps": len(mps),
            "agencies": len(agencies),
            "vendors": len(vendors),
            "users": len(users),
            "allocations": len(allocations),
            "works": len(works),
            "payments": len(payments),
            "progress_updates": len(updates),
            "evidence": len(evidence),
            "complaints": len(complaints),
            "planted": planted,
            "decollided": nudged,
            "overpriced_vendors": len(overpriced_vendors),
            "sparse": len(sparse),
            "quota_shortfall_mps": len(shortfall_mps),
            "stacked_critical": len(stacked),
            "stacked_by_primary": stacked_by_primary,
        }


def main() -> None:
    counts = generate()

    print(f"Generated {counts['works']} works into backend/mplads.db\n")

    print("  Reference data")
    for key in ("states", "districts", "constituencies", "mps", "agencies",
                "vendors", "users", "allocations"):
        print(f"    {key:20} {counts[key]:>6}")

    print("\n  Scheme records")
    for key in ("works", "payments", "progress_updates", "evidence",
                "complaints"):
        print(f"    {key:20} {counts[key]:>6}")

    print("\n  Planted anomalies (ground truth for evaluate.py)")
    total = 0
    stacked_primaries = counts["stacked_by_primary"]
    for label in sorted(counts["planted"]):
        found = counts["planted"][label]
        # Stacked works carry their C7 label in the column too, so the
        # single-label target only accounts for part of the count.
        target = (config.PLANTED_ANOMALY_COUNTS.get(label, 0)
                  + stacked_primaries.get(label, 0))
        flag = "" if found == target else f"  <-- expected {target}"
        extra = (f"  ({stacked_primaries[label]} stacked)"
                 if stacked_primaries.get(label) else "")
        print(f"    {label:24} {found:>4}{flag}{extra}")
        total += found
    print(f"    {'quota_shortfall (MPs)':24} {counts['quota_shortfall_mps']:>4}")
    print(f"    {'total work-level':24} {total:>4}")

    # Counted once each here; evaluate.py credits them under both labels.
    print(f"\n  Stacked critical works (2 labels each): "
          f"{counts['stacked_critical']}")

    print(f"    {'vendor_overpricing (vendors)':24} "
          f"{counts['overpriced_vendors']:>4}")

    print(f"\n  C5 collisions removed from clean rows: {counts['decollided']}")
    print(f"  Sparse works (no progress history):    {counts['sparse']}")


if __name__ == "__main__":
    main()
