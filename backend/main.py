"""The HTTP API. Two routers, three portals.

Run `uvicorn backend.main:app --reload --port 8000`.

`/citizen/*` and `/officer/*` are separate routers over the same database.
The split is not organisational: the citizen router contains **no code path
that selects total_score, reasons_json or any *_points column**, so "this
router cannot leak a risk score" is provable by the absence of code rather
than by a filter somebody has to remember. Leaking one would take a
deliberate edit.

There is no third router for MPs and the Ministry. They legitimately *see*
scores, so there is no such guarantee to protect for them; their restriction
is on writes, and `require_actor` returns 403 on the four action endpoints.
A third router would add files without adding safety.

Scope is never accepted from the client. Every scoped query derives its
filter from the verified token via `auth.scope_filter` or
`auth.alert_scope_clause`. A route taking `?district_id=` would let an
officer read someone else's district by editing a URL.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path

from fastapi import (APIRouter, Depends, FastAPI, File, Form, HTTPException,
                     Request, UploadFile)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend import auth, config, uploads
from backend.db import get_db

REF = config.REFERENCE_DATE


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Refuse to serve without a usable signing secret.

    auth._secret() is deliberately read at call time, which means a server
    started without JWT_SECRET boots cleanly, answers /health with a 200 and
    then returns 500 on the first login. During a demo that reads as "the app
    is broken" rather than "an environment variable is missing", and the
    traceback only appears in the server log.

    Validating once at startup turns a confusing runtime 500 into a refusal to
    start, naming the command that fixes it. This only reads the secret; it is
    never logged.
    """
    auth._secret()
    yield


app = FastAPI(
    title="MPLADS Risk Engine",
    description="Anomaly detection and monitoring for MPLADS works.",
    version="1.0.0",
    lifespan=lifespan,
)

# The React dev server, plus whatever origins a deployment adds. Data that
# reached the browser has already left the server, so this list is a
# convenience for the browser -- never the access control. Scope enforcement
# lives in the token and the shared dependency.
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_allow_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


def current_principal(request: Request) -> auth.Principal:
    """Who is asking, proven by the bearer token. Never from the body."""
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "Not authenticated.")
    try:
        return auth.verify_token(token)
    except auth.AuthError as exc:
        raise HTTPException(401, str(exc)) from exc


def require_citizen(
    principal: auth.Principal = Depends(current_principal),
) -> auth.Principal:
    if principal.role != "citizen":
        raise HTTPException(403, "This portal is for citizen accounts.")
    return principal


def require_officer_or_oversight(
    principal: auth.Principal = Depends(current_principal),
) -> auth.Principal:
    """Anyone entitled to see a score: officers plus MP and Ministry.

    Citizens are excluded here rather than filtered later, so no citizen
    request ever reaches a query that selects total_score.
    """
    if principal.role == "citizen":
        raise HTTPException(403, "Risk scores are not public.")
    return principal


def require_actor(
    principal: auth.Principal = Depends(current_principal),
    db: Session = Depends(get_db),
) -> auth.Principal:
    """A principal allowed to change an alert's state, re-verified now.

    Reads trust the signature alone; this is the one path that pays for a
    database lookup, because a token cannot be revoked and acting on an alert
    is both rare and consequential.
    """
    try:
        auth.require_active_actor(db, principal)
    except auth.AuthError as exc:
        raise HTTPException(401, str(exc)) from exc
    except auth.PermissionError_ as exc:
        raise HTTPException(403, str(exc)) from exc
    return principal


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    username: str
    password: str
    # A filter, never a claim. The server re-checks it against the row.
    role: str


class ResolveRequest(BaseModel):
    # Both required. An officer must not be able to close a large alert with
    # a bare "visited" button; what was found has to be on the record.
    verdict: str = Field(pattern="^(substantiated|not_substantiated"
                                 "|could_not_verify)$")
    resolution_note: str = Field(min_length=10)


class SnoozeRequest(BaseModel):
    days: int = Field(ge=1, le=180)
    note: str | None = None


class ComplaintRequest(BaseModel):
    text: str = Field(min_length=10, max_length=2000)
    lat: float | None = None
    lon: float | None = None


class RatingRequest(BaseModel):
    stars: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=500)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

