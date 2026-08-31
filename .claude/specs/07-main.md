# Step 04 — API endpoints

## Overview

`main.py` turns the scored database into JSON the React app can render.

It adds **no logic**. Every number it returns was computed by
`checks.py` and stored in `scores`. If a value is not in the database,
the API does not invent it — and the frontend must never recompute one
that is not in the response.

Three routers:

| Router | Prefix | Who |
|---|---|---|
| Auth | `/auth` | everyone, and the unauthenticated login |
| Citizen | `/citizen` | role `citizen` only |
| Officer | `/officer` | the other four roles, filtered by `require_role` |

### Three portals, two routers

Five roles, **three home screens**, **two routers**. Page count and
router count answer different questions, and conflating them is how a
third router gets added for no safety benefit.

| Portal | Roles | Calls | Home screen |
|---|---|---|---|
| **Citizen** `/citizen` | citizen | `/citizen/*` only | Works in their area — facts, photos, overdue flag, complaint button |
| **Worklist** `/officer` | district_officer, state_officer | `/officer/*` incl. the PATCH routes | Ranked alerts + act buttons |
| **Oversight** `/oversight` | mp, ministry | `/officer/*` **reads only** | Dashboard. No action buttons anywhere |

District and State Officer share a portal because they match on **every
row** of the permission matrix — only their scope differs, and scope
comes from the token. The State Officer's extra content (MP-quota and
district-utilisation alerts) is not a different page; it is the same
worklist holding more subject types, which `SUBJECT_ROUTING` already
produces. So that view costs almost nothing on top of the District
Officer's.

**The Oversight portal has no router of its own.** MPs and Ministry
users hit the same `/officer/*` read endpoints, and
`require_role(*ALERT_ACTOR_ROLES)` on the four write endpoints returns
403 if they try to act. A third router would add files without adding
safety.

The router split exists to protect **data exposure**, not page count:
`/citizen/*` has no code path that selects `total_score`, so a leak
requires someone to add the field deliberately. MPs and Ministry
legitimately see scores, so there is no such guarantee to protect for
them — their restriction is on writes.

Inside Oversight the shell is shared and widgets differ by scope: an MP
gets the SC/ST quota meter and their constituency's works; the Ministry
gets national league tables and trends. Neither renders an action
button.

After login the frontend redirects on `user.role` from `/auth/login`:

```js
const PORTAL = {
  citizen: "/citizen", district_officer: "/officer",
  state_officer: "/officer", mp: "/oversight", ministry: "/oversight",
};
```

**That map is convenience, not security.** A route guard bounces an MP
who deep-links `/officer` so they do not see a broken page — the
enforcement is that every write call still returns 403.

## Depends on

- **Step 05 (auth)** — build that first. Every route here depends on
  `get_current_user`, `require_active_user`, `require_role` and
  `scope_filter`. Retrofitting auth onto finished routes is how one
  route gets missed.
- Step 03 — populated `scores` and `alerts`.

---

## Files

```
backend/
├── main.py         ← NEW: app, middleware, router registration
├── routers/
│   ├── __init__.py
│   ├── auth.py     ← login/logout/me
│   ├── citizen.py
│   └── officer.py
└── schemas.py      ← NEW: all Pydantic models
```

Splitting routers keeps `main.py` under 60 lines — app creation, CORS,
error handlers, `include_router`. A single-file API is unreadable by the
time the officer portal is done.

New dependencies: `fastapi`, `uvicorn`, `pydantic` (comes with FastAPI).

---

## Two things that will block you on day one

### CORS

The frontend runs on `:5173`, the API on `:8000`. Different origins, so
the browser blocks every request unless the server says otherwise. The
symptom is a network error in the console with no server-side log at
all, which is genuinely confusing the first time.

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

Name the origin explicitly. `allow_origins=["*"]` with
`allow_credentials=True` is rejected by browsers anyway, and it is a bad
habit to demonstrate in a government-facing project.

### `reasons_json` must be parsed, not passed through

It is stored as `Text`. If the API returns it raw, the frontend receives
a **string** inside JSON and has to `JSON.parse` it — every component,
every time, with no type safety.

Parse it server-side and return a real array. Same for `checks_run` and
`checks_skipped`.

---

## Which clock

`CLAUDE.md` forbids `date.today()` in `backend/`. `main.py` needs a
narrow exception, and the line is:

**`REFERENCE_DATE` for facts about the data. The real clock for events
happening now.**

| Use | Clock |
|---|---|
| "242 days overdue" shown to a citizen | `REFERENCE_DATE` |
| Any delay, age, or duration derived from work dates | `REFERENCE_DATE` |
| `alerts.created_at`, `resolved_at` when an officer acts | real UTC |
| Is `snoozed_until` still in the future? | real UTC |
| JWT `exp` (in `auth.py`) | real UTC |

