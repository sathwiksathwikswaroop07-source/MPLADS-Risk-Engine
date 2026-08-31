# Step 05 — JWT authentication and scope enforcement

*Revised: password hashing moves from werkzeug to passlib (argon2 primary,
bcrypt fallback). Everything else carried forward.*

## Overview

Everything so far trusts whoever is calling. This step makes the server
decide two questions on every request, from evidence it verifies itself:

1. **Authentication** — who is this? Answered by a signed token issued
   only after a username and password matched a row in `users`.
2. **Authorisation** — what may they do, and *which rows may they see*?
   Answered from claims inside that token, never from anything the
   client sends alongside it.

The second half is what matters for this project. A district officer
must not see another district's alerts, and that must be true because
the SQL cannot return them — not because the React page chose not to
render them.

## Build this before step 04

The roadmap lists API endpoints as 04 and this as 05. Build them the
other way round. Every route in step 04 depends on `get_current_user`
and the scope helper defined here, and retrofitted auth is how one route
gets missed.

## Depends on

- Step 01 — `users` with `role`, `scope_type`, `scope_id`,
  `password_hash`, `is_active`.
- Step 02 — seeded demo accounts. **Their hashes must be passlib
  hashes** — see the migration note below.

---

## Files

```
backend/
├── auth.py         ← NEW: hashing, tokens, dependencies, scope
└── config.py       ← extended
```

`auth.py` imports from `config`, `db`, `models`, `crud`. **Nothing
imports `main`** — the dependency arrow points one way, or you get a
circular import the first time a route needs `get_current_user`.

### Config additions

`config.py` already has `JWT_ALGORITHM`, `JWT_EXPIRY_HOURS`,
`JWT_SECRET_ENV_VAR`, `JWT_MIN_SECRET_BYTES`, `ALERT_ACTOR_ROLES`,
`SUBJECT_ROUTING`. Add:

```python
LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCKOUT_MINUTES = 15
ROLES = ("citizen", "mp", "district_officer", "state_officer", "ministry")
SCOPE_TYPES = ("constituency", "district", "state", "national")

# Argon2id parameters. OWASP-recommended low-memory profile: fast enough
# that a demo login is instant, strong enough to be defensible.
ARGON2_TIME_COST = 2
ARGON2_MEMORY_COST = 19456      # KiB, ~19 MB
ARGON2_PARALLELISM = 1
```

### New dependencies

```bash
pip install "passlib[argon2,bcrypt]" pyjwt
```

`passlib[argon2]` pulls `argon2-cffi`; `passlib[bcrypt]` pulls `bcrypt`.

**Known incompatibility.** passlib 1.7.4 reads
`bcrypt.__about__.__version__`, which bcrypt removed in 4.1. You get a
noisy `error reading bcrypt version` warning at import — hashing still
works. Either pin `bcrypt<4.1` or ignore it. Since argon2 is primary and
bcrypt is only a fallback verifier here, ignoring it is reasonable, but
do not let an unexplained warning surface during a demo.

---

## The one exception to the REFERENCE_DATE rule

`CLAUDE.md` forbids `datetime.now()` anywhere in `backend/` and the DoD
greps for it. **`auth.py` is the single exception, and the grep must be
amended.**

Token expiry is wall-clock time. `REFERENCE_DATE` is 15 September 2026 —
if `exp` derived from it, every token issued today would be either valid
for months or already expired. Neither is authentication.

```python
from datetime import datetime, timedelta, timezone
now = datetime.now(timezone.utc)          # allowed HERE and nowhere else
```

The distinction: `REFERENCE_DATE` pins **the data being analysed** so
scores reproduce. A token lifetime is **an event happening now** and has
nothing to do with the dataset. Update the DoD grep to:

```bash
grep -rn "date.today\|datetime.now" backend/ --exclude=auth.py   # empty
```

Nothing in the scoring path may know what time it is.

---

## Passwords

### One CryptContext, defined once

```python
from passlib.context import CryptContext

pwd_context = CryptContext(
    schemes=["argon2", "bcrypt"],
    deprecated="auto",
    argon2__type="ID",                              # argon2id
    argon2__time_cost=config.ARGON2_TIME_COST,
    argon2__memory_cost=config.ARGON2_MEMORY_COST,
    argon2__parallelism=config.ARGON2_PARALLELISM,
    bcrypt__truncate_error=True,
)

def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)

def verify_password(plain: str, stored: str) -> bool:
    return pwd_context.verify(plain, stored)
```