auth_router = APIRouter(prefix="/auth", tags=["auth"])


@auth_router.post("/login")
def login(body: LoginRequest, db: Session = Depends(get_db)) -> dict:
    """One login endpoint for every role.

    Three endpoints would mean getting the audit write and the generic
    failure message right in three places instead of one.
    """
    try:
        result = auth.login(db, body.username, body.password, body.role)
    except auth.AuthError as exc:
        # Deliberately the same response for an unknown user, a wrong role, a
        # disabled account and a bad password.
        raise HTTPException(401, str(exc)) from exc
    db.commit()
    return result


@auth_router.get("/me")
def whoami(principal: auth.Principal = Depends(current_principal)) -> dict:
    return {
        "user_id": principal.user_id,
        "role": principal.role,
        "scope_type": principal.scope_type,
        "scope_id": principal.scope_id,
    }


# ---------------------------------------------------------------------------
# Citizen router -- facts only, never a score
# ---------------------------------------------------------------------------

citizen_router = APIRouter(prefix="/citizen", tags=["citizen"])

# Every column a citizen may see. The risk score, the reasons and the
# per-check point columns are absent from this SELECT and from every other
# query in this router -- that absence is the guarantee, and it is meant to
# survive a grep for those column names across this file.
#
# Contractor names are public record and may be shown. They must never appear
# beside a risk score on a public page, which is structurally impossible here
# because this router has no access to one.
_CITIZEN_WORK_COLUMNS = """
    works.work_id, works.work_type, works.description,
    works.terrain, works.area_type, works.quantity, works.unit,
    works.estimated_cost, works.final_cost,
    works.recommended_on, works.sanctioned_on,
    works.expected_completion_on, works.completed_on,
    works.status, works.progress_pct, works.lat, works.lon,
    districts.name AS district_name,
    vendors.name AS vendor_name
"""

_CITIZEN_FROM = """
    FROM works
    JOIN districts ON districts.district_id = works.district_id
    LEFT JOIN vendors ON vendors.vendor_id = works.vendor_id
"""


def _overdue_days(work: dict) -> int | None:
    """Days past the expected completion date, or None.

    Arithmetic on two stored fields, not a score. "Expected by 16 Jan 2026,
    still in progress -- 242 days overdue" is something a citizen can already
    work out from the dates on the page; hiding it would make the page less
    honest, not more careful.
    """
    if work.get("completed_on") or not work.get("expected_completion_on"):
        return None
    overdue = (REF - date.fromisoformat(work["expected_completion_on"])).days
    return overdue if overdue > 0 else None


@citizen_router.get("/works")
def citizen_works(
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    principal: auth.Principal = Depends(require_citizen),
    db: Session = Depends(get_db),
) -> dict:
    """Works in the citizen's own constituency.

    The scope comes from the token. There is deliberately no district or
    constituency parameter to pass.
    """
    where, params = auth.scope_filter(principal)
    clauses = [where]
    if status:
        clauses.append("works.status = :status")
        params["status"] = status

    params.update({"limit": min(limit, 200), "offset": max(offset, 0)})

    rows = db.execute(text(f"""
        SELECT {_CITIZEN_WORK_COLUMNS}
        {_CITIZEN_FROM}
        WHERE {' AND '.join(clauses)}
        ORDER BY works.work_id
        LIMIT :limit OFFSET :offset
    """), params).mappings().all()

    total = db.execute(text(f"""
        SELECT COUNT(*) {_CITIZEN_FROM} WHERE {' AND '.join(clauses)}
    """), params).scalar()

    works = []
    for row in rows:
        work = dict(row)
        work["overdue_days"] = _overdue_days(work)
        works.append(work)

    return {"total": total, "works": works}


