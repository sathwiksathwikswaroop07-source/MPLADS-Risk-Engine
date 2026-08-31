"""JWT login, token verification and scope enforcement.

There is no sessions table. On login the server signs a token carrying the
user id, role and scope, and every later request derives its query filter from
those claims -- no database lookup on the read path, which matters because the
worklist reloads on every page view.

What that costs, stated honestly: a JWT cannot be revoked. Setting
`is_active = 0` does not take effect until the token expires. The mitigation
is to re-check the account on state-changing actions only (see
`require_active_actor`), trusting the signature alone on reads. Production
would add a revocation list.

Two rules run through this module:

* **The client never supplies its own scope.** Role and scope come from the
  verified token, never from a query parameter. A route accepting
  `?district_id=` lets an officer read someone else's district.
* **The filter is written once.** Every scoped query goes through
  `scope_filter`, because a per-route WHERE clause is a route someone will
  forget.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
from sqlalchemy import text
from werkzeug.security import check_password_hash

from backend import config
from backend.models import AuditLog

# Deliberately generic, and identical for every failure mode. Telling a caller
# that the username exists but the password is wrong hands them half the
# credential.
INVALID_CREDENTIALS = "Invalid credentials"


class AuthError(Exception):
    """Login failed, or a token was missing, expired or malformed."""


class PermissionError_(Exception):
    """Authenticated, but not allowed to do this."""


def _secret() -> str:
    """The signing secret, from the environment only.

    Read at call time rather than import time so a test can set it, but
    validated every time -- a weak secret silently accepted is worse than a
    crash, because the tokens it signs look perfectly valid.
    """
    secret = os.environ.get(config.JWT_SECRET_ENV_VAR)
    if not secret:
        raise RuntimeError(
            f"{config.JWT_SECRET_ENV_VAR} is not set. Generate one with: "
            "python -c 'import secrets; print(secrets.token_urlsafe(48))'"
        )
    if len(secret.encode()) < config.JWT_MIN_SECRET_BYTES:
        raise RuntimeError(
            f"{config.JWT_SECRET_ENV_VAR} must be at least "
            f"{config.JWT_MIN_SECRET_BYTES} bytes; got {len(secret.encode())}."
        )
    return secret


@dataclass(frozen=True)
class Principal:
    """Who is asking, as proven by the token. Never built from user input."""

    user_id: int
    role: str
    scope_type: str
    scope_id: int | None

    @property
    def is_national(self) -> bool:
        return self.scope_type == "national"

    def may_act_on_alerts(self) -> bool:
        """Only District and State officers act on alerts.

        Not arbitrary: under the scheme an MP recommends works while the
        District Authority sanctions, executes and verifies them. A platform
        letting an MP close an alert on their own constituency's work would
        invert the accountability the scheme rests on. The Ministry is
        oversight, not case-work.
        """
        return self.role in config.ALERT_ACTOR_ROLES


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------


def issue_token(user_id: int, role: str, scope_type: str,
                scope_id: int | None) -> str:
    """Sign a token for a user who has already proven their password.

    `sub` is the user id as a STRING. PyJWT rejects an integer subject, and
    the failure surfaces at decode time rather than here, which makes it an
    unpleasant one to debug.

    Expiry uses the real clock, not REFERENCE_DATE. That is the one place a
    wall clock is correct in this codebase: a token has to stop working in the
    actual world. Everything *scored* still reads REFERENCE_DATE, so the demo
    stays reproducible.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "role": role,
        "scope_type": scope_type,
        "scope_id": scope_id,
        "iat": now,
        "exp": now + timedelta(hours=config.JWT_EXPIRY_HOURS),
    }
    return jwt.encode(payload, _secret(), algorithm=config.JWT_ALGORITHM)