**argon2id is the default and the only scheme used for new hashes.**
It is memory-hard, which is what makes GPU cracking expensive — bcrypt
is CPU-hard only. `schemes` lists argon2 first, so `pwd_context.hash()`
always produces argon2.

**bcrypt is present as a verifier, not a producer.** `deprecated="auto"`
marks every non-primary scheme deprecated, so a stored bcrypt hash still
verifies but is flagged for rehash. This is the standard passlib
migration pattern and it means an existing bcrypt-hashed account keeps
working if one ever appears.

**`bcrypt__truncate_error=True` is not optional.** bcrypt silently
ignores everything past 72 bytes, so `"…71 chars…A"` and
`"…71 chars…B"` are the same password. Silent truncation in an auth
system is the kind of thing that is invisible until it is a finding.
Raising is correct.

passlib also caps input at 4096 bytes by default, which stops someone
DoS-ing the server by posting a 10 MB password for argon2 to chew on.
Leave that alone.

### Optional but cheap: rehash on login

```python
if pwd_context.needs_update(user.password_hash):
    user.password_hash = hash_password(plain)
```

Costs three lines and upgrades legacy hashes transparently on next
login. Worth having as an answer if asked how you would migrate.

### Rules

- Never log, print, or return a password or a hash. Not in a debug
  print, not in an error body, not in `audit_log.detail`.
- Never compare hashes with `==`. `pwd_context.verify` is constant-time.
- **No password reset, change, or registration endpoint.** Accounts come
  from seed data. A registration form is the fastest way to break
  "roles are provisioned, never self-declared".

### Migration note — the demo hashes must be regenerated

The as-built `generate_data.py` seeded werkzeug scrypt hashes
(`scrypt:32768:8:1$…`). **passlib cannot parse that format**, so every
seeded login would fail.

`generate_data.py` must import `hash_password` from `auth.py` and use
it. Since the work-type split already requires regenerating the
database, this costs nothing extra — but it must not be forgotten, or
step 05's first test fails for a reason that looks like a JWT bug.

Hashing ~40 accounts with argon2 adds two or three seconds to
generation. Acceptable. If the seed count ever grows into the hundreds,
hash one password and reuse the digest for the filler accounts.

---

## The signing secret

Read from the environment, validated at import, never in the repository.

```python
secret = os.environ.get(config.JWT_SECRET_ENV_VAR)
if not secret or len(secret.encode()) < config.JWT_MIN_SECRET_BYTES:
    raise RuntimeError(
        "JWT_SECRET missing or shorter than 32 bytes. Generate one with:\n"
        "  python -c 'import secrets; print(secrets.token_urlsafe(48))'"
    )
```

**Never a default value.** A fallback like
`os.getenv("JWT_SECRET", "dev-secret")` means the day someone forgets
the variable, the app keeps working and signs tokens that anyone who has
read the repository can forge.

Generate with:

