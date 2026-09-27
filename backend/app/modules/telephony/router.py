import logging
import uuid
from datetime import date, datetime
from typing import Annotated, Literal
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import and_, case, func, select

from app.core import clinic_time
from app.core.config import get_settings
from app.core.deps import SessionDep, require_roles
from app.core.text import phone_digits_query, search_key
from app.modules.ai.models import CallAnalysis
from app.modules.leads.models import OPEN_STAGES, Lead
from app.modules.leads.service import find_patient_by_phone
from app.modules.patients.models import Patient
from app.modules.reports import service as reports
from app.modules.scheduling.models import ACTIVE_STATUSES, Appointment
from app.modules.tasks.models import Task, TaskStatus
from app.modules.telephony import service
from app.modules.telephony.models import (
    UNANSWERED_INBOUND,
    Call,
    CallDirection,
    CallStatus,
    RecordingStatus,
)
from app.modules.users.models import Role, User

log = logging.getLogger(__name__)
router = APIRouter(prefix="/telephony", tags=["telephony"])

CALL_CENTER = (Role.OPERATOR, Role.SUPERVISOR, Role.ADMIN)
VIEWERS = (*CALL_CENTER, Role.OWNER)
# recordings are sensitive: managers hear everything, an operator only their own calls
LISTENERS = (Role.SUPERVISOR, Role.ADMIN, Role.OWNER)
Agent = Annotated[User, Depends(require_roles(*CALL_CENTER))]
Viewer = Annotated[User, Depends(require_roles(*VIEWERS))]


# --- PBX -> CRM -------------------------------------------------------------------------------


def _enqueue_recording(call_id: uuid.UUID) -> None:
    from app.workers.celery_app import celery_app

    try:
        # MixMonitor closes its files right after the hangup handler runs
        celery_app.send_task("jobs.process_recording", args=[str(call_id)], countdown=5)
    except Exception:  # the broker being down must not lose the call record itself
        log.warning("could not queue recording processing for call %s", call_id)


@router.post("/events", include_in_schema=False)
async def pbx_event(
    request: Request,
    session: SessionDep,
    x_pbx_secret: Annotated[str | None, Header(alias="X-PBX-Secret")] = None,
) -> dict[str, bool]:
    if not service.valid_pbx_secret(x_pbx_secret):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="bad_secret")
    raw = (await request.body()).decode("utf-8", "replace")
    data = {k: v[-1] for k, v in parse_qs(raw, keep_blank_values=True).items()}
    call = await service.record_event(session, data)
    await session.commit()
    if call and call.recording_status is RecordingStatus.PENDING:
        _enqueue_recording(call.id)
    return {"ok": call is not None}


# --- softphone --------------------------------------------------------------------------------


class SoftphoneOut(BaseModel):
    enabled: bool
    extension: str | None = None
    password: str | None = None


@router.get("/me")
async def softphone(user: Agent) -> SoftphoneOut:
    """SIP credentials for the logged-in operator's own extension only."""
    ext = user.sip_extension
    if not get_settings().pbx_sip_secret or not ext or ext not in service.extensions():
        return SoftphoneOut(enabled=False)
    return SoftphoneOut(enabled=True, extension=ext, password=service.sip_password(ext))


@router.get("/extensions")
async def pbx_extensions(_: Annotated[User, Depends(require_roles(Role.ADMIN))]) -> list[str]:
    """Extensions the PBX defines (PBX_EXTENSIONS), for assigning them in Users."""
    return service.extensions()


class LookupPatient(BaseModel):
    id: uuid.UUID
    full_name: str
    kind: str
    do_not_call: bool
    district: str | None


class LookupLead(BaseModel):
    id: uuid.UUID
    name: str | None
    stage: str
    interest: str | None


class LookupOut(BaseModel):
    phone: str | None
    patient: LookupPatient | None = None
    lead: LookupLead | None = None
    open_tasks: int = 0
    next_visit: datetime | None = None


