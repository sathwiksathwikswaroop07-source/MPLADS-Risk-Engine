# Steps 06–07 (+10) — Frontend

## Overview

The React app. Three portals, one login, and the two screens the whole
project is judged on: the **officer worklist** and the **alert detail**.

This spec assumes no prior React knowledge and gives working code for
the parts that are genuinely awkward — auth storage, the 401 redirect,
loading states. The rest is plain components.

**Scope of this spec:** Login, the officer worklist (step 06), alert
detail (step 07), and the citizen portal (step 10, in brief). The
Ministry/State dashboards (step 09) need charts and get their own spec —
do not start them until the two screens below are finished.

## Depends on

Step 04 (API) running on `http://localhost:8000`. Check `/docs` loads
before writing any React.

---

## Setup

```bash
npm create vite@latest frontend -- --template react
cd frontend
npm install react-router-dom
npm run dev          # http://localhost:5173
```

Delete what Vite scaffolds: `src/App.css`, `src/assets/`, and everything
inside `src/index.css`. Keep `main.jsx`.

**Plain JavaScript, not TypeScript.** No Redux, no Zustand, no React
Query, no component library. Five screens do not need any of it, and
every dependency is something to explain to a judge.

---

## Files

```
frontend/src/
├── main.jsx                  entry, mounts <App/>
├── App.jsx                   routes only
├── theme.css                 every colour in the project
├── api.js                    every fetch call in the project
├── auth.jsx                  AuthProvider, useAuth, ProtectedRoute
├── useApi.js                 the loading/error/data hook
├── components/
│   ├── SeverityPill.jsx
│   ├── ReasonList.jsx        ← the most important component
│   ├── StateBlock.jsx        loading / error / empty
│   ├── Money.jsx
│   └── Layout.jsx            header + logout
├── Login.jsx
├── officer/
│   ├── AlertList.jsx         step 06 — the home screen
│   └── AlertDetail.jsx       step 07
├── oversight/
│   └── Dashboard.jsx         step 09 — stub for now
└── citizen/
    ├── WorkList.jsx          step 10
    └── WorkDetail.jsx        step 10
```

---

## `theme.css` — every colour lives here

**No hex value may appear in any component.** If you need a colour that
is not here, add a token here first.

```css
:root {
  --bg: #f6f7f9;
  --surface: #ffffff;
  --surface-2: #f0f2f5;
  --border: #d8dce2;

  --text: #1a1d21;
  --text-muted: #5a6472;
  --text-faint: #8b95a3;

  --accent: #1a56b0;
  --accent-soft: #e8f0fb;

  --sev-critical: #a4262c;   --sev-critical-bg: #fdeaea;
  --sev-high:     #b8560f;   --sev-high-bg:     #fdf0e6;
  --sev-medium:   #8a6d0b;   --sev-medium-bg:   #fbf5e0;
  --ok:           #1a7f4b;   --ok-bg:           #e6f5ec;

  --radius: 8px;
  --shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
}

@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #14171a;
    --surface: #1c2024;
    --surface-2: #23282d;
    --border: #333a42;

    --text: #e8eaed;
    --text-muted: #9aa4b0;
    --text-faint: #6b7580;

    --accent: #6ba3f0;
    --accent-soft: #16283f;

    --sev-critical: #f08b8b;   --sev-critical-bg: #3a1f21;
    --sev-high:     #e5a05f;   --sev-high-bg:     #3a2a1a;
    --sev-medium:   #d9c268;   --sev-medium-bg:   #33301c;
    --ok:           #6bc99a;   --ok-bg:           #1a3328;

    --shadow: 0 1px 3px rgba(0, 0, 0, 0.4);
  }
}

:root[data-theme="dark"] { /* same dark values again */ }

* { box-sizing: border-box; }

body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
}

table { border-collapse: collapse; width: 100%; }
th, td { text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--border); }
th { color: var(--text-muted); font-weight: 600; font-size: 13px; }
```

