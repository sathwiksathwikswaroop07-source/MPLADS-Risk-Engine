# Frontend — MPLADS Risk Engine

React (Vite), plain JS, plain CSS. Talks to the FastAPI backend under `/api`.

```bash
npm install
npm run dev      # port 5173; expects the backend on port 8000
npm run build    # emits dist/, which the backend serves in deployment
```

The API base is `VITE_API_BASE`, defaulting to `/api` — set in `src/api.js`.

## Three portals, two routers

Five roles, three home screens, grouped by **what a role can do** — never by
seniority.

| Portal | Roles | Why together |
|---|---|---|
| `/citizen` | citizen | Never sees a score |
| `/officer` | district_officer, state_officer | Identical permissions; only scope differs, and scope comes from the token |
| `/oversight` | mp, ministry | See scores, cannot act |

District and state officers match on every row of the permission matrix, so
they share a page — the state officer's extra MP-level and district-level
alerts are the same worklist holding more subject types.

**Do not add a third router to match the third portal.** The `/citizen` split
exists so that "this code cannot leak a risk score" is provable by the absence
of any code path selecting one. MPs and the Ministry legitimately see scores;
their restriction is on writes, and the API enforces it with a 403.

Route guards only stop a role seeing a page it would find broken. They are
**not** the access control — every API call is checked server-side. Never let a
frontend redirect be the reason data is safe.

## Two rules that are easy to break

**No `fetch()` inside a component.** Every call lives in `src/api.js`, which
attaches the bearer token and clears the session on a 401.

**No colour literal outside `theme.css`.** Components use tokens only:

```
--bg --surface --surface-2 --border
--text --text-muted --text-faint
--accent --accent-soft
--sev-critical --sev-high --sev-medium (+ -bg variants)
--ok --ok-bg --radius --shadow
```

Light on `:root`, dark under both `@media (prefers-color-scheme: dark)` and
`[data-theme="dark"]`. Verify with:

```bash
grep -rnE '#[0-9a-fA-F]{3,8}' src --include='*.css' --include='*.jsx' \
  | grep -v theme.css        # must be empty
```

## Layout

```
src/
  main.jsx          root render
  App.jsx           routes and role guards
  auth.jsx          AuthProvider, PORTAL map, ACTOR_ROLES
  api.js            every fetch call
  format.js         rupees, dates, percentages
  Login.jsx         one login for every role, redirects by role
  theme.css         the only file with colour literals
  components/       Layout, ReasonList, SeverityBadge, loading/empty states
  officer/          Worklist, AlertDetail, ActionBar, panels
  citizen/          Works, WorkDetail, WorkCard, ComplaintForm
```

## Display rules

- The alert list is the officer portal's **home screen**, not a tab.
- **A score is never shown without its reasons** — not in a table cell, not in
  a tooltip. `ReasonList` is the only component that renders a total, and it
  returns `null` when there are no reasons, so a bare number cannot appear.
- Loading and empty states on every page; the two list pages distinguish
  "your filter matched nothing" from "you have nothing to do".
- Citizens see cost, dates, status, contractor, photographs and location — and
  delay stated plainly as arithmetic. Never a score, never a severity.
- Contractor names are public record. **Never show one beside a risk score on
  a public page.**
- Prefer a persistent priority banner over a modal. Modals get dismissed
  reflexively and block the task the officer came to do.
