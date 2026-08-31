# Spec: JWT Login And Scope Enforcement

## Overview

`backend/auth.py` issues and verifies JSON Web Tokens, authenticates logins
against the seeded users, and owns the single scope filter every scoped route
will depend on from step 04 onward. There is no sessions table.

Written after implementation.

## Depends on

Steps 01 (the `users` table) and 02 (seeded accounts). Independent of the
checks; the API routers in step 04 consume it.

## API endpoints

No endpoints yet — this is the library step 04's routers build on. `db.py`
already provides `get_db` as the FastAPI dependency.

## Database changes

No schema changes. Writes `audit_log` rows for logins and state-changing
actions, and updates `users.last_login_at`.

## Detection logic

No detection logic.

## Frontend

No frontend changes.

## Files to change

None.

## Files to create

- `backend/auth.py`

## New dependencies

- `pyjwt` — token signing and verification

## Rules for implementation

- **`sub` is the user id as a string.** PyJWT rejects an integer subject, and
  the failure surfaces at decode time rather than at issue, which makes it an
  unpleasant one to debug.
- **The signing algorithm is pinned** at verification. Accepting whatever the
  token's own header requests is how `"alg": "none"` downgrades happen.
- **The secret comes from `$JWT_SECRET`, is at least 32 bytes, and never
  appears in the repository.** Missing or short raises rather than falling back
  to a default — a weak secret silently accepted is worse than a crash, because
  the tokens it signs look perfectly valid.
- **The role selector is a filter, never a claim.** `WHERE username = ? AND
  role = ? AND is_active = 1`, then verify the hash.
- **One generic failure message.** Unknown user, wrong role, disabled account
  and bad password all return "Invalid credentials". Distinguishing them hands
  an attacker half the credential.
- **The client never supplies its own scope.** No route may accept
  `?district_id=`; scope comes from the verified token only.
- **The `WHERE` is written once**, in `scope_filter`. A per-route clause is a
  route someone will forget.
- Expiry uses the real clock. That is the one place a wall clock is correct in
  this codebase — a token must stop working in the actual world — while
  everything *scored* still reads `REFERENCE_DATE`.

## The stateless trade-off

A JWT cannot be revoked, so `is_active = 0` does not take effect until the
token expires. The mitigation, exactly as CLAUDE.md specifies: re-check
`is_active` **and** `role` against the database on state-changing actions
(acknowledge / escalate / resolve / snooze), and trust the signature alone on
reads. The worklist reloads on every page view and does not deserve a database
hit; acting on an alert is rare and consequential enough to be worth one query.

Role is re-read alongside `is_active` because a demoted account is as much a
problem as a disabled one.

## `national` means no filter, not a NULL comparison

The ministry user genuinely has `scope_id = NULL`. Filtering on it —
`works.district_id = NULL` — matches zero rows in SQL, so the national
dashboard would come back empty and look like missing data rather than a bug.
`scope_filter` branches on `scope_type` first and returns a `1 = 1` fragment
for national principals.

A scoped role that somehow arrives with no `scope_id` is **denied**, not
defaulted to unfiltered. The failure mode of guessing there is showing someone
the entire country.

## Roles

Only district and state officers may act on alerts (`ALERT_ACTOR_ROLES`, which
already existed in config). Not arbitrary: under the scheme an MP *recommends*
works while the District Authority sanctions, executes and verifies them, so
letting an MP close an alert on their own constituency's work would invert the
accountability the scheme rests on. The Ministry is oversight, not case-work.

## Definition of done

All verified against the seeded database.

- [x] A valid login returns a token whose `sub` is a **string** (`'1'`, not `1`)
- [x] `do.pune` (scope_id 1) and `do.nashik` (scope_id 3) get different scopes,
      seeing 85 and a different set of works respectively
- [x] A citizen selecting `district_officer`, a wrong password and an unknown
      username all fail with the identical message
- [x] Rejected: tampered payload, token signed with another key, expired token,
      and an **`alg: none` downgrade**
- [x] Missing `JWT_SECRET` and a 16-byte secret both raise; 64 bytes is accepted
- [x] Ministry resolves to `1 = 1` and sees all 4,520 works — not zero
- [x] `do.pune` sees 85 works; `so.mh` sees 693 — scope isolation is real
- [x] A revoked user's token still verifies for reads but is refused on a
      state-changing action
- [x] Ministry is refused alert actions; district and state officers are allowed
- [x] Logins append to `audit_log`
- [x] No literal secret anywhere in `backend/`

The end-to-end test arrives with the API in step 04: log in as `do.pune`, paste
their alert URL into `do.nashik`'s session, and get a 403.