```bash
python -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Store in `.env` (already gitignored) or export in the shell. It is a
64-character URL-safe string, 64 bytes, comfortably past the 32-byte
floor.

---

## The token

### Claims

| Claim | Type | Value |
|---|---|---|
| `sub` | **string** | `str(user.user_id)` |
| `role` | string | one of `ROLES` |
| `scope_type` | string | one of `SCOPE_TYPES` |
| `scope_id` | int or null | null only when `scope_type == "national"` |
| `iat` | int | issued at, real UTC |
| `exp` | int | `iat + JWT_EXPIRY_HOURS` (12h) |

**`sub` must be a string.** PyJWT rejects an integer `sub` on decode.
Convert out, `int()` back in. Ten minutes to discover at 2 a.m., one
line to prevent.

Nothing sensitive goes in the payload. **A JWT is signed, not
encrypted** — anyone holding it can base64-decode and read every claim.
No password hash, no email, no full name. `role` and `scope_id` are in
there because we must read them and they are harmless to the holder, who
already knows their own role.

### Decoding — pin the algorithm

```python
jwt.decode(token, secret, algorithms=[config.JWT_ALGORITHM])
```

The `algorithms` list is **mandatory and must be a literal from
config**, never read from the token's own header. A header can claim
`"alg": "none"`, and a decoder that trusts it accepts an unsigned,
freely-edited payload. This is the classic JWT attack and worth being
able to explain in one sentence when a judge asks what stops someone
editing `"role": "ministry"` into their token.

Three failures, distinct in code, identical in response:

| Exception | Response |
|---|---|
| `ExpiredSignatureError` | 401 `"Session expired, please log in again"` |
| `InvalidTokenError` | 401 `"Invalid credentials"` |
| Missing / malformed header | 401 `"Invalid credentials"` |

### Transport

`Authorization: Bearer <token>` via FastAPI's `HTTPBearer`. The frontend
keeps it in `sessionStorage` and attaches it in `api.js` — one place.

The honest tradeoff if asked: an `httpOnly` cookie resists XSS better
but needs CSRF protection alongside. For a prototype on generated data,
Bearer plus a 12-hour expiry is proportionate, and we know what we
traded.

---

## Login

`POST /auth/login` — the only unauthenticated write endpoint.

```json
{ "username": "do.pune", "password": "...", "role": "district_officer" }
```

### Role is a filter, not a claim

The form has a role selector. The server **never trusts it as an
assertion**; it is an extra `WHERE` clause:

```python
stmt = select(User).where(
    User.username == username,
    User.role == role,
    User.is_active == 1,
)
```

A citizen selecting "District Officer" matches no row and login fails.
The role in the issued token comes from `user.role` read out of the
database — **never from the request body**. The dropdown decides which
door you knock on; the database decides whether it opens.

### Sequence

1. Check the lockout counter. If locked → 429.
2. Run the query above.
3. **If no row, hash a dummy password anyway, then fail.** Skipping the
   hash on a missing user makes "no such user" measurably faster than
   "wrong password", and that timing difference enumerates valid
   usernames. Argon2 at 19 MB is slow enough that the gap is obvious
   without this.
4. `verify_password(plain, user.password_hash)`. If false, fail.
5. On failure: increment counter, `write_audit(action="login_failed")`,
   401.
6. On success: reset counter, optionally rehash, `record_login()` to
   stamp `last_login_at`, `write_audit(action="login")`, issue token.

### One error message

Every failure — unknown username, wrong password, wrong role,
deactivated account — returns the same body:

```json
{ "detail": "Invalid credentials" }
```

Never "user not found" versus "wrong password".

### Lockout

`LOGIN_MAX_ATTEMPTS` (5) failures for one username within
`LOGIN_LOCKOUT_MINUTES` (15) → 429. A module-level dict is fine.

State the limitation in a comment: per-process and in-memory, so it
resets on restart and would not survive multiple workers. Production
needs Redis or a `login_attempts` table. Writing the honest limitation
down beats both having no lockout and pretending this one is
production-grade.

### Response

```json
{
  "token": "eyJ...",
  "user": { "user_id": 7, "full_name": "...", "role": "district_officer",
            "scope_type": "district", "scope_id": 3, "scope_name": "Pune" }
}
```

`scope_name` is resolved server-side for display. Never echo the
password or hash.

The frontend uses `role` to pick a portal — see "Three portals" below.

---

## Verifying a request

### `get_current_user` — the base dependency

Decode, validate, return a small frozen object. **Not the ORM `User`** —
a plain immutable value, so no route can accidentally mutate a user row
it merely wanted to read.

```python
@dataclass(frozen=True)
class Principal:
    user_id: int
    role: str
    scope_type: str
    scope_id: int | None
```

**Reads trust the token alone** — no database lookup. The worklist loads
on every page view and does not deserve a query to re-confirm what the
signature already proves.

### `require_active_user` — for state-changing actions

Everything that writes depends on this instead. It does what
`get_current_user` does, then hits the database:

```python
user = session.get(User, principal.user_id)
if user is None or not user.is_active or user.role != principal.role:
    raise HTTPException(401, "Invalid credentials")
