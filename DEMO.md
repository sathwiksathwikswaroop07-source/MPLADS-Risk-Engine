# Demo script

Three minutes. The whole point is that every number on screen has a sentence
next to it explaining how it got there.

**Alert ids are not hardcoded in this file.** They are autoincrement keys that
`checks.py` deletes and rebuilds, so they move whenever the generator changes.
Run `python -m backend.checks` and read the **Demo pointers** block it prints at
the end — those ids are authoritative. The ones quoted below were true at the
last generation.

---

## Before you start

```bash
source .venv/bin/activate
python -m backend.generate_data     # ~4500 works, ~300 planted anomalies
python -m backend.checks            # scores everything, prints the pointers
python -m backend.evaluate          # the closing number

uvicorn backend.main:app --reload --port 8000
cd frontend && npm run dev          # port 5173
```

Expect `checks.py` to report **10 critical, 33 high, 246 medium**. If critical
is 0 you are on old data — re-run the generator.

If uvicorn exits with `JWT_SECRET is not set`, the `.env` is missing:

```bash
cp .env.example .env
python -c 'import secrets;print(secrets.token_urlsafe(48))'   # paste into .env
```

## Accounts

All seeded by `generate_data.py`, all with password `mplads2026`. The login
page has a click-to-fill row for these, so nothing is typed on stage.

| Account | Proves |
|---|---|
| `do.pune` | A district officer's worklist, worst first |
| `do.nashik` | A different scope — and the 404 |
| `so.mh` | MP-level alerts a district officer never sees |
| `ministry.mospi` | Sees scores, cannot act on anything |
| `citizen001` | Facts, never a score |

---

## The run

**1 · Sign in as `do.pune`.** (~20s)

The worklist is the home screen, not a tab. It opens sorted worst-first with a
priority banner on the top alert.

**2 · Open the top alert — currently alert 202, work 3539, score 70.** (~40s)

This is the beat the whole project rests on. Read the reasons out loud:

> Cost per unit is *n*× the median of *m* comparable works · payment has run
> ahead of demonstrated progress · four verified citizen reports.

Three independent checks, three sentences, one score. Say plainly:

> "It is not accusing anyone. It is saying these numbers do not match
> comparable works, so someone should go and look. A costly road may be a
> hilly road."

Point at "compared against *m* comparable works" — that is the peer group, and
it is chosen by the data, never by a constant we picked.

**3 · Copy the URL** `/officer/alerts/202`.

**4 · Sign out. Sign in as `do.nashik`.** (~20s)

Different district, different worklist, its own critical (alert 227, work 3926,
score 75).

**5 · Paste Pune's URL into this session.** (~10s)

**404.** Say:

> "Not 403. The response does not confirm the alert exists — it is hidden, not
> refused. And that is enforced on the server: the scope comes from the signed
> token, never from the URL."

This is ten seconds and it proves access control rather than describing it.

**6 · Sign out. Sign in as `so.mh`.** (~25s)

Same page, more subject types. Filter `subject_type = mp` — an MP quota
shortfall alert. A district officer sees none of these.

> "An MP recommends works; the district authority sanctions and verifies them.
> So a quota alert about a member goes to the state officer, never to the
> member and never only to the district that is the subject of it."

**7 · Sign out. Sign in as `citizen001`.** (~25s)

The same works, publicly. Cost, dates, contractor, photographs, location — and
no score anywhere. That is structural: the citizen router has no code path that
selects one.

But delay is shown plainly — "expected by *date*, still in progress, *n* days
overdue".

> "That is arithmetic on two dates the citizen can already see. Hiding it would
> make the page less honest, not more careful. A risk score is different: it is
> an accusation the system has not earned until an officer verifies it."

**8 · Optional, ten seconds.** Click the `do.pune` chip, then change the role
dropdown to Citizen by hand and submit. **Invalid credentials.**

> "The role selector is a filter, not a claim. The server matches it in the
> WHERE clause; it never trusts it."

**9 · Close on the number.**

```
recall 77.5%   false-positive rate 1.14%   precision 83.0%
```

> "Of the anomalies planted in the data, 77.5% reached an officer. Of every
> clean work, 1.14% was flagged wrongly. And `checks.py` cannot read the
> ground-truth column — `grep -rn planted backend/checks.py` is empty, so the
> engine is not marking its own homework."

Mention the honest gap: several checks cap below the alert threshold on
purpose, so a work can be correctly *detected* and still not raise an alert.
`evaluate.py` prints both columns rather than the flattering one.

---

## If it breaks

| Symptom | Cause |
|---|---|
| `JWT_SECRET is not set` | No `.env` — see above |
| Empty worklist | `checks.py` was not run after `generate_data.py` |
| Alert id 404s for its own officer | Data was regenerated; re-read the Demo pointers block |
| `critical 0` | Old database |

## Not in this demo

Deliberately, so nobody asks:

- **Ministry and State dashboards** (roadmap step 09) — `/oversight` currently
  reuses the worklist with actions removed. The national league tables are not
  built.
- **CSV / Excel upload** (roadmap step 11) — the "how does this connect to
  eSAKSHI?" answer is designed but not built.

Both need new API surface and are their own roadmap steps.