@citizen_router.get("/works/{work_id}")
def citizen_work_detail(
    work_id: int,
    principal: auth.Principal = Depends(require_citizen),
    db: Session = Depends(get_db),
) -> dict:
    """One work, with its photographs.

    Out of scope returns 404 rather than 403, so the response does not
    confirm that a work the citizen may not see exists.
    """
    where, params = auth.scope_filter(principal)
    params["work_id"] = work_id

    row = db.execute(text(f"""
        SELECT {_CITIZEN_WORK_COLUMNS}
        {_CITIZEN_FROM}
        WHERE works.work_id = :work_id AND {where}
    """), params).mappings().one_or_none()

    if row is None:
        raise HTTPException(404, "Work not found.")

    work = dict(row)
    work["overdue_days"] = _overdue_days(work)

    work["photos"] = [dict(r) for r in db.execute(text("""
        SELECT evidence_id, kind, file_path, stage, captured_at
        FROM evidence
        WHERE work_id = :work_id AND kind = 'photo'
        ORDER BY evidence_id
    """), {"work_id": work_id}).mappings().all()]

    work["complaint_count"] = db.execute(text("""
        SELECT COUNT(*) FROM complaints
        WHERE work_id = :work_id AND verified = 1
    """), {"work_id": work_id}).scalar()

    work["rating_summary"] = _rating_summary(db, work_id)

    return work


def _rating_summary(db: Session, work_id: int) -> dict:
    """Average and count of citizen ratings for one work.

    A summary, never the individual rows: a rating is attached to a named
    citizen account, and who rated what is not public.
    """
    row = db.execute(text("""
        SELECT COUNT(*) AS count, AVG(stars) AS average
        FROM ratings WHERE work_id = :work_id
    """), {"work_id": work_id}).mappings().one()
    return {
        "count": row["count"],
        "average": round(row["average"], 1) if row["count"] else None,
    }


@citizen_router.post("/works/{work_id}/complaint", status_code=201)
async def file_complaint(
    work_id: int,
    text_: str = Form(alias="text", min_length=10, max_length=2000),
    lat: float | None = Form(default=None),
    lon: float | None = Form(default=None),
    photo: UploadFile | None = File(default=None),
    principal: auth.Principal = Depends(require_citizen),
    db: Session = Depends(get_db),
) -> dict:
    """File one report about a work in the citizen's own constituency.

    UNIQUE(work_id, user_id) is what makes C6's distinct-reporter count
    meaningful, so a second attempt is refused rather than silently accepted.

    Multipart rather than JSON, because a report may carry a photograph the
    citizen captured at the site. The photograph is optional and a report
    without one behaves exactly as it always has.

    The photograph is stored against the COMPLAINT, never as an `evidence`
    row. evidence is official proof and its absence is what C7 detects -- a
    citizen photographing a road must not be able to clear the ghost-asset
    flag on a work that was never built, and two citizens photographing the
    same landmark must not trip the reused-photo check. Nothing a citizen
    uploads moves a score; it is material for the officer who verifies.
    """
    where, params = auth.scope_filter(principal)
    params["work_id"] = work_id
    exists = db.execute(text(f"""
        SELECT 1 {_CITIZEN_FROM} WHERE works.work_id = :work_id AND {where}
    """), params).scalar()
    if not exists:
        raise HTTPException(404, "Work not found.")

    # Read and re-encode BEFORE the insert: a photograph that turns out not
    # to be an image should fail the request, not leave a complaint row
    # pointing at a file that was never written.
    image_bytes = None
    if photo is not None and photo.filename:
        raw = await photo.read()
        try:
            image_bytes = uploads.normalise(raw)
        except uploads.UploadError as exc:
            raise HTTPException(400, str(exc)) from None

    try:
        result = db.execute(text("""
            INSERT INTO complaints
                (work_id, user_id, text, photo_path, lat, lon, verified,
                 verified_by, created_at)
            VALUES
                (:work_id, :user_id, :text, NULL, :lat, :lon, 0, NULL,
                 :created_at)
        """), {
            "work_id": work_id,
            "user_id": principal.user_id,
            "text": text_,
            "lat": lat,
            "lon": lon,
            "created_at": REF.isoformat(),
        })

        # The path is keyed by complaint_id, so it is only known once the row
        # exists. Written inside the transaction: if the write fails the
        # complaint is rolled back rather than left claiming a missing file.
        if image_bytes is not None:
            complaint_id = result.lastrowid
            relative = uploads.complaint_photo_path(work_id, complaint_id)
            uploads.write_photo(relative, image_bytes)
            db.execute(text("""
                UPDATE complaints SET photo_path = :path
                WHERE complaint_id = :complaint_id
            """), {"path": relative, "complaint_id": complaint_id})

        auth.record_action(db, principal, "complaint_filed", "work", work_id)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            409, "You have already reported this work.") from None

    return {"status": "received",
            "message": "Your report has been recorded for verification."}


