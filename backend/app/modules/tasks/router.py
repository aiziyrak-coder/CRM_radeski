import uuid
from datetime import date, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import AwareDatetime, BaseModel, Field, StringConstraints
from sqlalchemy import func, select

from app.core import clinic_time
from app.core.deps import SessionDep, client_ip, require_roles
from app.modules.ai import service as ai
from app.modules.audit import service as audit
from app.modules.campaigns.models import Campaign
from app.modules.catalog.models import Branch, Doctor, Service
from app.modules.leads.models import Lead
from app.modules.patients.models import Patient
from app.modules.scheduling.models import Appointment, Recommendation
from app.modules.scheduling.service import SchedulingError
from app.modules.tasks import service
from app.modules.tasks.models import (
    REASONS,
    Outcome,
    ShiftNote,
    Task,
    TaskAttempt,
    TaskStatus,
    TaskType,
)
from app.modules.users.models import Role, User

router = APIRouter(prefix="/tasks", tags=["tasks"])
CALL_CENTER = (Role.OPERATOR, Role.SUPERVISOR, Role.ADMIN)
Agent = Annotated[User, Depends(require_roles(*CALL_CENTER))]
# TZ 3: the call-center lead redistributes the queue (move, cancel, reprioritise)
Supervisor = Annotated[User, Depends(require_roles(Role.SUPERVISOR, Role.ADMIN))]


class AiSuggestion(BaseModel):
    analysis_id: uuid.UUID
    call_id: uuid.UUID
    outcome: str | None
    reason: str | None
    summary: str | None
    next_step: str | None


class ScriptContext(BaseModel):
    """What the script placeholders [shifokor], [xizmat], [filial] refer to, in both languages
    (the script's language is chosen per call). [sana] / [vaqt] come from `appointment_at`."""

    doctor_uz: str | None = None
    doctor_ru: str | None = None
    services_uz: str | None = None
    services_ru: str | None = None
    branch_uz: str | None = None
    branch_ru: str | None = None


class TaskOut(BaseModel):
    id: uuid.UUID
    type: TaskType
    status: TaskStatus
    priority: int
    due_at: datetime
    overdue: bool
    attempts: int
    no_answer_count: int
    last_attempt_at: datetime | None
    outcome: Outcome | None
    outcome_reason: str | None
    note: str | None
    script_code: str | None
    patient_id: uuid.UUID | None
    patient_name: str | None
    patient_phone: str | None
    patient_language: str | None
    do_not_call: bool
    lead_id: uuid.UUID | None
    lead_channel: str | None
    appointment_id: uuid.UUID | None
    appointment_at: datetime | None
    recommendation_id: uuid.UUID | None = None
    recommendation_due: date | None = None
    campaign_id: uuid.UUID | None
    campaign_name: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
    completed_by_name: str | None = None
    cancel_reason: str | None = None
    context: ScriptContext = Field(default_factory=ScriptContext)
    ai_suggestion: AiSuggestion | None = None


class ResultIn(BaseModel):
    outcome: Outcome
    reason: str | None = Field(default=None, max_length=50)
    note: str | None = Field(default=None, max_length=2000)
    callback_at: datetime | None = None
    # the AI analysis the operator confirmed or corrected with this result (plan 4.4)
    analysis_id: uuid.UUID | None = None


class ManualTaskIn(BaseModel):
    patient_id: uuid.UUID
    due_at: datetime
    note: str | None = Field(default=None, max_length=2000)


class TaskUpdate(BaseModel):
    due_at: AwareDatetime | None = None  # with a zone: a bare time is ambiguous
    # lower = more urgent (the rule defaults run 4..45)
    priority: int | None = Field(default=None, ge=1, le=99)


class CancelIn(BaseModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=255)]


class ShiftNoteIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class ShiftNoteOut(BaseModel):
    id: uuid.UUID
    user_name: str | None
    text: str
    created_at: datetime


class CampaignCount(BaseModel):
    id: uuid.UUID
    name: str
    open: int


class Summary(BaseModel):
    by_type: dict[str, int]
    total_due: int
    overdue: int
    lead_sla_breached: int
    # campaigns with calls still to make (the queue's campaign filter)
    campaigns: list[CampaignCount] = Field(default_factory=list)