@router.get("/lookup")
async def lookup(phone: str, session: SessionDep, _: Agent) -> LookupOut:
    """Who is calling: shown in the incoming-call popup."""
    number = service.e164(phone)
    if not number:
        return LookupOut(phone=None)
    out = LookupOut(phone=number)
    patient = await find_patient_by_phone(session, number)
    if patient:
        out.patient = LookupPatient(
            id=patient.id,
            full_name=patient.full_name,
            kind=patient.kind.value,
            do_not_call=patient.do_not_call,
            district=patient.district,
        )
        out.open_tasks = await session.scalar(
            select(func.count())
            .select_from(Task)
            .where(Task.patient_id == patient.id, Task.status == TaskStatus.OPEN)
        )
        out.next_visit = await session.scalar(
            select(func.min(Appointment.starts_at)).where(
                Appointment.patient_id == patient.id,
                Appointment.status.in_(ACTIVE_STATUSES),
                Appointment.starts_at >= clinic_time.now(),
            )
        )
        return out
    lead = await session.scalar(
        select(Lead)
        .where(Lead.phone == number, Lead.stage.in_(OPEN_STAGES))
        .order_by(Lead.created_at.desc())
        .limit(1)
    )
    if lead:
        out.lead = LookupLead(
            id=lead.id, name=lead.name, stage=lead.stage.value, interest=lead.interest
        )
    return out


# --- call log ---------------------------------------------------------------------------------


class CallOut(BaseModel):
    id: uuid.UUID
    direction: CallDirection
    status: CallStatus
    phone: str | None
    caller_raw: str | None = None  # as reported by the PBX, when it isn't a valid Uzbek number
    patient_id: uuid.UUID | None
    patient_name: str | None
    lead_id: uuid.UUID | None
    task_id: uuid.UUID | None
    user_id: uuid.UUID | None
    user_name: str | None
    extension: str | None
    started_at: datetime
    ended_at: datetime | None
    wait_seconds: int | None
    talk_seconds: int | None
    callback_requested: bool
    recording_status: RecordingStatus | None
    ai_status: str | None = None
    ai_score: int | None = None
    ai_red_flags: bool = False


@router.get("/calls")
async def calls(
    session: SessionDep,
    user: Viewer,
    day: date | None = None,
    direction: CallDirection | None = None,
    call_status: Annotated[CallStatus | None, Query(alias="status")] = None,
    patient_id: uuid.UUID | None = None,
    who: Literal["all", "mine"] = "all",
    limit: int = Query(default=200, le=500),
) -> list[CallOut]:
    stmt = (
        select(
            Call, Patient.full_name, User.full_name,
            CallAnalysis.status, CallAnalysis.score, CallAnalysis.has_red_flags,
        )
        .outerjoin(Patient, Patient.id == Call.patient_id)
        .outerjoin(User, User.id == Call.user_id)
        .outerjoin(CallAnalysis, CallAnalysis.call_id == Call.id)
        .order_by(Call.started_at.desc())
        .limit(limit)
    )  # fmt: skip
    if patient_id:
        stmt = stmt.where(Call.patient_id == patient_id)
    else:
        start, end = clinic_time.day_bounds(day or clinic_time.today())
        stmt = stmt.where(Call.started_at >= start, Call.started_at < end)
    if direction:
        stmt = stmt.where(Call.direction == direction)
    if call_status:
        stmt = stmt.where(Call.status == call_status)
    if who == "mine":
        stmt = stmt.where(Call.user_id == user.id)
    return [
        CallOut(
            **{f: getattr(c, f) for f in CallOut.model_fields if hasattr(c, f)},
            patient_name=patient_name,
            user_name=user_name,
            ai_status=ai_status.value if ai_status else None,
            ai_score=ai_score,
            ai_red_flags=bool(flags),
        )
        for c, patient_name, user_name, ai_status, ai_score, flags in await session.execute(stmt)
    ]


class CallLogItem(CallOut):
    task_type: str | None = None
    task_outcome: str | None = None  # the operator's recorded result of the call's task
    task_outcome_reason: str | None = None
    ai_outcome: str | None = None  # what the AI analysis suggested
    called_back_at: datetime | None = None  # missed inbound: first call back to the number


class CallLogSummary(BaseModel):
    total: int
    inbound: int
    outbound: int
    answered: int
    missed: int  # unanswered inbound (missed, abandoned, after hours)
    missed_not_called_back: int
    outbound_answered: int
    avg_wait_sec: int | None
    talk_minutes: int


class CallLogPage(BaseModel):
    total: int
    items: list[CallLogItem]
    summary: CallLogSummary


MAX_LOG_DAYS = 92