@citizen_router.get("/complaints/{complaint_id}/photo")
def citizen_complaint_photo(
    complaint_id: int,
    principal: auth.Principal = Depends(require_citizen),
    db: Session = Depends(get_db),
) -> FileResponse:
    """One complaint's photograph, scoped like every other citizen read.

    A route rather than a StaticFiles mount on the upload directory: a mount
    would make every citizen's photograph world-readable by URL and bypass
    scope_filter entirely.
    """
    return _complaint_photo_response(db, complaint_id,
                                     *auth.scope_filter(principal))


def _complaint_photo_response(db: Session, complaint_id: int,
                              where: str, params: dict) -> FileResponse:
    """Shared by the citizen and officer photo routes.

    Out of scope is 404, not 403 -- the response must not confirm that a
    photograph the caller may not see exists.
    """
    params = {**params, "complaint_id": complaint_id}
    row = db.execute(text(f"""
        SELECT complaints.photo_path
        FROM complaints
        JOIN works ON works.work_id = complaints.work_id
        JOIN districts ON districts.district_id = works.district_id
        WHERE complaints.complaint_id = :complaint_id AND {where}
    """), params).mappings().one_or_none()

    if row is None or not row["photo_path"]:
        raise HTTPException(404, "Photograph not found.")

    try:
        path = uploads.resolve_upload(row["photo_path"])
    except uploads.UploadError:
        raise HTTPException(404, "Photograph not found.") from None

    if not path.is_file():
        # Expected in deployment: Render's free tier has no persistent disk,
        # so uploads do not survive a restart. A missing file is a 404, not a
        # 500 -- the row is still a legitimate report.
        raise HTTPException(404, "Photograph is no longer available.")

    return FileResponse(path, media_type="image/jpeg")


@citizen_router.post("/works/{work_id}/rating", status_code=201)
def rate_work(
    work_id: int,
    body: RatingRequest,
    principal: auth.Principal = Depends(require_citizen),
    db: Session = Depends(get_db),
) -> dict:
    """Rate a completed work 1-5.

    Only completed works: rating a road that is still being built measures
    nothing. UNIQUE(work_id, user_id) stops one person moving the average,
    and a second attempt is refused rather than silently replacing the first.

    This feeds no check. See models.Rating for why.
    """
    where, params = auth.scope_filter(principal)
    params["work_id"] = work_id
    row = db.execute(text(f"""
        SELECT works.status {_CITIZEN_FROM}
        WHERE works.work_id = :work_id AND {where}
    """), params).mappings().one_or_none()
    if row is None:
        raise HTTPException(404, "Work not found.")
    if row["status"] != "completed":
        raise HTTPException(
            400, "Only completed works can be rated.")

    try:
        db.execute(text("""
            INSERT INTO ratings (work_id, user_id, stars, comment, created_at)
            VALUES (:work_id, :user_id, :stars, :comment, :created_at)
        """), {
            "work_id": work_id,
            "user_id": principal.user_id,
            "stars": body.stars,
            "comment": body.comment,
            "created_at": REF.isoformat(),
        })
        auth.record_action(db, principal, "work_rated", "work", work_id,
                           detail=f"stars={body.stars}")
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "You have already rated this work.") from None

    return {"status": "recorded", "message": "Thank you for rating this work."}


# ---------------------------------------------------------------------------
# Officer router -- scores, evidence and the act buttons
# ---------------------------------------------------------------------------

officer_router = APIRouter(prefix="/officer", tags=["officer"])

# How each subject type names itself on the worklist. The label is resolved in
# SQL per subject type rather than by a second round trip per alert.
_SUBJECT_LABEL = {
    "work": ("works.description", "works.work_type"),
    "mp": ("mps.full_name", "mps.house"),
    "district": ("districts.name", "'district'"),
    "vendor": ("vendors.name", "'vendor'"),
}