def verify_token(token: str) -> Principal:
    """Decode and validate a token, returning who it belongs to.

    The algorithm is pinned. Accepting whatever the token's own header asks
    for is how "alg": "none" downgrades happen.
    """
    try:
        payload = jwt.decode(
            token, _secret(), algorithms=[config.JWT_ALGORITHM]
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("Session expired. Please sign in again.") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthError("Invalid session token.") from exc

    try:
        user_id = int(payload["sub"])
        role = payload["role"]
        scope_type = payload["scope_type"]
    except (KeyError, TypeError, ValueError) as exc:
        raise AuthError("Invalid session token.") from exc

    return Principal(
        user_id=user_id,
        role=role,
        scope_type=scope_type,
        scope_id=payload.get("scope_id"),
    )


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

# role is an extra FILTER, never a claim. The login screen may offer a role
# selector, but a citizen choosing "District Officer" simply matches no row.
# is_active is in the WHERE for the same reason: a disabled account should not
# reach the password comparison at all.
_LOGIN_SQL = text("""
    SELECT user_id, username, password_hash, full_name, role,
           scope_type, scope_id, mp_id
    FROM users
    WHERE username = :username
      AND role = :role
      AND is_active = 1
""")


def login(session, username: str, password: str, role: str) -> dict:
    """Verify credentials and issue a token.

    Every failure -- unknown user, wrong role, disabled account, bad password
    -- raises the same AuthError with the same message. The caller must not
    distinguish them either.
    """
    row = session.execute(_LOGIN_SQL, {
        "username": username, "role": role,
    }).mappings().one_or_none()

    if row is None or not check_password_hash(row["password_hash"], password):
        raise AuthError(INVALID_CREDENTIALS)

    token = issue_token(row["user_id"], row["role"],
                        row["scope_type"], row["scope_id"])

    now = datetime.now(timezone.utc).isoformat()
    session.execute(
        text("UPDATE users SET last_login_at = :now WHERE user_id = :uid"),
        {"now": now, "uid": row["user_id"]},
    )
    # There is no session table to cross-reference, which makes the audit
    # trail the only record that this login happened.
    session.add(AuditLog(
        user_id=row["user_id"],
        action="login",
        subject_type=None,
        subject_id=None,
        detail=f"role={row['role']}",
        created_at=now,
    ))

    return {
        "token": token,
        "user": {
            "user_id": row["user_id"],
            "username": row["username"],
            "full_name": row["full_name"],
            "role": row["role"],
            "scope_type": row["scope_type"],
            "scope_id": row["scope_id"],
            "mp_id": row["mp_id"],
        },
    }


# ---------------------------------------------------------------------------
# Scope enforcement
# ---------------------------------------------------------------------------

# Which column on `works` each scope type constrains. One entry per scope
# type, so a new role cannot quietly fall through to "unfiltered".
_SCOPE_COLUMN = {
    "constituency": "works.constituency_id",
    "district": "works.district_id",
    "state": "districts.state_id",
}


def scope_filter(principal: Principal) -> tuple[str, dict]:
    """The WHERE fragment and bound params for this principal's visible rows.

    Returns a fragment that is always safe to AND into a query, plus the
    parameters it needs. The value is bound, never interpolated; only the
    column name comes from the table above, and that is code-owned.

    A national principal gets a fragment that is TRUE rather than a filter on
    a NULL scope_id. The Ministry user genuinely has scope_id = NULL, and
    `works.district_id = NULL` matches no rows in SQL -- the national
    dashboard would come back empty, looking like missing data rather than a
    mistake.
    """
    if principal.is_national:
        return "1 = 1", {}

    column = _SCOPE_COLUMN.get(principal.scope_type)
    if column is None or principal.scope_id is None:
        # Unknown scope type, or a scoped role with no scope. Deny rather
        # than fall back to unfiltered: the failure mode of guessing here is
        # showing someone the whole country.
        raise PermissionError_("This account has no valid data scope.")

    return f"{column} = :scope_id", {"scope_id": principal.scope_id}


def require_role(principal: Principal, *allowed: str) -> None:
    """Refuse a principal whose role is not in `allowed`."""
    if principal.role not in allowed:
        raise PermissionError_(
            "This account is not permitted to perform that action.")


def require_active_actor(session, principal: Principal) -> None:
    """Re-verify the account before a state-changing action.

    The read path trusts the signature alone -- the worklist loads on every
    page view and does not deserve a database hit. Acting on an alert is rare
    and consequential, so it is worth one query to close the gap where a
    stateless token outlives a revoked or demoted account.

    Both fields are re-read: a user disabled since login must be refused, and
    so must one whose role was reduced.
    """
    row = session.execute(text("""
        SELECT role, is_active FROM users WHERE user_id = :uid
    """), {"uid": principal.user_id}).mappings().one_or_none()

    if row is None or not row["is_active"]:
        raise AuthError("This account is no longer active.")
    if row["role"] != principal.role:
        raise AuthError("This account's permissions have changed. "
                        "Please sign in again.")
    if not principal.may_act_on_alerts():
        raise PermissionError_(
            "Only district and state officers can act on alerts.")


def record_action(session, principal: Principal, action: str,
                  subject_type: str | None = None,
                  subject_id: int | None = None,
                  detail: str | None = None) -> None:
    """Append a state-changing action to the audit trail. Never updates."""
    session.add(AuditLog(
        user_id=principal.user_id,
        action=action,
        subject_type=subject_type,
        subject_id=subject_id,
        detail=detail,
        created_at=datetime.now(timezone.utc).isoformat(),
    ))


# ---------------------------------------------------------------------------
# Alert scoping, across every subject type
# ---------------------------------------------------------------------------

# `scope_filter` above answers "which works may this principal see", which is
# all the citizen portal needs. The officer worklist is wider: an alert can be
# about a work, an MP, a district or a vendor, and only the first of those
# reaches a district through `works`.
#
# Each subject type therefore carries its own join and its own scope columns.
# Keeping them in one table rather than in the route is the same rule as
# before -- a WHERE clause written per route is a route somebody forgets.
#
# `join` is ANDed into the FROM clause of the worklist query, which already
# selects from scores. Every fragment here is code-owned; only values are
# bound.
_ALERT_SCOPE = {
    "work": {
        "join": ("JOIN works ON works.work_id = scores.subject_id "
                 "JOIN districts ON districts.district_id = works.district_id"),
        "constituency": "works.constituency_id",
        "district": "works.district_id",
        "state": "districts.state_id",
    },
    "vendor": {
        "join": ("JOIN vendors ON vendors.vendor_id = scores.subject_id "
                 "JOIN districts "
                 "ON districts.district_id = vendors.district_id"),
        # A vendor has no constituency; a constituency-scoped principal sees
        # none, which is correct -- vendors are a procurement concern.
        "constituency": None,
        "district": "vendors.district_id",
        "state": "districts.state_id",
    },
    "mp": {
        "join": "JOIN mps ON mps.mp_id = scores.subject_id",
        "constituency": "mps.constituency_id",
        # Quota shortfall routes to the State Officer, never to the district
        # -- and never only to the member the alert is about.
        "district": None,
        "state": "mps.state_id",
    },
    "district": {
        "join": ("JOIN districts "
                 "ON districts.district_id = scores.subject_id"),
        "constituency": None,
        "district": "districts.district_id",
        "state": "districts.state_id",
    },
}

ALERT_SUBJECT_TYPES = tuple(sorted(_ALERT_SCOPE))


def alert_scope_clause(principal: Principal,
                       subject_type: str) -> tuple[str, str, dict] | None:
    """(join, where, params) for one subject type, or None if out of scope.

    None means this principal sees no alerts of this type at all -- a district
    officer and MP-quota alerts, say. That is a real answer, not an error: the
    caller simply skips the subject type rather than emitting a query that
    would return everything.

    Note the JOIN is always paired with the type filter by the caller, because
    scores.subject_id is polymorphic. Joining `mps` on a subject_id that
    belongs to a work would match a completely unrelated member, and it would
    do so silently.
    """
    spec = _ALERT_SCOPE.get(subject_type)
    if spec is None:
        return None

    if principal.is_national:
        return spec["join"], "1 = 1", {}

    column = spec.get(principal.scope_type)
    if column is None or principal.scope_id is None:
        return None

    return spec["join"], f"{column} = :scope_id", {
        "scope_id": principal.scope_id,
    }
