# Spec: Live camera capture and citizen rating

## Overview

Two additions to the citizen portal, plus the officer action that makes the
first of them matter:

1. A citizen filing a report can capture a photograph with their device
   camera, optionally tagged with the coordinates they consent to share.
2. A citizen can rate a completed work 1-5.
3. An officer can **verify** a citizen's report — which, until this step, no
   endpoint anywhere could do.

Written after implementation, to record what was built and the three things
the work uncovered.

## Depends on

Steps 01-08 and 10. Adds one table and five endpoints. Changes no scoring
logic: `checks.py`, `evaluate.py` and `generate_data.py` are untouched, and
the accuracy figures are identical before and after.

## API endpoints

| Method | Path | Who |
|---|---|---|
| POST | `/api/citizen/works/{id}/complaint` | citizen — now **multipart**, optional photo |
| GET | `/api/citizen/complaints/{id}/photo` | citizen, scoped |
| POST | `/api/citizen/works/{id}/rating` | citizen, completed works only |
| GET | `/api/officer/complaints/{id}/photo` | officer and oversight, scoped |
| POST | `/api/officer/complaints/{id}/verify` | district and state officers only |

## Database changes

One new table, `ratings` — `rating_id · work_id · user_id · stars · comment ·
created_at`, `UNIQUE(work_id, user_id)`, `CHECK(stars BETWEEN 1 AND 5)`.

**Nothing else changed.** `complaints.photo_path`, `lat` and `lon` already
existed and were written by nothing — the API hardcoded `photo_path` to NULL
and the frontend never sent coordinates. The camera half needed no migration,
only a write path.

## Detection logic

No new checks, no changed thresholds, no new points.

The one score consequence is deliberate and indirect: verifying a complaint
sets `verified = 1`, and C6 counts distinct verified reporters, so a verified
report can award up to 15 points at the next scoring run. That is C6 working
as designed — it was simply unreachable before.

## Files to change

- `backend/models.py` — `Rating`
- `backend/main.py` — multipart complaint, two photo routes, rating route,
  verify route, `_rating_summary`
- `backend/config.py` — upload limits and allowed formats
- `requirements.txt` — Pillow
- `frontend/src/api.js` — FormData branch in `request()`, four new calls
- `frontend/src/citizen/ComplaintForm.jsx`, `WorkDetail.jsx`
- `frontend/src/officer/panels.jsx`, `AlertDetail.jsx`
- `frontend/src/app.css`, `.gitignore`, `CLAUDE.md`

## Files to create

- `backend/uploads.py`
- `frontend/src/citizen/PhotoCapture.jsx`, `RatingWidget.jsx`

## New dependencies

`Pillow==12.3.0`. Justified against `requirements.txt`'s "deliberately absent"
policy: it re-encodes every upload, which is what **strips the EXIF**. The
alternative is trusting the client to have removed metadata, or storing it.

`python-multipart` was already pinned for the unbuilt step 11, so parsing
needed nothing new.

## Rules for implementation

- **A citizen photograph is stored against the complaint and never as an
  `evidence` row.** This is the load-bearing rule — see below.
- **Re-encode every upload.** Never write client bytes to disk. Sniff the
  format from the leading bytes; the filename and content-type are
  attacker-controlled.
- **Serve photographs through a scoped route, never a `StaticFiles` mount.**
  A mount would make every photograph world-readable by URL and bypass
  `scope_filter`.
- Apply the `resolve()` + `is_relative_to` guard to any path that came from a
  database column, exactly as `serve_spa` does.
- Out of scope is **404**, never 403, on every new route.
- The photograph is optional throughout. A report with no photograph must
  behave exactly as it did before.
- `created_at` keeps using `REFERENCE_DATE`. No wall clock.

## What the work uncovered

**1. Nothing could verify a complaint.** CLAUDE.md's role matrix lists "Verify
a complaint" as a district and state officer action, and the officer alert
page already *displayed* each report's verified flag — but no endpoint
anywhere wrote `complaints.verified`. Since C6 counts only verified rows, a
report filed through the API could never affect anything at all. The citizen
side of the system was a write-only surface. Adding the verify action is what
turns a photograph into something an officer can act on.

**2. Citizen photographs must not become evidence rows.** `evidence` is
*official* proof and its absence is the signal: `checks.py` awards 15 points
for a completed work with zero evidence rows. Had citizen uploads been
inserted there, **a citizen photographing a road would have cleared the
ghost-asset flag on a work that was never built.** Worse, C7's reused-photo
self-join carries no `kind` or provenance filter and awards 20 points — its
largest single component — so two citizens photographing the same landmark
for two different works would have manufactured a false positive.

Note also that `evidence.photo_hash` is not a content hash: it is
`sha256(f"{work_id}|{kind}")`, unique by construction. A real content hash in
the same column would make the self-join compare two different things.

**3. Uploads are ephemeral in deployment, and the app must say so.** Render's
free tier has no persistent disk — the reason `frontend/dist` and
`mplads.db` are committed in the first place. Photographs written to
`uploads/` do not survive a restart. Rather than pretend otherwise, a missing
file is treated as an ordinary 404 with "no longer available", the UI renders
it as a plain line rather than an error, and the README states that a
deployment needs object storage.

## The geolocation reversal

`ComplaintForm.jsx` previously carried a deliberate decision *not* to request
the browser's location: *"a geolocation prompt on a civic page costs more
trust than the two coordinates are worth."*

On its own that still holds, so the prompt now appears **only when a
photograph is attached**, where the trade changes: together they let an
officer confirm the report came from the site, which is the entire reason the
capture exists. Declining is always allowed and the report still sends.

What the coordinates are not is proof. Browser geolocation is client-asserted
and trivially spoofed. They are an input to an officer's verification, never
a substitute for it, and the UI does not claim otherwise.

## Privacy

`models.py` calls identifying data a liability, and a phone photograph is full
of it — GPS, device serial, timestamps. Every upload is decoded and re-encoded
through a fresh image object, so no EXIF block is carried across. Verified in
testing: a JPEG submitted with Make, Model and DateTime tags is stored with
zero EXIF keys.

The only location retained is the one the citizen ticked a box to send. The
capture is also drawn through a `<canvas>` client-side, which discards EXIF
before the bytes leave the browser — defence in depth, not the guarantee.

Ratings are returned as an average and a count. Who rated what is never
exposed.

## Deferred

**Ratings feed no check, by design.** An unverified public rating driving a
risk score would be exactly the accusation CLAUDE.md says the system is not
entitled to make, and it would be trivially brigadable — `UNIQUE(work_id,
user_id)` raises the cost of that but does not remove it. The rating is
context for a resident reading the page and for the officer deciding whether
to visit. Making it a check would be a scoring-contract change and belongs in
its own step, with a planted label and a recall row.