@officer_router.get("/alerts")
def worklist(
    status: str | None = None,
    severity: str | None = None,
    subject_type: str | None = None,
    limit: int = 100,
    principal: auth.Principal = Depends(require_officer_or_oversight),
    db: Session = Depends(get_db),
) -> dict:
    """The ranked worklist. Worst first.

    Assembled per subject type because an alert about a work, an MP, a
    district and a vendor each reach a principal's scope by a different join.
    A district officer sees no MP-quota alerts at all -- those route to the
    State Officer, because an alert about someone must not land only on that
    same person's desk.

    Every row carries its reasons. A bare score is never returned, so the
    frontend cannot render one even by accident.
    """
    wanted = ([subject_type] if subject_type
              else list(auth.ALERT_SUBJECT_TYPES))

    alerts = []
    for kind in wanted:
        scope = auth.alert_scope_clause(principal, kind)
        if scope is None:
            continue
        join, where, params = scope
        label, sublabel = _SUBJECT_LABEL[kind]

        clauses = [where, "scores.subject_type = :kind"]
        params = {**params, "kind": kind}
        if status:
            clauses.append("alerts.status = :status")
            params["status"] = status
        if severity:
            clauses.append("alerts.severity = :severity")
            params["severity"] = severity

        rows = db.execute(text(f"""
            SELECT alerts.alert_id, alerts.severity, alerts.status,
                   alerts.snoozed_until, alerts.created_at,
                   scores.subject_type, scores.subject_id,
                   scores.total_score, scores.reasons_json,
                   {label} AS subject_label,
                   {sublabel} AS subject_sublabel
            FROM alerts
            JOIN scores ON scores.score_id = alerts.score_id
            {join}
            WHERE {' AND '.join(clauses)}
        """), params).mappings().all()

        for row in rows:
            alert = dict(row)
            # The sentences, not just the number. Every score is shown with
            # its reasons -- that is the whole basis of the product.
            alert["reasons"] = json.loads(alert.pop("reasons_json"))
            alerts.append(alert)

    # Worst first, with a stable tiebreak so paging cannot reorder.
    alerts.sort(key=lambda a: (-a["total_score"], a["alert_id"]))

    return {
        "total": len(alerts),
        "can_act": principal.may_act_on_alerts(),
        "alerts": alerts[:min(limit, 500)],
    }


def _load_alert(db: Session, principal: auth.Principal, alert_id: int) -> dict:
    """One alert the principal is entitled to see, or 404.

    The subject_type filter and the join are applied together, always. Joining
    on scores.subject_id without first filtering the type is the trap the
    polymorphic column sets: a district score with subject_id 3 matches work 3
    just as happily, and it fails silently rather than erroring.
    """
    row = db.execute(text("""
        SELECT alerts.alert_id, alerts.score_id, alerts.severity,
               alerts.status, alerts.verdict, alerts.resolution_note,
               alerts.snoozed_until, alerts.assigned_to, alerts.created_at,
               alerts.resolved_at,
               scores.subject_type, scores.subject_id, scores.total_score,
               scores.cost_points, scores.delay_points,
               scores.compliance_points, scores.duplicate_points,
               scores.public_points, scores.evidence_points,
               scores.utilisation_points,
               scores.reasons_json, scores.checks_run, scores.checks_skipped,
               scores.scored_on
        FROM alerts
        JOIN scores ON scores.score_id = alerts.score_id
        WHERE alerts.alert_id = :alert_id
    """), {"alert_id": alert_id}).mappings().one_or_none()

    if row is None:
        raise HTTPException(404, "Alert not found.")

    alert = dict(row)
    scope = auth.alert_scope_clause(principal, alert["subject_type"])
    if scope is None:
        # Not merely unauthorised -- this principal never sees this subject
        # type. 404 rather than 403 so the response does not confirm it exists.
        raise HTTPException(404, "Alert not found.")

    join, where, params = scope
    visible = db.execute(text(f"""
        SELECT 1 FROM alerts
        JOIN scores ON scores.score_id = alerts.score_id
        {join}
        WHERE alerts.alert_id = :alert_id
          AND scores.subject_type = :kind
          AND {where}
    """), {**params, "alert_id": alert_id,
           "kind": alert["subject_type"]}).scalar()

    if not visible:
        # This is the demo: Pune's alert id pasted into Nashik's session.
        raise HTTPException(404, "Alert not found.")

    return alert