class AttemptOut(BaseModel):
    id: uuid.UUID
    outcome: Outcome
    reason: str | None
    note: str | None
    user_name: str | None
    automatic: bool
    created_at: datetime


class DoneBy(BaseModel):
    user_id: uuid.UUID | None
    name: str | None
    count: int


class DonePage(BaseModel):
    total: int
    items: list[TaskOut]
    by_user: list[DoneBy]


async def _names(session: SessionDep, model: type, ids: set) -> dict:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return {o.id: o for o in await session.scalars(select(model).where(model.id.in_(ids)))}


async def serialize(session: SessionDep, rows: list[Task]) -> list[TaskOut]:
    patients = await _names(session, Patient, {t.patient_id for t in rows})
    leads = await _names(session, Lead, {t.lead_id for t in rows})
    appts = await _names(session, Appointment, {t.appointment_id for t in rows})
    recs = await _names(session, Recommendation, {t.recommendation_id for t in rows})
    campaigns = await _names(session, Campaign, {t.campaign_id for t in rows})
    users = await _names(session, User, {t.completed_by for t in rows})
    doctors = await _names(
        session,
        Doctor,
        {a.doctor_id for a in appts.values()} | {r.doctor_id for r in recs.values()},
    )
    branches = await _names(session, Branch, {a.branch_id for a in appts.values()})
    services = await _names(
        session,
        Service,
        {s.service_id for a in appts.values() for s in a.services}
        | {r.service_id for r in recs.values()},
    )
    suggestions = await ai.suggestions_for_tasks(session, [t.id for t in rows])
    now = clinic_time.now()

    def context(appt: Appointment | None, rec: Recommendation | None) -> ScriptContext:
        doctor = doctors.get(appt.doctor_id if appt else rec.doctor_id if rec else None)
        branch = branches.get(appt.branch_id) if appt else None
        lines = (
            [services[s.service_id] for s in appt.services if s.service_id in services]
            if appt
            else [services[rec.service_id]]
            if rec and rec.service_id in services
            else []
        )
        return ScriptContext(
            doctor_uz=doctor.name_uz if doctor else None,
            doctor_ru=doctor.name_ru if doctor else None,
            services_uz=", ".join(s.name_uz for s in lines) or None,
            services_ru=", ".join(s.name_ru for s in lines) or None,
            branch_uz=branch.name_uz if branch else None,
            branch_ru=branch.name_ru if branch else None,
        )

    out = []
    for t in rows:
        p, lead = patients.get(t.patient_id), leads.get(t.lead_id)
        appt, rec = appts.get(t.appointment_id), recs.get(t.recommendation_id)
        campaign, closer = campaigns.get(t.campaign_id), users.get(t.completed_by)
        phone = next((ph.number for ph in (p.phones if p else []) if ph.is_primary), None)
        name = p.full_name if p else (lead.name if lead else None)
        out.append(
            TaskOut(
                id=t.id, type=t.type, status=t.status, priority=t.priority, due_at=t.due_at,
                overdue=t.status is TaskStatus.OPEN and t.due_at < now,
                attempts=t.attempts, no_answer_count=t.no_answer_count,
                last_attempt_at=t.last_attempt_at, outcome=t.outcome,
                outcome_reason=t.outcome_reason, note=t.note, script_code=t.script_code,
                patient_id=t.patient_id, patient_name=name,
                patient_phone=phone or (lead.phone if lead else None),
                patient_language=p.language.value if p else None,
                do_not_call=bool(p and p.do_not_call), lead_id=t.lead_id,
                lead_channel=lead.channel.value if lead else None, appointment_id=t.appointment_id,
                appointment_at=appt.starts_at if appt else None,
                recommendation_id=t.recommendation_id,
                recommendation_due=rec.due_date if rec else None,
                campaign_id=t.campaign_id, campaign_name=campaign.name if campaign else None,
                created_at=t.created_at, completed_at=t.completed_at,
                completed_by_name=closer.full_name if closer else None,
                cancel_reason=t.cancel_reason, context=context(appt, rec),
                ai_suggestion=suggestions.get(t.id),
            )
        )  # fmt: skip
    return out


async def _get_task(session: SessionDep, task_id: uuid.UUID) -> Task:
    task = await session.get(Task, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="task_not_found")
    return task


