# Steps 06 & 07 — Officer worklist and alert detail

## Overview

The React app for the two roadmap steps the API supports in full. No
backend change was needed or made.

Five roles, three portals, two routers — but only **two page
components**. The worklist and the alert detail serve both the Officer
portal and Oversight; `can_act` from the API is the only difference, and
it arrives on every response. A parallel component tree for MPs and the
Ministry would duplicate code without adding a guarantee.

```
frontend/src/
├── api.js            every fetch in the application
├── auth.jsx          AuthContext, PORTAL map, ACTOR_ROLES
├── format.js         rupees / dates / titles -- presentation only
├── theme.css         the only file containing a colour
├── app.css           layout, var() references only
├── Login.jsx         one login, redirect by role
├── App.jsx           routes and role guards
├── components/
│   ├── ReasonList.jsx    THE score component
│   ├── SeverityBadge.jsx band label, never rendered alone
│   ├── States.jsx        Loading / Empty / ErrorBox
│   └── Layout.jsx        shell, user chip, sign out
└── officer/
    ├── Worklist.jsx      home screen, not a tab
    ├── AlertRow.jsx      one row
    ├── PriorityBanner.jsx persistent, never a modal
    ├── AlertDetail.jsx   the evidence pack
    ├── ActionBar.jsx     acknowledge / escalate / resolve / snooze
    └── panels.jsx        subject + evidence tables, breakdown, coverage
```

## The score guarantee, made structural

CLAUDE.md requires that a score is never displayed without its reasons.
That is enforced by construction rather than by review:

`ReasonList` is the **only** component that prints `total_score`. It
takes `reasons` as a required prop and returns `null` when the list is
empty. No other component accepts a score at all, so a developer cannot
render one without supplying the sentences — there is no API to do it.

Verified by rendering `<ReasonList score={99} reasons={[]} />`, which
produces the empty string.

The one other place a number appears is the points breakdown total, and
it sits directly beneath the itemised per-check points that produce it.

## The evidence bag is rendered generically

Each check carries a different evidence shape — C1 has
`median`/`ratio`/`peer_count`, C7 has `payment_ratio`/`stale_days`,
C5 has `other_work_id`/`gap_days`. Eight checks appear in the data
(C1, C2, C3, C3-MP, C5, C6, C7, C8).

A typed view per check would mean eight components to keep in step with
`checks.py`. Instead `EvidenceBag` iterates `Object.entries`, with a
label map for known keys and a readable fallback for the rest. Adding a
check to the backend needs no frontend change.

## What the API actually does

Read from `backend/main.py`, not from `07-main.md`, which describes an
earlier shape.

| Behaviour | Consequence |
|---|---|
| Out-of-scope alert → **404**, not 403 | The response must not confirm the row exists. "Not found" and "not yours" are one message. |
| `/officer/alerts` has `limit`, no `offset` | The worklist is top-N. No pager is offered, because one would silently repeat page 1. |
| Filters unvalidated; bad `subject_type` → 500 | Fixed dropdowns only, never free text. |
| `reasons`, `checks_run`, `checks_skipped` pre-parsed | No `JSON.parse` in any component. |
| `snooze` discards `note`, returns hardcoded `"open"` | No note field offered; the alert is re-read after every action. |
| `/auth/me` omits `full_name` | The login `user` object is persisted; it is the only source of a display name. |
| CORS allows `:5173` only | `strictPort: true`, so a port fallback fails loudly instead of as an opaque CORS error. |
| `file_path` returned, nothing serves files | Evidence is listed as records. An `<img>` would render broken and imply the photograph is missing when it is only unserved. |

Severity is read from `alert.severity` rather than re-derived from the
score; the local 70/45/25 mapping is a fallback only, so there is one
source of truth. No alert in the current data reaches 70, so `critical`
is not offered as a filter option — it would always return nothing.

## Verification

```bash
uvicorn backend.main:app --reload --port 8000
cd frontend && npm run dev          # must be 5173
```

Confirmed against the running API through the Vite proxy:

| Check | Result |
|---|---|
| `do.pune` worklist | 5 alerts, top 259 @ 45 |
| `do.nashik` worklist | 3 alerts, top 244 @ 45 — a different list |
| `so.mh` worklist | 38, including **2 MP-quota alerts** a DO never sees |
| `ministry.mospi` | 282 across work/mp/vendor, `can_act` false |
| `mp1` | 5 alerts, `can_act` false |
| Nashik reads Pune's alert 259 | **404** |
| `mp1` POSTs acknowledge | **403** |
| `citizen001` GETs `/officer/alerts` | **403** |
| No token | **401** |
| `do.pune` signing in as `mp` | **401** |
| Resolve with a 5-character note | **422** |
| Acknowledge, then re-read | status persists, `assigned_to` set |

Alert 259 scores 45 = C2 delay 25 + C5 duplicate 20, both sentences on
screen with their evidence. That is the "explain it out loud" gate.

```bash
grep -rniE "#[0-9a-f]{3,8}" frontend/src --include="*.jsx" --include="*.js"  # empty
grep -rn "fetch(" frontend/src --include="*.jsx"                            # empty
grep -rniE "fraud|scam|corrupt" frontend/src                                # empty
```

## Correction for the demo script

CLAUDE.md's demo notes say pasting Pune's alert URL into Nashik's
session returns **403**. It returns **404** — deliberate, so the
response does not confirm the alert exists. The access-control point
still lands; the slide should say the alert is hidden, not refused.

## Not built here

| Step | Blocked on |
|---|---|
| 09 dashboards | No aggregate endpoint. Counting client-side is capped at 500 rows and would be quietly wrong. |
| 10 citizen portal | Endpoints exist — this is the cheapest next step, pure frontend. |
| 11 CSV upload | No endpoint of any kind. |
| Evidence photos | No static mount; `file_path` points at files that do not exist. |