An overdue count is a property of the dataset and must not change
overnight. A snooze an officer set five minutes ago is a real-world
event. Extend the DoD grep:

```bash
grep -rn "date.today\|datetime.now" backend/ \
  --exclude=auth.py --exclude-dir=routers      # empty
```

Nothing in `checks.py`, `evaluate.py` or `generate_data.py` may know
what time it is.

---

## Response models — where the citizen guarantee lives

Every response goes through an explicit Pydantic model. Never return an
ORM object, never return a raw dict built from `row._mapping`.

**`planted_anomaly` appears in no response model anywhere.** Not the
officer's, not the Ministry's. It is the answer key; exposing it through
an API would make the accuracy claim meaningless.

**`specification` is display-only** — it may be returned, and the alert
detail should show it, but nothing scores it.

Two families, and the separation is the point:

```python
class CitizenWork(BaseModel):
    work_id: int
    description: str
    work_type: str
    specification: str | None
    quantity: float
    unit: str
    cost: int                     # COALESCE(final_cost, estimated_cost)
    status: str
    recommended_on: str
    sanctioned_on: str | None
    expected_completion_on: str | None
    completed_on: str | None
    days_overdue: int | None      # from REFERENCE_DATE
    vendor_name: str | None
    district_name: str
    lat: float | None
    lon: float | None
    photo_urls: list[str]
    # NO total_score. NO severity. NO reasons. NO planted_anomaly.
```

**Delay is a fact, not a score.** `days_overdue` is arithmetic on two
fields already on the citizen's screen. Show it. Hiding it makes the
page less honest, not more careful — and it is why
`expected_completion_on` is a stored column.

Contractor names are public record and may be shown. **Never beside a
risk score on a public page** — which the model above makes structurally
impossible.

---

## Endpoints

`★` = minimum viable. Build these five first and the demo works.

### Auth — `/auth`

| | Method | Path | Notes |
|---|---|---|---|
| ★ | POST | `/auth/login` | Spec 05. The only unauthenticated route |
| | POST | `/auth/logout` | Writes an audit row. The client discards the token; the server cannot revoke it |
| ★ | GET | `/auth/me` | Principal + resolved `scope_name`. The frontend calls this on refresh to restore session |

### Officer — `/officer`

| | Method | Path | Notes |
|---|---|---|---|
| ★ | GET | `/officer/alerts` | **The worklist. The home screen** |
| ★ | GET | `/officer/alerts/{alert_id}` | The evidence pack |
| ★ | PATCH | `/officer/alerts/{alert_id}` | acknowledge / escalate / resolve / snooze |
| | GET | `/officer/works/{work_id}` | Full work incl. score, payments, progress, evidence |
| | GET | `/officer/dashboard` | Role-shaped summary counts |
| | GET | `/officer/complaints?verified=0` | Pending verification queue |
| | PATCH | `/officer/complaints/{id}` | Mark verified |
| | GET | `/officer/mps/{mp_id}` | Quota meter against the 15% / 7.5% floors |
| | GET | `/officer/districts` | District comparison — state officer and Ministry |

**Which portal calls which:**

| Endpoint | Worklist | Oversight |
|---|:--:|:--:|
| `GET /officer/alerts` | ✅ home screen | ✅ read-only list |
| `GET /officer/alerts/{id}` | ✅ with act buttons | ✅ without them |
| `PATCH /officer/alerts/{id}` | ✅ | ❌ **403** |
| `GET /officer/works/{id}` | ✅ | ✅ |
| `GET /officer/dashboard` | ✅ | ✅ **primary screen** |
| `GET /officer/complaints` | ✅ | ❌ 403 |
| `PATCH /officer/complaints/{id}` | ✅ | ❌ 403 |
| `GET /officer/mps/{mp_id}` | ✅ | ✅ MP sees only their own |
| `GET /officer/districts` | state officer only | ✅ Ministry |

`GET /officer/dashboard` returns a **role-shaped** payload, not one
blob the frontend filters. An MP gets their quota meter, unspent
balance and stalled works; the Ministry gets national counts and
trends; an officer gets their open-alert counts by severity. Each
role's view is a different shape, not one screen relabelled — building
one dashboard and hiding fields per role is visible to anyone looking
closely, and it puts the filtering decision in the frontend where it
does not belong.

`GET /officer/mps/{mp_id}` must check that an `mp`-role caller is
asking about **their own** `mp_id` (from `users.mp_id`), not any MP.
Otherwise one MP can read another's compliance record by changing a
number in the URL.

### Citizen — `/citizen`

| | Method | Path | Notes |
|---|---|---|---|
| | GET | `/citizen/works` | Paginated, filterable. Facts only |
| | GET | `/citizen/works/{work_id}` | Same shape, one row |
| | POST | `/citizen/works/{work_id}/complaints` | One per citizen per work |
| | GET | `/citizen/complaints` | Their own reports and status |