```

This closes the gap statelessness opens. A JWT cannot be revoked, so
`is_active = 0` does nothing until expiry — up to 12 hours of a disabled
account still acting. Re-checking on writes means a revoked officer can
still *read* briefly but cannot *resolve an alert*, and reads are the
cheap, harmless half.

The answer if a judge asks about revocation:

> *"The token is signed, so role and scope can't be forged. For
> state-changing actions we re-verify against the database that the
> account is still active, which closes the window where a stateless
> token outlives a revoked user. Production would add a revocation list;
> we chose not to fake one."*

### `require_role(*roles)` — permission

A dependency factory:

```python
Depends(require_role(*config.ALERT_ACTOR_ROLES))   # district + state officer
```

Returns **403** (authenticated, not permitted), distinct from **401**
(not authenticated). Applies the permission matrix: only district and
state officers act on alerts; MPs and Ministry are view-only; citizens
file complaints and nothing else.

---

## Scope enforcement

### Three rules

1. **Never accept a scope identifier from the client.** No
   `?district_id=`, no `{"state_id": …}`, no path parameter naming a
   district. A route that takes one lets an officer type someone else's.
2. **Never write the `WHERE` per route.** Twenty routes each remembering
   to filter is nineteen chances to forget.
3. **Never filter in the frontend.** Data that reached React has already
   left the server.

### One helper

```python
def scope_filter(model, principal) -> ColumnElement[bool]:
    """The WHERE clause restricting `model` to what `principal` may see."""
