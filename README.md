# MPLADS Risk Engine

Anomaly detection and monitoring for the Members of Parliament Local Area
Development Scheme. Smart India Hackathon, problem statement 26102
(MoSPI — Data Informatics & Innovation Division).

Reads MPLADS works data, runs deterministic checks over every work, MP,
district and vendor, produces a 0–100 risk score **with a written reason for
every point awarded**, and shows officers a ranked list of subjects that need
verification — worst first.

### What it is not

**It does not detect fraud.** It flags subjects whose numbers deviate from
comparable ones and from scheme rules, so that a human can verify them. A
costly road may be a hilly road.

**It is not a data-entry system.** eSAKSHI is the system of record. Agencies
and district authorities enter works there as part of their existing workflow;
this platform reads that data, scores it, and pushes alerts back to the same
authorities. It never creates a project record.

Design decisions and the reasoning behind them live in [CLAUDE.md](CLAUDE.md).
The demo script is [DEMO.md](DEMO.md).

---

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cd frontend && npm install && cd ..

cp .env.example .env                # then put a secret in it:
python -c 'import secrets;print(secrets.token_urlsafe(48))'

python -m backend.db                # creates empty mplads.db
python -m backend.generate_data     # fills it, ~4500 works
python -m backend.checks            # scores everything
python -m backend.evaluate          # recall vs planted anomalies

uvicorn backend.main:app --reload --port 8000
cd frontend && npm run dev          # port 5173
```

`generate_data.py` drops and recreates everything and is always safe to re-run.
`checks.py` rebuilds `scores` and `alerts` only. Without a `JWT_SECRET` the app
refuses to start rather than failing later at the first login.

The demo password is `mplads2026`; the login page lists the accounts.

## What you get

| | |
|---|---|
| Works | 4,520 across 53 districts and 10 states |
| Planted anomalies | ~300, labelled as ground truth |
| Alerts | 10 critical, 33 high, 246 medium |
| Recall | **77.5%** of planted anomalies reach an officer |
| False positives | **1.14%** of clean works |
| Precision | **83.0%** |

## How scoring works

Each check returns `{check, points, reason, evidence}`. Points are summed per
subject and clamped to 0–100. **A check that cannot produce a human-readable
reason may not award points**, and a check that cannot run records why — so the
alert page can say "5 of 8 checks ran; the rest need authenticated eSAKSHI
data."

Checks run at four levels and are never mixed. Charging an MP's quota shortfall
to each of their works would flag every work that member ever recommended.

| Level | Check | Max |
|---|---|---|
| work | C1 cost outlier | 35 |
| work | C2 delay / C2b predicted stall | 25 / 8 |
| work | C3 compliance | 15 |
| work | C5 duplicate | 20 |
| work | C6 citizen reports | 15 |
| work | C7 paid without proof of work | 35 |
| mp | C3-MP SC/ST quota floors | 48 |
| district | C4 utilisation against the calendar | 15 |
| vendor | C8 pricing and concentration | 30 |

**Cost is compared against actual peers, never against a constant.** C1 walks a
five-rung peer ladder (work type + terrain + area type + district, widening
until at least 8 comparable works exist) and takes the median. It is
fence-first: a work must clear `Q3 + 1.5·IQR` before any ratio band applies, so
a tightly clustered peer group does not start flagging half of itself. Costs
are deflated to constant prices first.

Severity: 70+ critical, 45–69 high, 25–44 medium. Below 25 a score row is still
written — which is what lets the citizen listing and the officer worklist read
from the same place.

## Accuracy

`python -m backend.evaluate` reports two rates per label:

- **detected** — the checks scored it above zero; the signal was seen at all.
- **alerted** — it reached the threshold and an officer sees it. This is recall.

Both are printed because they differ sharply and reporting only one would
mislead. Several checks cap below the alert threshold on purpose, so a work can
be correctly identified and still need a second signal before it is worth an
officer's trip.

The number is trustworthy because the scoring code cannot see the answers:

```bash
grep -rn "planted" backend/checks.py     # empty
```

`evaluate.py` is the only module permitted to read the ground-truth labels.

## Verification

```bash
python -m backend.generate_data && python -m backend.checks
python -m backend.checks          # run twice -- identical output
python -m backend.evaluate

grep -rn "date.today" backend/                        # empty
grep -rni "fraud\|scam\|corrupt" backend/ frontend/   # empty
grep -rn "SELECT \*" backend/                         # empty
grep -rn "planted" backend/checks.py                  # empty
```

Determinism is a requirement, not a nicety: `REFERENCE_DATE` is pinned, the
generator is seeded, and nothing in `backend/` calls `date.today()`. Scores must
not drift overnight or the recall figure stops matching the app.

The three `datetime.now()` calls in `backend/auth.py` are **correct and must not
be "fixed"** — JWT expiry, `last_login_at` and audit timestamps are real
wall-clock events. Nothing scored reads them.

## Architecture

| Layer | Choice |
|---|---|
| Database | SQLite, committed to git so the team shares one dataset |
| ORM | SQLAlchemy 2.x for schema, CRUD, auth |
| Analytics | `text()` with bound parameters for peer-group queries |
| Backend | FastAPI + uvicorn, Python 3.11+ |
| Auth | JWT (PyJWT), no session table |
| Frontend | React (Vite), plain JS, Recharts |

```
backend/
  config.py         REFERENCE_DATE, thresholds, point caps
  models.py         16 SQLAlchemy models
  generate_data.py  dummy data + planted anomalies + demo users
  checks.py         the checks and scoring
  auth.py           JWT, login, scope enforcement
  evaluate.py       recall against planted anomalies
  main.py           FastAPI, two routers
frontend/src/
  citizen/          public portal, never sees a score
  officer/          worklist: district + state officer
  oversight/        read-only: mp + ministry
```

**Two routers, three portals.** `/citizen/*` is separate so that "this router
cannot leak a risk score" is provable by the *absence of code* rather than by a
filter someone might forget. Scope comes from the signed token and is applied in
one shared dependency — never from a query parameter, never in the frontend.

## Status

| Step | Feature | |
|---|---|---|
| 01–08 | Schema, data, checks, API, auth, worklist, evidence, evaluation | done |
| 09 | Ministry / State dashboards | not built |
| 10 | Citizen portal | done |
| 11 | CSV / Excel upload | not built |
| 12 | Demo seed data and polish | done |
| 13 | Camera capture, citizen rating, complaint verification | done |

Steps 09 and 11 are genuinely not built. `/oversight` currently reuses the
officer worklist with the action buttons removed.

**Citizen photo uploads are not persistent in deployment.** Render's free tier
has no disk that survives a restart — the same reason `frontend/dist` and
`mplads.db` are committed — so photographs written to `uploads/` are lost on
redeploy and the app returns an ordinary 404 for them. A real deployment writes
to object storage instead. Every upload is re-encoded on arrival, which strips
its EXIF: a phone photograph carries GPS, a device serial and timestamps, and
the only location stored is the one the citizen consented to send.

## Data boundary

The dataset is generated, not scraped. Real district, constituency and MP names
are copied from the **public** eSAKSHI dashboard to make it credible; work-level
payments, progress and evidence are not public, so the prototype demonstrates
the logic on generated data and a deployment would read the Ministry's own.

The authenticated portion of eSAKSHI is never touched. There are no real PANs
or identity data anywhere in this repository.
