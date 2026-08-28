---
description: Create a spec file and feature branch for the next build step
argument-hint: "Step number and feature name e.g. 3 detection checks"
allowed-tools: Read, Write, Glob, Grep, Bash(git:*)
---

You are a senior developer building the **MPLADS Risk Engine** — an
anomaly-detection and monitoring platform for the Members of Parliament
Local Area Development Scheme (Smart India Hackathon, PS 26102).

Always follow the rules in CLAUDE.md.

User input: $ARGUMENTS

## Step 1 — Check working directory is clean

Run `git status` and check for uncommitted, unstaged, or untracked files.
If any exist, stop immediately and tell the user to commit or stash changes
before proceeding. DO NOT CONTINUE until the working directory is clean.

## Step 2 — Parse the arguments

From $ARGUMENTS extract:

1. `step_number` — zero-padded to 2 digits: 3 → 03, 11 → 11

2. `feature_title` — human readable title in Title Case
   - Example: "Detection Checks" or "Alert Detail Screen"

3. `feature_slug` — git and file safe slug
   - Lowercase, kebab-case
   - Only a-z, 0-9 and -
   - Maximum 40 characters
   - Example: detection-checks, alert-detail

4. `branch_name` — format: `feature/<feature_slug>`
   - Example: `feature/detection-checks`

If you cannot infer these from $ARGUMENTS, ask the user to clarify
before proceeding.

## Step 3 — Check branch name is not taken

Run `git branch` to list existing branches.
If `branch_name` is already taken, append a number:
`feature/detection-checks-01`, `feature/detection-checks-02` etc.

## Step 4 — Switch to main and pull latest

Run:
```
git checkout main
git pull origin main
```

If there is no remote yet, skip the pull and continue.

## Step 5 — Create and switch to the feature branch

Run:
```
git checkout -b <branch_name>
```

## Step 6 — Research the codebase

Read these files before writing the spec:

- `CLAUDE.md` — roadmap, conventions, database schema, scoring rules
- `backend/db.py` — schema definition and query helpers
- `backend/checks.py` — existing detection checks and point allocation
- `backend/main.py` — existing API endpoints
- `frontend/src/api.js` — how the frontend calls the API
- `frontend/src/` — existing components and CSS variables
- All files in `.claude/specs/` — avoid duplicating existing specs

Only read the files that already exist. If a file is missing because
this step is what creates it, note that in the spec.

Check the roadmap table in `CLAUDE.md` to confirm the requested step is
not already marked complete. If it is, warn the user and stop.

## Step 7 — Write the spec

Generate a spec document with this exact structure:

---

# Spec: <feature_title>

## Overview
One paragraph describing what this feature does and why it exists at
this stage of the MPLADS Risk Engine roadmap.

## Depends on
Which previous steps must be complete before this one can start.

## API endpoints
Every new or changed endpoint:
- `METHOD /path` — description — what it returns — which role uses it

If no endpoints change: state "No API changes".

## Database changes
Any new tables, columns, indexes, or constraints.
Always verify against `backend/db.py` before writing this.
If none: state "No database changes".

## Detection logic
Only for steps that add or change a check. State:
- The rule in plain words
- The exact formula or threshold
- Maximum points it may contribute to `risk_score`
- The reason string it writes into the alert

If this step adds no detection logic: state "No detection logic".

## Frontend
- **Create:** new components with their path under `frontend/src/`
- **Modify:** existing components and what changes

If this is backend-only: state "No frontend changes".

## Files to change
Every file that will be modified.

## Files to create
Every new file that will be created.

## New dependencies
Any new pip or npm packages, with the reason each is needed.
If none: state "No new dependencies".

## Rules for implementation
Specific constraints Claude must follow. Always include:

- **No ORM.** Raw `sqlite3` only — no SQLAlchemy, no Prisma.
- **Parameterised queries only.** Never build SQL with f-strings.
- **No ML libraries in the prototype.** Detection is pure statistics
  and rules — median, IQR, date arithmetic, if/else. No scikit-learn,
  no model files, no LLM calls in the scoring path.
- **Every flag must be explainable.** A check that cannot produce a
  human-readable reason string is not allowed to add points.
- **Wording.** Never output the words "fraud", "scam", or "corrupt"
  in code, UI copy, or comments. Use "flagged", "needs verification",
  "risk indicator".
- **Never rank or score Members of Parliament.** Score works and
  transactions only.
- **CSS variables only** — never hardcode hex values in components.
  All colours come from `frontend/src/theme.css`.
- **Scoring is capped.** No single check may exceed the point cap
  defined in CLAUDE.md, and `risk_score` is clamped to 0–100.
- **Determinism.** Running the checks twice on the same data must
  produce identical scores.

Add any step-specific rules below those.

## Definition of done
A specific testable checklist. Each item must be verifiable by running
the app or a command. Include at least one item that proves the
detection still works against planted anomalies where relevant, e.g.
`python backend/evaluate.py` still reports recall above the current
baseline.

---

## Step 8 — Save the spec

Save to: `.claude/specs/<step_number>-<feature_slug>.md`

## Step 9 — Report to the user

Print a short summary in this exact format:
```
Branch:    <branch_name>
Spec file: .claude/specs/<step_number>-<feature_slug>.md
Title:     <feature_title>
```

Then tell the user:
"Review the spec at `.claude/specs/<step_number>-<feature_slug>.md`
then enter Plan Mode with Shift+Tab twice to begin implementation."

Do not print the full spec in chat unless explicitly asked.