@router.get("")
async def list_tasks(
    session: SessionDep,
    _: Agent,
    view: Literal["today", "all"] = "today",
    types: Annotated[list[TaskType] | None, Query()] = None,
    campaign_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TaskOut]:
    _, end_of_today = clinic_time.day_bounds(clinic_time.today())
    until = end_of_today if view == "today" else clinic_time.now() + timedelta(days=3650)
    rows = await service.queue(
        session, until=until, types=types, campaign_id=campaign_id, limit=limit, offset=offset
    )
    return await serialize(session, rows)


@router.get("/summary")
async def summary(session: SessionDep, _: Agent) -> Summary:
    _, end = clinic_time.day_bounds(clinic_time.today())
    now = clinic_time.now()
    rows = await session.execute(
        select(Task.type, func.count())
        .where(Task.status == TaskStatus.OPEN, Task.due_at < end)
        .group_by(Task.type)
    )
    by_type = {t.value: n for t, n in rows}
    overdue = await session.scalar(
        select(func.count())
        .select_from(Task)
        .where(Task.status == TaskStatus.OPEN, Task.due_at < now)
    )
    breached = await session.scalar(
        select(func.count())
        .select_from(Lead)
        .where(Lead.first_response_at.is_(None), Lead.sla_due_at < now, Lead.stage == "new")
    )
    campaigns = await session.execute(
        select(Campaign.id, Campaign.name, func.count(Task.id))
        .join(Task, Task.campaign_id == Campaign.id)
        .where(Task.status == TaskStatus.OPEN)
        .group_by(Campaign.id, Campaign.name)
        .order_by(Campaign.name)
    )
    return Summary(
        by_type=by_type, total_due=sum(by_type.values()), overdue=overdue or 0,
        lead_sla_breached=breached or 0,
        campaigns=[CampaignCount(id=i, name=n, open=c) for i, n, c in campaigns],
    )  # fmt: skip


@router.get("/meta")
async def meta(_: Agent) -> dict[str, list[str]]:
    return {
        "outcomes": [o.value for o in Outcome],
        "reasons": list(REASONS),
        "types": [t.value for t in TaskType],
    }


@router.get("/done")
async def done_tasks(
    session: SessionDep,
    _: Agent,
    period: Literal["today", "week"] = "today",
    user_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DonePage:
    """Closed tasks of today or the last 7 days, optionally of one operator ("Bajarilganlar")."""
    today = clinic_time.today()
    start = clinic_time.day_bounds(today if period == "today" else today - timedelta(days=6))[0]
    base = [Task.status.in_((TaskStatus.DONE, TaskStatus.CANCELLED)), Task.completed_at >= start]
    by_user = [
        DoneBy(user_id=uid, name=name, count=n)
        for uid, name, n in await session.execute(
            select(Task.completed_by, User.full_name, func.count())
            .outerjoin(User, User.id == Task.completed_by)
            .where(*base)
            .group_by(Task.completed_by, User.full_name)
            .order_by(func.count().desc())
        )
    ]
    filters = [*base, Task.completed_by == user_id] if user_id else base
    total = await session.scalar(select(func.count()).select_from(Task).where(*filters))
    rows = await session.scalars(
        select(Task)
        .where(*filters)
        .order_by(Task.completed_at.desc(), Task.id)
        .limit(limit)
        .offset(offset)
    )
    return DonePage(total=total or 0, items=await serialize(session, list(rows)), by_user=by_user)


@router.get("/patient/{patient_id}")
async def patient_tasks(patient_id: uuid.UUID, session: SessionDep, _: Agent) -> list[TaskOut]:
    rows = await session.scalars(
        select(Task).where(Task.patient_id == patient_id).order_by(Task.created_at.desc()).limit(50)
    )
    return await serialize(session, list(rows))


@router.get("/{task_id}/attempts")
async def task_attempts(task_id: uuid.UUID, session: SessionDep, _: Agent) -> list[AttemptOut]:
    """Every call made from the task: who, when, with what result (newest first)."""
    task = await _get_task(session, task_id)
    rows = await session.execute(
        select(TaskAttempt, User.full_name)
        .outerjoin(User, User.id == TaskAttempt.user_id)
        .where(TaskAttempt.task_id == task.id)
        .order_by(TaskAttempt.created_at.desc())
    )
    return [
        AttemptOut(
            id=a.id,
            outcome=a.outcome,
            reason=a.reason,
            note=a.note,
            user_name=name,
            automatic=a.automatic,
            created_at=a.created_at,
        )  # fmt: skip
        for a, name in rows
    ]


@router.post("/{task_id}/result")
async def record_result(
    task_id: uuid.UUID, body: ResultIn, request: Request, session: SessionDep, user: Agent
) -> TaskOut:
    task = await _get_task(session, task_id)
    if body.reason and body.reason not in REASONS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="unknown_reason")
    try:
        await service.record_result(
            session, task, user_id=user.id, outcome=body.outcome, reason=body.reason,
            note=body.note, callback_at=body.callback_at, analysis_id=body.analysis_id,
        )  # fmt: skip
    except service.TaskError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=exc.code) from None
    except SchedulingError as exc:  # raised by the confirm rule, e.g. the slot was taken meanwhile
        raise HTTPException(status.HTTP_409_CONFLICT, detail=exc.code) from None
    audit.record(
        session, "task.result", user_id=user.id, entity="task", entity_id=task.id,
        after=body.model_dump(mode="json"), ip=client_ip(request),
    )  # fmt: skip
    await session.commit()
    return (await serialize(session, [task]))[0]