Dark values are repeated under `[data-theme="dark"]` so a manual toggle
wins in both directions. Duplication is correct here — a colour defined
only inside a media query has no value when the query does not match.

---

## `api.js` — every fetch call in the project

**No `fetch()` inside a component, ever.** One file means the token
header, the base URL and the 401 handling exist once.

```js
const BASE = "http://localhost:8000";

export function getToken()  { return sessionStorage.getItem("token"); }
export function clearAuth() { sessionStorage.clear(); }

async function request(path, options = {}) {
  const token = getToken();

  const res = await fetch(BASE + path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  });

  // Token expired or invalid -> back to login, from anywhere in the app.
  if (res.status === 401) {
    clearAuth();
    window.location.href = "/login";
    throw new Error("Session expired");
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${res.status})`);
  }

  return res.status === 204 ? null : res.json();
}

const qs = (params) =>
  new URLSearchParams(
    Object.entries(params || {}).filter(([, v]) => v !== "" && v != null)
  ).toString();

export const api = {
  login: (username, password, role) =>
    request("/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password, role }),
    }),
  me: () => request("/auth/me"),

  alerts:      (params) => request(`/officer/alerts?${qs(params)}`),
  alert:       (id)     => request(`/officer/alerts/${id}`),
  patchAlert:  (id, body) =>
    request(`/officer/alerts/${id}`, { method: "PATCH", body: JSON.stringify(body) }),

  citizenWorks: (params) => request(`/citizen/works?${qs(params)}`),
  citizenWork:  (id)     => request(`/citizen/works/${id}`),
  fileComplaint: (workId, body) =>
    request(`/citizen/works/${workId}/complaints`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
};
```

The 401 branch is the piece a first-timer always misses. Without it, a
token expiring after 12 hours leaves the app showing empty tables with
no explanation.

The `qs` helper strips empty filter values, so an unset dropdown does
not send `severity=` and get rejected as invalid.

---

## `auth.jsx` — who is logged in

```jsx
import { createContext, useContext, useState } from "react";
import { Navigate } from "react-router-dom";
import { api, clearAuth } from "./api";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    const raw = sessionStorage.getItem("user");
    return raw ? JSON.parse(raw) : null;
  });

  async function login(username, password, role) {
    const data = await api.login(username, password, role);
    sessionStorage.setItem("token", data.token);
    sessionStorage.setItem("user", JSON.stringify(data.user));
    setUser(data.user);
    return data.user;
  }

  function logout() {
    clearAuth();
    setUser(null);
  }

  return (
    <AuthContext.Provider value={{ user, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);

export function ProtectedRoute({ roles, children }) {
  const { user } = useAuth();
  if (!user) return <Navigate to="/login" replace />;
  if (roles && !roles.includes(user.role)) return <Navigate to={portalFor(user.role)} replace />;
  return children;
}

export const PORTAL = {
  citizen: "/citizen",
  district_officer: "/officer",
  state_officer: "/officer",
  mp: "/oversight",
  ministry: "/oversight",
};

export const portalFor = (role) => PORTAL[role] || "/login";
```

`sessionStorage`, not `localStorage` — the token dies when the tab
closes, which suits a 12-hour session and an officer on a shared desk.

Reading the initial state with a function (`useState(() => …)`) means a
page refresh restores the session instead of bouncing to login.

**`ProtectedRoute` is convenience, not security.** It stops an MP seeing
a broken officer page. The actual enforcement is the API returning 403 —
if you ever find yourself relying on the guard to keep data safe, the
backend is wrong.

---

## `useApi.js` — the three states

Every screen that loads data has three possible states, and all three
must be visible. A blank page while loading looks identical to a blank
page after an error.

```js
import { useState, useEffect } from "react";

export function useApi(fn, deps = []) {
  const [state, setState] = useState({ loading: true, error: null, data: null });

  useEffect(() => {
    let cancelled = false;
    setState({ loading: true, error: null, data: null });
    fn()
      .then((data)  => { if (!cancelled) setState({ loading: false, error: null, data }); })
      .catch((err)  => { if (!cancelled) setState({ loading: false, error: err.message, data: null }); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return state;
}
```

The `cancelled` flag matters. Change a filter twice quickly and two
requests are in flight; without it the slower one can land last and
overwrite the newer results with stale data. It is a race a beginner
will not see in testing and a judge might see live.

Usage:

```jsx
const { loading, error, data } = useApi(() => api.alerts({ severity }), [severity]);
if (loading || error || !data?.items.length)
  return <StateBlock loading={loading} error={error} empty="No alerts in this district." />;
```

---

## `App.jsx` — routes only

```jsx
export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />

          <Route path="/officer" element={
            <ProtectedRoute roles={["district_officer", "state_officer"]}>
              <Layout><AlertList /></Layout>
            </ProtectedRoute>} />
          <Route path="/officer/alerts/:id" element={
            <ProtectedRoute roles={["district_officer", "state_officer"]}>
              <Layout><AlertDetail /></Layout>
            </ProtectedRoute>} />

          <Route path="/oversight" element={
            <ProtectedRoute roles={["mp", "ministry"]}>
              <Layout><Dashboard /></Layout>
            </ProtectedRoute>} />

          <Route path="/citizen" element={
            <ProtectedRoute roles={["citizen"]}>
              <Layout><WorkList /></Layout>
            </ProtectedRoute>} />
          <Route path="/citizen/works/:id" element={
            <ProtectedRoute roles={["citizen"]}>
              <Layout><WorkDetail /></Layout>
            </ProtectedRoute>} />

          <Route path="*" element={<RootRedirect />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
```

`RootRedirect` sends a logged-in user to `portalFor(user.role)` and
everyone else to `/login`.

---

## Screen: Login

One page for all five roles.

**Fields:** username, password, and a **role dropdown**.

The dropdown is *not* the user claiming a role. The server uses it as an
extra `WHERE role = ?` filter — pick the wrong one and no row matches,
so login fails. Worth knowing when you demo it: selecting "District
Officer" as a citizen does not grant anything, it just fails.

On success, `login()` stores the token and you
`navigate(portalFor(user.role))`.

On failure, show the server's `detail` verbatim — it is deliberately the
same message for every kind of failure. Do not invent a friendlier
"user not found", which would leak which usernames exist.

**Put the demo accounts on the page** in a small muted box:

```
do.pune · do.nashik · so.maharashtra · mp.pune · ministry · citizen.pune
password: mplads2026
```

Under demo pressure you will not want to be recalling usernames, and it
shows a judge the roles exist without you narrating them.

---

## Screen: Officer alert list (step 06) ★

**This is the home screen.** Not a tab, not a subpage. `/officer` lands
here.

### Layout, top to bottom

1. **Header** — "Alerts needing verification", the count, the officer's
   name, scope name ("Pune district"), logout.
2. **Priority banner** — the single highest-scoring open alert, as a
   persistent strip, not a modal. Shows severity, score, subject, top
   reason, and a "Review" button.
3. **Filters** — severity, status, subject type. Plain `<select>`s.
4. **The table.**
5. **Pagination** — prev/next and "showing 1–50 of 312".

### Why a banner, not a popup

`CLAUDE.md` calls this out and it is worth understanding. A modal on
page load gets dismissed reflexively — the officer's hand is already
moving to close it before they have read it — and it blocks the task
they came to do. A banner stays visible, costs nothing, and does not
train the user to click Dismiss.

If you do use a modal: once per day, top three together, and every
button a real action. Never a bare "Dismiss".

### The table

| Column | Notes |
|---|---|
| Severity | `<SeverityPill>` — coloured chip |
| Score | The number, bold |
| Subject | `subject_label` |
| District | |
| Why | `top_reason`, one line, truncated with `text-overflow: ellipsis` |
| Age | days since `created_at` |

**Row click → `/officer/alerts/:id`.** Make the whole row clickable and
give it `cursor: pointer` and a hover background.

**The score column never appears without the "Why" column.** A bare
number is never displayed alone — not here, not in a tooltip. That rule
is the project's entire explainability story, and a table of naked
numbers quietly discards it.

Sorted by score descending — the API already does this. Do not re-sort
in JavaScript.

### Empty state

"No alerts in this district" is a **real state, not a bug**. It is what
`do.nashik` may legitimately see. Render it as a calm message, not a
spinner that never stops.

---

## Screen: Alert detail (step 07) ★

**The screen the project is judged on.** If a judge cannot understand
why this work scored 78 by reading this page, nothing else matters.

### Layout

**Header** — back link, subject label, severity pill, the score as a
large number, and the district.

**`<ReasonList>`** — immediately below the header. Not in a tab, not
below the fold. This is the reason the page exists.

**Coverage line** — from `checks_run` and `checks_skipped`:

> 5 of 9 checks ran. Payment-progress and evidence checks require
> authenticated eSAKSHI data.

Small and muted, but present. It tells a judge the system knows what it
needs and degrades honestly instead of pretending a missing input is a
clean result.

**Work facts panel** — cost, quantity and unit, dates, status, progress,
vendor, agency, and **`specification`**. The specification line matters
here specifically: an officer reading *"₹31 lakh above the median"*
alongside *"G+2, 2 lifts"* can judge whether the build explains the gap
before driving to the site.

**Evidence sections** — payments table, progress history, evidence
photos, complaints. Each with its own empty state. *"No evidence
recorded"* is itself a finding, so say it plainly rather than hiding the
section.

**Action bar** — sticky at the bottom: Acknowledge · Escalate · Resolve
· Snooze. Only rendered when `user.role` is `district_officer` or
`state_officer`. The Oversight portal reuses this page without it.

### `<ReasonList>` — the most important component

One card per entry in `reasons`:

```
┌────────────────────────────────────────────────────┐
│ C1  Cost outlier                          31 pts   │
│                                                    │
│ Cost per km is ₹8.4 lakh at 2026 prices (₹7.2 lakh │
│ as sanctioned in 2023), against a median of ₹2.0   │
│ lakh for 47 comparable works. 4.2×.                │
│                                                    │
│ this work ████████████████████████ ₹8.4 L          │
│ median     ██████                  ₹2.0 L          │
│ fence      ████████████            ₹4.3 L          │
│                                                    │
│ Compared against 47 works · same type, terrain     │
│ and area type                                      │
└────────────────────────────────────────────────────┘
```

The bars are three `<div>`s with percentage widths. No chart library —
Recharts for three bars is a dependency you would have to justify.

**Render only what is in `evidence`.** Never compute a ratio, a median
or a percentage in React. If a number is missing from `evidence`, the
fix is in `checks.py`, not here. The moment the frontend starts
calculating, the page can disagree with the score, and then neither is
trustworthy.

Cards ordered highest points first — the API already sorts them.

### The Resolve dialog

Resolving requires a **verdict** and a **note of at least 20
characters**. The API returns 422 without them; enforce it in the form
too so the officer gets an immediate message rather than a failed
request.

Verdict options: substantiated · not substantiated · could not verify.

Do not offer a bare "Dismiss" anywhere. Snooze exists for "not now" and
the alert comes back. This is a deliberate design position — an officer
must not be able to clear a ₹31 lakh alert with one click — and it is
worth saying out loud in the demo.

---

## Screen: Citizen portal (step 10)

Lower priority. Build after the two officer screens work.

`WorkList` — works in the citizen's area: description, type, cost,
status, and an **overdue badge** when `days_overdue` is set.

`WorkDetail` — the same facts plus photos, map location, contractor
name, and a "Report a problem" form.

### What a citizen must never see

`total_score`, `severity`, any reason, any alert. The API does not send
them, and the citizen components must not have a code path expecting
them. If you find yourself writing `{work.total_score && …}` in a
citizen component, stop — that field does not exist in that response and
writing the guard suggests you think it might.

**Delay is a fact, not a score.** *"Expected 16 Jan 2026, still in
progress — 242 days overdue"* is arithmetic on two dates the citizen can
already see. Show it plainly. Hiding it would make the page less honest,
not more careful.

Contractor names are public record and may be shown — and on this page
there is no score to show them beside, which is exactly why the citizen
router has no access to one.

### The complaint form

Text, optional photo, optional location. On success, a confirmation that
says the report will be reviewed — **not** that action will be taken.

A duplicate complaint returns **409**. Catch it and show *"You have
already reported this work"*, not a raw error.

---

## Rules

- **No hex colours in components.** Tokens only.
- **No `fetch()` outside `api.js`.**
- **Loading, error and empty states on every screen that loads data.**
- **Never display a score without its reasons.**
- **Never compute a number the API did not send.**
- No scope filtering in React. Data that reached the browser already
  left the server.
- No `localStorage` — `sessionStorage` only.
- Keep components under ~150 lines. Split when longer.
- Every clickable thing is a `<button>` or `<a>`, not a `<div onClick>`
  — keyboard users and screen readers depend on it, and it costs
  nothing.

---

## Build order

Do not deviate. Each step should end with something visible working.

| # | Build | Done when |
|---|---|---|
| 1 | `theme.css`, `api.js`, `auth.jsx`, `useApi.js`, `Layout` | Nothing renders yet — plumbing |
| 2 | `Login.jsx` | You can log in as `do.pune` and land on an empty `/officer` |
| 3 | `AlertList.jsx` — table only | Real alerts from your database appear |
| 4 | `AlertDetail.jsx` — header + `<ReasonList>` | You can read why the top alert scored what it did |
| 5 | Action bar + resolve dialog | You can resolve an alert and see it change |
| 6 | Filters, pagination, priority banner | The worklist feels finished |
| 7 | Citizen portal | |
| 8 | Oversight dashboard (step 09, separate spec) | |

**Steps 2–4 are the demo.** Everything after is improvement. If you run
out of time at step 5, you still have a working, defensible
demonstration.

---

## Definition of done

```bash
uvicorn backend.main:app --reload --port 8000   # terminal 1
cd frontend && npm run dev                      # terminal 2
```

Auth:

- [ ] Log in as `do.pune` → lands on `/officer`
- [ ] Log in as `mp.pune` → lands on `/oversight`, not `/officer`
- [ ] `mp.pune` typing `/officer` in the URL bar is redirected away
- [ ] Wrong password shows the server's message, not a blank screen
- [ ] Refreshing the page keeps you logged in
- [ ] Logout returns to `/login` and `/officer` is no longer reachable
- [ ] Hand-edit the token in sessionStorage → next request returns to login

The two screens:

- [ ] The worklist shows real alerts, worst first
- [ ] Every row showing a score also shows a reason
- [ ] `do.nashik` sees a different list from `do.pune`
- [ ] Filters change the list; clearing them restores it
- [ ] Changing a filter twice rapidly does not show stale results
- [ ] Alert detail renders every reason with its points and evidence
- [ ] The coverage line ("5 of 9 checks ran…") is visible
- [ ] Resolving without a note is blocked in the form, not just by the API
- [ ] After resolving, the alert's status is visibly changed
- [ ] `specification` appears on the detail page

Presentation:

- [ ] No hex colour anywhere: `grep -rn "#[0-9a-fA-F]\{3,6\}" src/ --include=*.jsx` is empty
- [ ] Dark mode works — toggle your OS theme and check every screen
- [ ] Every screen has loading, error and empty states — test by stopping the API mid-session
- [ ] No console errors on any screen
- [ ] Nothing overflows horizontally at 1280px

Then the one that decides it: **open the top alert and explain the score
out loud using only what is on screen.** If you cannot, the page is not
done — and no amount of styling fixes it.