---

## `GET /officer/alerts` — the one that matters

Query params — **all optional, none of them a scope identifier**:

```
severity=critical|high|medium
status=open|acknowledged|escalated|resolved      (default: not resolved)
subject_type=work|mp|district
limit=50   offset=0
```

**There is no `district_id` parameter, and there must never be one.**
Scope comes from `scope_filter(…, principal)`. A route that accepts a
district id lets an officer type someone else's.

Snoozed alerts are excluded by default when `snoozed_until` is in the
future (real clock). `include_snoozed=true` brings them back — the
alert returns rather than disappearing, which is the whole reason snooze
exists instead of a dismiss button.

Sort: `total_score DESC, alert_id ASC`. The second key is not cosmetic —
without it, ties reorder between requests and the list appears to
shuffle while an officer is reading it. `idx_scores_total` covers this.

### Avoid the N+1

The list needs each alert's score, subject description, and district. A
naive loop issues 1 + 3N queries and a 50-row page takes over a second.

One joined statement, or `selectinload`. The subject join is the
polymorphic trap:

```python
.where(Score.subject_type == "work")     # filter BEFORE the join, always
.join(Work, Work.work_id == Score.subject_id)
```

Keep the filter and the join in one shared helper so no future edit can
separate them. Without it a district-level score with `subject_id = 3`
silently renders as work #3 — no error, just a wrong row on an officer's
screen.

### Response

```json
{
  "total": 312,
  "limit": 50,
  "offset": 0,
  "items": [
    {
      "alert_id": 87,
      "severity": "critical",
      "status": "open",
      "total_score": 78,
      "subject_type": "work",
      "subject_id": 1183,
      "subject_label": "Road widening, Shivajinagar to Kothrud",
      "district_name": "Pune",
      "top_reason": "Cost per km is ₹8.4 lakh at 2026 prices against a median of ₹2.0 lakh for 47 comparable works (4.2×).",
      "checks_fired": ["C1", "C7"],
      "created_at": "2026-09-15T02:00:00"
    }
  ]
}
```

`total` is required — the frontend cannot render pagination without it.

`top_reason` is the highest-scoring reason, pre-selected server-side.
The list shows one line; the detail shows all of them. **A bare score is
never displayed alone** — not in a table cell, not in a tooltip.

---

## `GET /officer/alerts/{alert_id}` — the evidence pack

This is the screen the entire project rests on. If an officer cannot
explain the score from what is here, the check that failed to explain
itself is broken.

Returns, in one response:

- the alert (status, severity, verdict, assignee, snooze)
- the score: `total_score`, all seven `*_points` columns, `scored_on`
- **`reasons`** — the parsed array, each with `check`, `points`,
  `reason`, `evidence`
- **`checks_run` and `checks_skipped`** — so the page can say *"5 of 9
  checks ran; payment and evidence checks require authenticated eSAKSHI
  data."* That line tells a judge the system knows what it needs and
  degrades honestly
- the subject: full work detail including `specification`
- payments, progress history, evidence rows, complaints on that work

`specification` matters here specifically. An officer reading *"₹31 lakh
above the median"* alongside *"G+2, 2 lifts"* can judge whether the
build explains the gap before spending a morning on a site visit.

**404 if the alert does not exist. 403 if it exists outside your
scope.** Both with a generic body. 403 rather than 404 for scope is
deliberate: an officer already knows other districts have alerts, and
during development a 404 makes a genuine wrong-id bug
indistinguishable from a scope violation. It is also what makes the
demo legible — paste Pune's alert URL into Nashik's session, get a clear
refusal.

---

## `PATCH /officer/alerts/{alert_id}` — acting on it

`Depends(require_active_user)` and
`Depends(require_role(*config.ALERT_ACTOR_ROLES))`. District and State
officers only. MP or Ministry → **403**.

```json
{ "status": "resolved",
  "verdict": "not_substantiated",
  "resolution_note": "Site inspected 12 Sep. Hill cutting and retaining wall explain the cost." }
```

Validation, enforced **here**, not in the schema:

| Rule | Failure |
|---|---|
| `status = resolved` requires `verdict` **and** `resolution_note` (≥ 20 chars) | 422 |
| `status = snoozed` requires `snoozed_until`, in the future | 422 |
| An already-`resolved` alert cannot be silently re-resolved | 409 |
| The alert must be in the caller's scope | 403 |

**The verdict requirement is not decoration.** An officer must not be
able to clear a ₹31 lakh alert with a bare "visited" button. Closing an
alert records what was found — and over time those verdicts are how
thresholds get calibrated against reality instead of guesswork.

Sets `resolved_at` from the **real clock**. Writes an `audit_log` row
through `crud.write_audit` in the same transaction — the state change
and its audit record land together or not at all.

