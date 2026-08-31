# Spec: The API — Two Routers, Three Portals

## Overview

`backend/main.py` is the FastAPI application: one login endpoint, a citizen
router that structurally cannot return a risk score, and an officer router
carrying the worklist, the alert detail with its evidence pack, and the four
act endpoints.

This is the step that makes everything before it reachable. Written after
implementation.

## Depends on

Steps 01–03b (schema, data, scoring) and 05 (`auth.py`). Delivers roadmap
steps 04 and 07.

## API endpoints

| Method | Path | Who | Returns |
|---|---|---|---|
| POST | `/auth/login` | anyone | token + user; role is a filter, not a claim |
| GET | `/auth/me` | any token | the verified principal |
| GET | `/citizen/works` | citizen | scoped works, facts only, with overdue days |
| GET | `/citizen/works/{id}` | citizen | one work, photos, verified-complaint count |
| POST | `/citizen/works/{id}/complaint` | citizen | 201, or 409 on a repeat |
| GET | `/officer/alerts` | officer, mp, ministry | the worklist, worst first |
| GET | `/officer/alerts/{id}` | officer, mp, ministry | alert + evidence pack |
| POST | `/officer/alerts/{id}/acknowledge` | officer only | status change |
| POST | `/officer/alerts/{id}/escalate` | officer only | status change |
| POST | `/officer/alerts/{id}/resolve` | officer only | verdict + note **required** |
| POST | `/officer/alerts/{id}/snooze` | officer only | sets `snoozed_until` |
| GET | `/health` | anyone | liveness, work and alert counts |

## Database changes

No schema changes. `config.SUBJECT_ROUTING` gained its missing `vendor` entry.

## Detection logic

No detection logic. The API serves what `checks.py` computed.

## Frontend

No frontend changes. The React app is steps 06/07/09/10.

## Files to change

- `backend/auth.py` — `alert_scope_clause`, the subject-aware scope resolver
- `backend/config.py` — `SUBJECT_ROUTING["vendor"]`

## Files to create

- `backend/main.py`

## New dependencies

- `httpx` — only for `TestClient`; the app itself adds nothing

## Rules for implementation

- **The citizen router contains no code path that selects the risk score, the
  reasons or any per-check point column.** The guarantee is the absence of
  code, not a filter someone has to remember, and it must survive a grep.
- **Scope is never accepted from the client.** No endpoint takes a district,
  state or constituency id. Every scoped query derives its filter from the
  verified token.
- **The `WHERE` is written once**, in `auth.py`. A per-route clause is a route
  someone forgets.
- **Never join `scores.subject_id` without filtering `subject_type` first.**
  The join and the filter are applied together in `_load_alert`.
- **Out of scope returns 404, not 403** — the response must not confirm that a
  row the caller may not see exists.
- **`verdict` and `resolution_note` are required to resolve**, enforced by the
  request model.
- **Snooze defers; it never deletes.**
- **Every score is returned with its reasons**, so the frontend cannot render a
  bare number.
- **Every state change writes `audit_log`.** There is no session table, so this
  is the only record of who did what.

## Two routers, three portals

`/citizen/*` is separate because *"this router cannot leak a risk score"* has
to be provable structurally. MPs and Ministry users legitimately see scores, so
there is no such guarantee to protect for them — their restriction is on
**writes**, and `require_actor` returns 403 on the four action endpoints. A
third router would add files without adding safety.

## What the work required

**The worklist needed scoping the existing filter could not express.** Alerts
span four subject types, but `auth.scope_filter()` only emits `works`-table
columns — an MP or vendor alert cannot be scoped by it at all. Each type
reaches a principal by its own path: work through `works.district_id`, vendor
through `vendors.district_id`, MP through `mps.state_id`, district directly.

`alert_scope_clause` returns `None` when a principal sees none of a type — a
district officer and MP-quota alerts, say. That is a real answer rather than an
error, and it is what makes the State Officer's extra content fall out of the
design instead of needing a separate page.

**`SUBJECT_ROUTING` had no `vendor` entry.** Vendors arrived in step 03b and
the routing map was never updated. A vendor operates in exactly one district,
so their pricing conduct routes to that District Officer — and unlike the MP
and district rows, this is not an alert about the recipient, so there is no
conflict in routing it locally.

## Definition of done

Every item driven through the API with a test client, not by reading the
database.

- [x] Wrong password, wrong role and unknown user all return **401 with the
      identical message**
- [x] **The demo beat:** `do.pune` sees **5** alerts, `do.nashik` **3**; Pune's
      alert id returns **404 to Nashik and 200 to Pune**
- [x] The Maharashtra State Officer's worklist holds **36 work + 2 MP alerts** —
      the MP-quota rows no district officer sees
- [x] `GET /citizen/works` returns **no** score, reasons or point fields; a grep
      of the citizen router confirms none appear in its code
- [x] A citizen sees "575 days overdue" — arithmetic on stored dates
- [x] Citizen → officer router 403; officer → citizen router 403; no token 401;
      malformed token 401
- [x] Ministry reads all 282 alerts with `can_act=false` and is refused all four
      actions with **403**
- [x] Resolve rejects an empty body, a missing note, a short note and an invalid
      verdict (**422**); a valid one succeeds and writes `audit_log`
- [x] Snooze sets `snoozed_until` and the alert still exists
- [x] A revoked user still reads (200) but is refused a state change (401)
- [x] Alert detail returns reasons, payments, progress history, evidence and
      complaints; every alert in the worklist carries its reasons
- [x] A second complaint on the same work returns **409**; an out-of-scope work
      returns 404
- [x] `checks.py` and `evaluate.py` still produce identical numbers — recall
      74.8%, false positives 1.02%, precision 83.5%
- [x] No `date.today`, no `datetime.now`, no `SELECT *` in `main.py`

Sample evidence pack, work alert 155 (score 47, high): 2 reasons, 2 payments,
4 progress updates, 3 evidence rows, 7 of 7 checks run.