```

Every scoped query does
`select(Work).where(scope_filter(Work, principal))`. A new model gets
added *here*, and every existing route inherits it.

| Role | scope_type | Works visible |
|---|---|---|
| citizen | constituency | Any — MPLADS work lists are public record |
| mp | constituency | `Work.constituency_id == scope_id` |
| district_officer | district | `Work.district_id == scope_id` |
| state_officer | state | `Work.district_id IN (districts of state)` |
| ministry | national | all |

The state officer clause is a subquery over `districts.state_id`, not a
Python-side list fetched first — one statement, so it cannot go stale
mid-request.

### Scoping alerts crosses the polymorphic boundary

An alert points at a score, and a score's subject may be a work, an MP,
or a district. So "which alerts may this officer see" cannot be answered
without resolving `subject_type` first.

**This is where the polymorphic trap actually bites.** A join on
`subject_id` alone silently matches a district-level score with
`subject_id = 3` against `work_id = 3`, and the officer sees an alert
never meant for them — no error, just a wrong row.

Three explicit branches, unioned. Never one clever join:

```python
work_alerts = (
    select(Alert.alert_id)
    .join(Score, Score.score_id == Alert.score_id)
    .where(Score.subject_type == "work")            # filter BEFORE the join
    .join(Work, Work.work_id == Score.subject_id)
    .where(scope_filter(Work, principal))
)
```

Keep the type filter and the join adjacent, in one helper, so no future
edit separates them.

Routing follows `config.SUBJECT_ROUTING`: work alerts to the District
Officer; MP-quota and district-utilisation alerts to the **State**
Officer only. A district officer must never be the sole recipient of an
alert saying his own district is underspending.

### Out-of-scope resources: 403

Fetching an alert that exists but is outside your scope returns **403**
with a generic body.

404 would hide existence and is the better default in most systems. Here
403 wins on two counts: an officer already knows other districts have
alerts, so nothing secret leaks; and during development a 404 makes a
genuine wrong-id bug indistinguishable from a scope violation. It is
also what makes the demo legible — paste Pune's alert URL into Nashik's
session, get a clear refusal.

---

## Three portals, two routers

**Two routers**, because the split protects *data exposure*, not page
count:

- `/citizen/*` — no code path selects `total_score` or `reasons_json`.
  The guarantee is provable by absence of code.
- `/officer/*` — everything else. Action endpoints carry
  `require_role(*ALERT_ACTOR_ROLES)`.

**Three frontend portals**, grouped by what a role can *do*:

| Portal | Roles | Why together |
|---|---|---|
| `/citizen` | citizen | Never sees a score |
| `/officer` | district_officer, state_officer | Identical permissions; only scope differs |
| `/oversight` | mp, ministry | See scores, cannot act |

Do **not** add a third router to match the third portal. MPs and
Ministry legitimately see scores, so there is no exposure guarantee to
protect; their restriction is on writes, which `require_role` enforces.

After login the frontend redirects on `user.role`:

```js
const PORTAL = {
  citizen: "/citizen", district_officer: "/officer",
  state_officer: "/officer", mp: "/oversight", ministry: "/oversight",
};
```

**That map is convenience, not security.** A route guard bounces an MP
who deep-links `/officer` so they do not see a broken page — but the
enforcement is that every API call still returns 403.

Citizens see cost, dates, status, contractor, photos, location, and the
overdue flag computed from `expected_completion_on`. Never
`total_score`, `severity`, `reasons_json`, `planted_anomaly`, or any
alert. Contractor names are public record and may be shown — **never
beside a risk score** on a public page.

---

## Audit

Through `crud.write_audit`. Log `login`, `login_failed`, `logout`.
Never the password, never the token, never the hash — a token in a log
file is a working credential.

With no session table, the audit log is the only record that a login
happened. That matters more, not less.

---

## Rules for implementation

- `auth.py` imports config, db, models, crud. Nothing imports `main`.
- `JWT_SECRET` read once at import and validated. Never committed, never
  defaulted, never printed.
- `algorithms=[...]` on every `decode`. No exceptions.
- One error message for all login failures.
- **No endpoint anywhere writes `users.role`, `scope_type`, or
  `scope_id`.**
- No password reset or registration route.
- Scope identifiers never appear in a request signature.
- One `CryptContext`, defined once in `auth.py`. `generate_data.py`
  imports `hash_password` from it rather than building its own.

---

## Definition of done

Setup:

```bash
export JWT_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
uvicorn backend.main:app --reload --port 8000
```

Hashing:

- [ ] Seeded hashes start with `$argon2id$` — not `scrypt:`, not `$2b$`
- [ ] `verify_password` returns True for the demo password, False for a wrong one
- [ ] A stored bcrypt hash still verifies (create one by hand) and
      `needs_update` returns True for it
- [ ] A 100-character password raises rather than silently truncating
- [ ] No hash or password appears in any log line or response body

Authentication:

- [ ] Correct username + password + role → 200 with a token
- [ ] Correct password, **wrong role selected** → 401
- [ ] Wrong password → 401, same body as unknown username
- [ ] Unknown username → 401, in comparable time to a wrong password
- [ ] `is_active = 0` → 401
- [ ] 6 rapid failures → 429
- [ ] Missing `JWT_SECRET` → app refuses to start with a clear message
- [ ] A 16-byte secret → refuses to start

Token integrity:

- [ ] Payload contains `sub`, `role`, `scope_type`, `scope_id`, `iat`, `exp`
- [ ] `sub` is a string; decode succeeds
- [ ] Edit one character of the payload → 401
- [ ] Re-sign with a different secret → 401
- [ ] Forge `{"alg": "none"}` with no signature → 401
- [ ] Hand-craft `exp` in the past → 401 with the expiry message
- [ ] No password, hash, or email in the decoded payload

Authorisation:

- [ ] `do.pune` requesting one of Nashik's alerts → **403**
- [ ] `do.pune` listing alerts → only Pune subjects, verified against a direct SQL count
- [ ] `so.maharashtra` sees Pune and Nashik, plus MP-quota and district-utilisation alerts
- [ ] `do.pune` does **not** see MP-quota or district-utilisation alerts
- [ ] `mp.pune` resolving an alert → 403
- [ ] `ministry` resolving an alert → 403
- [ ] `citizen.pune` on any `/officer/*` route → 403
- [ ] A citizen response contains no `total_score`, `severity`, `reasons_json`, `planted_anomaly`
- [ ] Deactivate a user mid-session: reads still work, any write → 401

Grep:

```bash
grep -rn "date.today\|datetime.now" backend/ --exclude=auth.py   # empty
grep -rn "algorithms=" backend/auth.py                           # every decode
grep -rn "getenv.*JWT_SECRET.*," backend/                        # empty, no default
grep -rn "werkzeug" backend/                                     # empty
grep -rn "\.role *=" backend/ --include=*.py | grep -v generate_data   # empty
```

The demo, end to end:

- [ ] Log in as `do.pune`, copy an alert URL. Log out. Log in as
      `do.nashik`, paste it → **403**. Under ten seconds, and access
      control is proven rather than described.

---

## What this step does not do

- No refresh tokens. A 12-hour expiry and re-login is proportionate.
- No revocation list. The write-path re-check is the documented
  mitigation.
- No OAuth, no Aadhaar. Named in the pitch as the production path for
  citizen identity; not built.
- No per-route permission strings. Five roles and one matrix is enough;
  a permission system nobody needs is complexity a judge will ask you to
  justify.