@router.patch("/{task_id}")
async def update_task(
    task_id: uuid.UUID, body: TaskUpdate, request: Request, session: SessionDep, user: Supervisor
) -> TaskOut:
    """Supervisor: move an open task to another time and / or change its priority."""
    task = await _get_task(session, task_id)
    before = {"due_at": task.due_at.isoformat(), "priority": task.priority}
    try:
        if body.due_at is not None:
            await service.reschedule(session, task, body.due_at, user_id=user.id)
        if body.priority is not None:
            await service.set_priority(session, task, body.priority, user_id=user.id)
    except service.TaskError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=exc.code) from None
    audit.record(
        session, "task.update", user_id=user.id, entity="task", entity_id=task.id,
        before=before, after=body.model_dump(mode="json", exclude_none=True),
        ip=client_ip(request),
    )  # fmt: skip
    await session.commit()
    return (await serialize(session, [task]))[0]


@router.post("/{task_id}/cancel")
async def cancel_task(
    task_id: uuid.UUID, body: CancelIn, request: Request, session: SessionDep, user: Supervisor
) -> TaskOut:
    """Supervisor: take a task off the queue without calling, with a reason."""
    task = await _get_task(session, task_id)
    try:
        await service.cancel(session, task, reason=body.reason, user_id=user.id)
    except service.TaskError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=exc.code) from None
    audit.record(
        session, "task.cancel", user_id=user.id, entity="task", entity_id=task.id,
        after={"reason": body.reason}, ip=client_ip(request),
    )  # fmt: skip
    await session.commit()
    return (await serialize(session, [task]))[0]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_callback(body: ManualTaskIn, session: SessionDep, user: Agent) -> dict[str, bool]:
    if await session.get(Patient, body.patient_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="patient_not_found")
    created = await service.create_task(
        session, TaskType.CALLBACK, due_at=body.due_at, patient_id=body.patient_id, note=body.note
    )
    await session.commit()
    return {"created": created}


@router.get("/shift-notes")
async def shift_notes(
    session: SessionDep, _: Agent, since: date | None = None
) -> list[ShiftNoteOut]:
    stmt = (
        select(ShiftNote, User.full_name)
        .outerjoin(User, User.id == ShiftNote.user_id)
        .order_by(ShiftNote.created_at.desc())
        .limit(10)
    )
    if since:
        if not 2000 <= since.year <= 2100:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="bad_range")
        stmt = stmt.where(ShiftNote.created_at >= clinic_time.day_bounds(since)[0])
    rows = await session.execute(stmt)
    return [
        ShiftNoteOut(id=n.id, user_name=name, text=n.text, created_at=n.created_at)
        for n, name in rows
    ]


@router.post("/shift-notes", status_code=status.HTTP_201_CREATED)
async def add_shift_note(body: ShiftNoteIn, session: SessionDep, user: Agent) -> ShiftNoteOut:
    note = ShiftNote(user_id=user.id, text=body.text, created_at=clinic_time.now())
    session.add(note)
    await session.commit()
    return ShiftNoteOut(
        id=note.id, user_name=user.full_name, text=note.text, created_at=note.created_at
    )