@officer_router.get("/alerts/{alert_id}")
def alert_detail(
    alert_id: int,
    principal: auth.Principal = Depends(require_officer_or_oversight),
    db: Session = Depends(get_db),
) -> dict:
    """An alert with everything needed to verify it without leaving the page.

    If an officer cannot explain the score from what is here, the evidence
    pack is incomplete.
    """
    alert = _load_alert(db, principal, alert_id)

    alert["reasons"] = json.loads(alert.pop("reasons_json"))
    alert["checks_run"] = json.loads(alert["checks_run"])
    alert["checks_skipped"] = json.loads(alert["checks_skipped"])
    alert["can_act"] = principal.may_act_on_alerts()
    alert["routes_to"] = config.SUBJECT_ROUTING.get(alert["subject_type"])

    if alert["subject_type"] == "work":
        work_id = alert["subject_id"]
        alert["work"] = dict(db.execute(text(f"""
            SELECT {_CITIZEN_WORK_COLUMNS}, works.fy, works.is_sc_area,
                   works.is_st_area, works.last_updated_on,
                   agencies.name AS agency_name,
                   mps.full_name AS mp_name
            {_CITIZEN_FROM}
            LEFT JOIN agencies ON agencies.agency_id = works.agency_id
            LEFT JOIN mps ON mps.mp_id = works.mp_id
            WHERE works.work_id = :work_id
        """), {"work_id": work_id}).mappings().one())

        # The evidence pack. Absence is itself a signal -- an empty evidence
        # list on a completed work is exactly what C7 flags.
        alert["payments"] = [dict(r) for r in db.execute(text("""
            SELECT payment_id, tranche_no, amount, paid_on,
                   progress_pct_at_payment, voucher_ref
            FROM payments WHERE work_id = :work_id ORDER BY tranche_no
        """), {"work_id": work_id}).mappings().all()]

        alert["progress_updates"] = [dict(r) for r in db.execute(text("""
            SELECT update_id, progress_pct, reported_on, reported_by, note
            FROM progress_updates WHERE work_id = :work_id
            ORDER BY reported_on, update_id
        """), {"work_id": work_id}).mappings().all()]

        alert["evidence"] = [dict(r) for r in db.execute(text("""
            SELECT evidence_id, kind, file_path, stage, captured_at,
                   uploaded_at, exif_lat, exif_lon
            FROM evidence WHERE work_id = :work_id ORDER BY evidence_id
        """), {"work_id": work_id}).mappings().all()]

        # has_photo rather than the path: the officer's client asks for the
        # image by complaint id through a scoped route, so the storage layout
        # never reaches the browser.
        alert["complaints"] = [dict(r) for r in db.execute(text("""
            SELECT complaint_id, text, verified, created_at, lat, lon,
                   CASE WHEN photo_path IS NOT NULL THEN 1 ELSE 0 END
                     AS has_photo
            FROM complaints WHERE work_id = :work_id ORDER BY complaint_id
        """), {"work_id": work_id}).mappings().all()]

        # Context for the verdict, never a component of the score.
        alert["rating_summary"] = _rating_summary(db, work_id)

    elif alert["subject_type"] == "mp":
        alert["mp"] = dict(db.execute(text("""
            SELECT mps.mp_id, mps.full_name, mps.house, mps.term_start,
                   mps.term_end, constituencies.name AS constituency_name,
                   states.name AS state_name
            FROM mps
            JOIN constituencies
              ON constituencies.constituency_id = mps.constituency_id
            JOIN states ON states.state_id = mps.state_id
            WHERE mps.mp_id = :mp_id
        """), {"mp_id": alert["subject_id"]}).mappings().one())

    elif alert["subject_type"] == "vendor":
        alert["vendor"] = dict(db.execute(text("""
            SELECT vendors.vendor_id, vendors.name, vendors.registered_on,
                   districts.name AS district_name
            FROM vendors
            JOIN districts ON districts.district_id = vendors.district_id
            WHERE vendors.vendor_id = :vendor_id
        """), {"vendor_id": alert["subject_id"]}).mappings().one())

    elif alert["subject_type"] == "district":
        alert["district"] = dict(db.execute(text("""
            SELECT districts.district_id, districts.name,
                   states.name AS state_name
            FROM districts
            JOIN states ON states.state_id = districts.state_id
            WHERE districts.district_id = :district_id
        """), {"district_id": alert["subject_id"]}).mappings().one())

    return alert