---

## Citizen endpoints

`GET /citizen/works` — paginated, filters on `work_type`, `status`,
`district_id`. A district filter is fine **here**: MPLADS work lists are
public record and a citizen browsing another district leaks nothing. The
protection on this router is that scores are absent, not that rows are
narrow.

`POST /citizen/works/{work_id}/complaints` — body is `text`, optional
`photo_path`, `lat`, `lon`. `user_id` comes from the token, never the
body. A second complaint on the same work by the same user violates
`UNIQUE(work_id, user_id)` → **409**, not a 500. Catch the
`IntegrityError` and return a clear message.

New complaints are `verified = 0` and score nothing until an officer
verifies them. Only verified, distinct-reporter complaints feed C6 —
otherwise the score becomes a brigading target.

---

## Errors

One shape everywhere:

```json
{ "detail": "Invalid credentials" }
```

| Code | Meaning |
|---|---|
| 401 | Not authenticated, or a bad/expired token |
| 403 | Authenticated but not permitted, or out of scope |
| 404 | Does not exist |
| 409 | Conflict — duplicate complaint, already resolved |
| 422 | Validation failed |

Register a handler so an unexpected exception returns `{"detail":
"Internal error"}` and logs the traceback server-side. A stack trace in
a response body is an information leak, and it looks terrible on a
projector.

---

## Rules for implementation

- Every route except `/auth/login` depends on `get_current_user`.
- Every **write** route depends on `require_active_user`.
- **No route accepts a district, state or constituency id as a scope
  argument.** The citizen work filter is browsing, not scoping.
- Scope is applied through the shared `scope_filter`, never a per-route
  `WHERE`.
- Every response is an explicit Pydantic model. No ORM objects, no raw
  dicts.
- `planted_anomaly` appears in no model.
- Parse `reasons_json`, `checks_run`, `checks_skipped` server-side.
- Name columns in every query. No `SELECT *`, no unbounded `.all()`.
- Every list endpoint paginates. `works` has 6,000 rows.
- The API computes nothing a check should have computed. If the UI needs
  a number, it belongs in `evidence`.

---

## Definition of done

```bash
export JWT_SECRET="..."
uvicorn backend.main:app --reload --port 8000
```

- [ ] `/docs` loads and lists every endpoint — free from FastAPI, and
      worth showing a judge as proof the API is real
- [ ] `GET /officer/alerts` as `do.pune` returns only Pune subjects,
      verified against a direct SQL count
- [ ] Same call as `do.nashik` returns a different, non-overlapping set
- [ ] `so.maharashtra` sees both, plus MP-quota and district-utilisation
      alerts; `do.pune` sees neither of those
- [ ] Sorted by `total_score` descending; two identical calls return
      identical order
- [ ] `total` is present and matches the unpaginated count
- [ ] A 50-row page returns in well under 500 ms — if not, it is the N+1
- [ ] Alert detail returns parsed `reasons` as an array of objects, not
      a string
- [ ] `checks_run` + `checks_skipped` are present and non-empty
- [ ] Fetching a Nashik alert as `do.pune` → **403**; a nonexistent id →
      **404**
- [ ] `PATCH` to resolve without a verdict → 422; with one → 200 and an
      `audit_log` row appears
- [ ] `PATCH` as `mp.pune` → 403; as `ministry` → 403
- [ ] `mp.pune` **can** read `GET /officer/alerts` and the detail — the
      Oversight portal needs them
- [ ] `mp.pune` requesting `GET /officer/mps/{another mp_id}` → 403
- [ ] `GET /officer/dashboard` returns a different shape for `mp`,
      `ministry` and `district_officer` — not one payload the frontend
      filters
- [ ] Filing the same complaint twice → 409, not 500
- [ ] No citizen response contains `total_score`, `severity`, `reasons`,
      or `planted_anomaly` — grep the raw JSON, do not just read the
      model
- [ ] `citizen.pune` on any `/officer/*` route → 403
- [ ] The React dev server on `:5173` can call the API without a CORS
      error

```bash
grep -rn "planted_anomaly" backend/routers/ backend/schemas.py   # empty
grep -rn "SELECT \*" backend/                                    # empty
grep -rn "district_id" backend/routers/officer.py | grep -i "Query\|Body"  # empty
```

Then the test no checklist covers: open the top alert in the browser and
read it aloud. If you cannot explain why it scored what it scored using
only what is on screen, the API is not returning enough — or a check is
not explaining itself, which is worse.

---

## What this step does not do

- No CSV/Excel upload — step 11.
- No WebSockets or live refresh. The officer reloads the page.
- No caching. SQLite with the right indexes is fast enough at this size,
  and a cache would only hide an N+1.
- No rate limiting beyond the login lockout in step 05.