@router.get("/call-log")
async def call_log(
    session: SessionDep,
    user: Viewer,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
    direction: CallDirection | None = None,
    call_status: Annotated[CallStatus | Literal["unanswered"] | None, Query(alias="status")] = None,
    user_id: uuid.UUID | None = None,
    who: Literal["all", "mine"] = "all",
    q: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CallLogPage:
    """TZ 4.7 call journal: a date range with filters, a page of calls and the range's totals."""
    date_to = date_to or clinic_time.today()
    date_from = date_from or date_to
    if not (
        2000 <= date_from.year <= 2100
        and 2000 <= date_to.year <= 2100
        and 0 <= (date_to - date_from).days <= MAX_LOG_DAYS
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="bad_range")
    start, end = clinic_time.day_bounds(date_from)[0], clinic_time.day_bounds(date_to)[1]
    where = [Call.started_at >= start, Call.started_at < end]
    if direction:
        where.append(Call.direction == direction)
    if call_status == "unanswered":
        where += [Call.direction == CallDirection.IN, Call.status.in_(UNANSWERED_INBOUND)]
    elif call_status:
        where.append(Call.status == call_status)
    if who == "mine":
        where.append(Call.user_id == user.id)
    elif user_id:
        where.append(Call.user_id == user_id)
    if q and q.strip():
        if digits := phone_digits_query(q):
            where.append(Call.phone.contains(digits) | Call.caller_raw.contains(digits))
        elif words := search_key(q).split():
            where.append(
                Call.patient_id.in_(
                    select(Patient.id).where(*(Patient.search_key.contains(w) for w in words))
                )
            )
    callback = reports.first_callback_at()
    missed = and_(Call.direction == CallDirection.IN, Call.status.in_(UNANSWERED_INBOUND))
    inbound = Call.direction == CallDirection.IN
    answered = Call.status == CallStatus.ANSWERED
    totals = (
        await session.execute(
            select(
                func.count(),
                func.count().filter(inbound),
                func.count().filter(~inbound),
                func.count().filter(inbound, answered),
                func.count().filter(missed),
                func.count().filter(missed, Call.phone.is_not(None), callback.is_(None)),
                func.count().filter(~inbound, answered),
                func.avg(Call.wait_seconds).filter(inbound, Call.wait_seconds.is_not(None)),
                func.coalesce(func.sum(Call.talk_seconds), 0),
            ).where(*where)
        )
    ).one()
    total, n_in, n_out, n_ans, n_missed, not_back, out_ans, avg_wait, talk = totals
    stmt = (
        select(
            Call, Patient.full_name, User.full_name, CallAnalysis.status, CallAnalysis.score,
            CallAnalysis.has_red_flags, CallAnalysis.suggested_outcome, Task.type, Task.outcome,
            Task.outcome_reason, case((missed, callback), else_=None),
        )
        .outerjoin(Patient, Patient.id == Call.patient_id)
        .outerjoin(User, User.id == Call.user_id)
        .outerjoin(CallAnalysis, CallAnalysis.call_id == Call.id)
        .outerjoin(Task, Task.id == Call.task_id)
        .where(*where)
        .order_by(Call.started_at.desc(), Call.id)
        .limit(limit)
        .offset(offset)
    )  # fmt: skip
    items = [
        CallLogItem(
            **{f: getattr(c, f) for f in CallOut.model_fields if hasattr(c, f)},
            patient_name=patient_name, user_name=user_name,
            ai_status=ai_status.value if ai_status else None, ai_score=ai_score,
            ai_red_flags=bool(flags), ai_outcome=ai_outcome,
            task_type=task_type.value if task_type else None,
            task_outcome=task_outcome.value if task_outcome else None,
            task_outcome_reason=reason, called_back_at=back,
        )
        for (
            c, patient_name, user_name, ai_status, ai_score, flags, ai_outcome, task_type,
            task_outcome, reason, back,
        ) in await session.execute(stmt)
    ]  # fmt: skip
    return CallLogPage(
        total=total,
        items=items,
        summary=CallLogSummary(
            total=total, inbound=n_in, outbound=n_out, answered=n_ans, missed=n_missed,
            missed_not_called_back=not_back, outbound_answered=out_ans,
            avg_wait_sec=round(float(avg_wait)) if avg_wait is not None else None,
            talk_minutes=round(talk / 60),
        ),
    )  # fmt: skip


@router.get("/calls/{call_id}/recording")
async def recording(call_id: uuid.UUID, session: SessionDep, user: Viewer) -> FileResponse:
    call = await session.get(Call, call_id)
    if call is None or call.recording_status is not RecordingStatus.READY or not call.recording:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="recording_not_found")
    if user.role not in LISTENERS and call.user_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="forbidden")
    path = service.recordings_dir() / call.recording
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="recording_not_found")
    return FileResponse(path, media_type="audio/mpeg", filename=f"call-{call.id}.mp3")