def _transition(db: Session, principal: auth.Principal, alert_id: int,
                action: str, **fields) -> dict:
    """Apply one workflow change and record who did it.

    audit_log matters more here than anywhere: there is no session table to
    cross-reference, so this is the only record that a particular officer
    closed a particular alert.
    """
    alert = _load_alert(db, principal, alert_id)

    assignments = ", ".join(f"{name} = :{name}" for name in fields)
    db.execute(text(f"""
        UPDATE alerts SET {assignments}, assigned_to = :actor
        WHERE alert_id = :alert_id
    """), {**fields, "actor": principal.user_id, "alert_id": alert_id})

    auth.record_action(db, principal, action, alert["subject_type"],
                       alert["subject_id"],
                       detail=f"alert_id={alert_id}")
    db.commit()

    return {"alert_id": alert_id, "status": fields.get("status", "open")}


@officer_router.post("/alerts/{alert_id}/acknowledge")
def acknowledge(alert_id: int,
                principal: auth.Principal = Depends(require_actor),
                db: Session = Depends(get_db)) -> dict:
    return _transition(db, principal, alert_id, "alert_acknowledged",
                       status="acknowledged")


@officer_router.post("/alerts/{alert_id}/escalate")
def escalate(alert_id: int,
             principal: auth.Principal = Depends(require_actor),
             db: Session = Depends(get_db)) -> dict:
    return _transition(db, principal, alert_id, "alert_escalated",
                       status="escalated")


@officer_router.post("/alerts/{alert_id}/resolve")
def resolve(alert_id: int, body: ResolveRequest,
            principal: auth.Principal = Depends(require_actor),
            db: Session = Depends(get_db)) -> dict:
    """Close an alert, recording what was actually found.

    verdict and resolution_note are required by the request model, so a bare
    "visited" cannot clear a large alert. Enforced here rather than in the
    schema, where the constraint would be unreadable.
    """
    return _transition(db, principal, alert_id, "alert_resolved",
                       status="resolved",
                       verdict=body.verdict,
                       resolution_note=body.resolution_note,
                       resolved_at=REF.isoformat())


@officer_router.post("/alerts/{alert_id}/snooze")
def snooze(alert_id: int, body: SnoozeRequest,
           principal: auth.Principal = Depends(require_actor),
           db: Session = Depends(get_db)) -> dict:
    """Defer an alert. It returns; it does not disappear.

    This is the honest alternative to a dismiss button -- the alert comes
    back rather than being quietly cleared.
    """
    until = (REF + timedelta(days=body.days)).isoformat()
    result = _transition(db, principal, alert_id, "alert_snoozed",
                         snoozed_until=until)
    result["snoozed_until"] = until
    return result


# ---------------------------------------------------------------------------
# Complaint verification
# ---------------------------------------------------------------------------
#
# The one officer action here that changes a SCORE. C6 counts distinct
# verified complaints, so marking one verified can award up to 15 points on
# the next run of checks.py. That is the intended design -- an unverified
# report must never move a score, and a verified one is a fact an officer has
# stood behind -- but it is why the audit_log write is not optional: this is
# the only record of who decided a public report was true.
#
# Until this existed, nothing anywhere could set complaints.verified, so a
# report filed through the API could never reach C6 at all.


def _load_complaint_for_actor(db: Session, principal: auth.Principal,
                              complaint_id: int) -> dict:
    """One complaint the principal is entitled to act on, or 404.

    Scoped through the complaint's parent work with the same filter every
    other route uses. Out of scope is 404, not 403.
    """
    where, params = auth.scope_filter(principal)
    params["complaint_id"] = complaint_id
    row = db.execute(text(f"""
        SELECT complaints.complaint_id, complaints.work_id,
               complaints.verified, complaints.photo_path
        FROM complaints
        JOIN works ON works.work_id = complaints.work_id
        JOIN districts ON districts.district_id = works.district_id
        WHERE complaints.complaint_id = :complaint_id AND {where}
    """), params).mappings().one_or_none()

    if row is None:
        raise HTTPException(404, "Complaint not found.")
    return dict(row)


@officer_router.post("/complaints/{complaint_id}/verify")
def verify_complaint(complaint_id: int,
                     principal: auth.Principal = Depends(require_actor),
                     db: Session = Depends(get_db)) -> dict:
    """Confirm a citizen's report, so that it counts towards C6.

    require_actor means district and state officers only -- MPs and the
    Ministry are view-only, and an MP confirming a report about their own
    constituency's work would invert the accountability the scheme rests on.
    """
    complaint = _load_complaint_for_actor(db, principal, complaint_id)

    if complaint["verified"]:
        return {"complaint_id": complaint_id, "verified": 1,
                "message": "Already verified."}

    db.execute(text("""
        UPDATE complaints SET verified = 1, verified_by = :actor
        WHERE complaint_id = :complaint_id
    """), {"actor": principal.user_id, "complaint_id": complaint_id})

    auth.record_action(db, principal, "complaint_verified", "work",
                       complaint["work_id"],
                       detail=f"complaint_id={complaint_id}")
    db.commit()

    return {"complaint_id": complaint_id, "verified": 1,
            "message": "Report verified. It will count at the next scoring run."}


@officer_router.get("/complaints/{complaint_id}/photo")
def officer_complaint_photo(
    complaint_id: int,
    principal: auth.Principal = Depends(require_officer_or_oversight),
    db: Session = Depends(get_db),
) -> FileResponse:
    """The citizen's photograph, for the officer deciding whether to verify."""
    return _complaint_photo_response(db, complaint_id,
                                     *auth.scope_filter(principal))


# Every API route lives under /api. One service serves both the API and the
# built React app, so the prefix is what keeps them apart: without it a work
# route and a client route could claim the same path, and the SPA fallback
# below would swallow API 404s as HTML.
API_PREFIX = "/api"

app.include_router(auth_router, prefix=API_PREFIX)
app.include_router(citizen_router, prefix=API_PREFIX)
app.include_router(officer_router, prefix=API_PREFIX)


@app.get(f"{API_PREFIX}/health")
def health() -> dict:
    """Liveness for the platform's health check. No auth, no database.

    Deliberately does not touch the database: a health check that opens a
    connection turns a slow query into a restart loop.
    """
    return {"ok": True}


@app.get(f"{API_PREFIX}/status")
def status(db: Session = Depends(get_db)) -> dict:
    """Liveness plus the two numbers that say the pipeline has been run."""
    return {
        "status": "ok",
        "reference_date": REF.isoformat(),
        "works": db.execute(text("SELECT COUNT(*) FROM works")).scalar(),
        "alerts": db.execute(text("SELECT COUNT(*) FROM alerts")).scalar(),
    }


# ---------------------------------------------------------------------------
# Static frontend
#
# EVERYTHING BELOW MUST BE THE LAST THING REGISTERED IN THIS FILE.
# FastAPI matches routes in registration order, so the catch-all would
# shadow every API route declared after it and return HTML where the client
# expects JSON.
# ---------------------------------------------------------------------------

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"

# Guarded so local development without a build still runs: `npm run dev`
# serves the app itself on another port and this block simply does nothing.
if FRONTEND_DIR.is_dir():
    app.mount(
        "/assets",
        StaticFiles(directory=FRONTEND_DIR / "assets"),
        name="assets",
    )

    _INDEX = FRONTEND_DIR / "index.html"

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_spa(full_path: str) -> FileResponse:
        """Serve a real file when one exists, else index.html.

        React Router owns paths like /officer/alerts/272 that exist only in
        the browser. On a hard refresh the server is asked for them directly
        and must answer with the app shell rather than a 404, or the router
        never gets the chance to run.
        """
        # An unmatched /api path is a client error, not a page. Falling
        # through to index.html would answer a bad API call with HTTP 200
        # and HTML, which a fetch() would try to parse as JSON.
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")

        # Resolve inside the build directory and confirm the result is still
        # within it: a path like "../../backend/mplads.db" would otherwise
        # escape and serve the database.
        candidate = (FRONTEND_DIR / full_path).resolve()
        if candidate.is_file() and candidate.is_relative_to(FRONTEND_DIR.resolve()):
            return FileResponse(candidate)
        return FileResponse(_INDEX)
