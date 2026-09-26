import uuid
from datetime import date, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.core import clinic_time
from app.core.deps import SessionDep, client_ip, require_roles
from app.modules.audit import service as audit
from app.modules.leads.models import Lead
from app.modules.patients.models import Patient
from app.modules.scheduling.models import Appointment
from app.modules.scheduling.service import SchedulingError
from app.modules.tasks import service
from app.modules.tasks.models import (
    REASONS,
    Outcome,
    ShiftNote,
    Task,
    TaskStatus,
    TaskType,
)
from app.modules.users.models import Role, User

router = APIRouter(prefix="/tasks", tags=["tasks"])
CALL_CENTER = (Role.OPERATOR, Role.SUPERVISOR, Role.ADMIN)
Agent = Annotated[User, Depends(require_roles(*CALL_CENTER))]


class TaskOut(BaseModel):
    id: uuid.UUID
    type: TaskType
    status: TaskStatus
    priority: int
    due_at: datetime
    overdue: bool
    attempts: int
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
    campaign_id: uuid.UUID | None
    created_at: datetime


class ResultIn(BaseModel):
    outcome: Outcome
    reason: str | None = Field(default=None, max_length=50)
    note: str | None = Field(default=None, max_length=2000)
    callback_at: datetime | None = None


class ManualTaskIn(BaseModel):
    patient_id: uuid.UUID
    due_at: datetime
    note: str | None = Field(default=None, max_length=2000)


class ShiftNoteIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class ShiftNoteOut(BaseModel):
    id: uuid.UUID
    user_name: str | None
    text: str
    created_at: datetime


class Summary(BaseModel):
    by_type: dict[str, int]
    total_due: int
    overdue: int
    lead_sla_breached: int


async def serialize(session: SessionDep, rows: list[Task]) -> list[TaskOut]:
    patients = {
        p.id: p
        for p in await session.scalars(
            select(Patient).where(Patient.id.in_({t.patient_id for t in rows if t.patient_id}))
        )
    }
    lead_rows = await session.scalars(
        select(Lead).where(Lead.id.in_({t.lead_id for t in rows if t.lead_id}))
    )
    leads = {lead.id: lead for lead in lead_rows}
    appts = {
        a.id: a
        for a in await session.scalars(
            select(Appointment).where(
                Appointment.id.in_({t.appointment_id for t in rows if t.appointment_id})
            )
        )
    }
    now = clinic_time.now()
    out = []
    for t in rows:
        p, lead, appt = (
            patients.get(t.patient_id),
            leads.get(t.lead_id),
            appts.get(t.appointment_id),
        )
        phone = next((ph.number for ph in (p.phones if p else []) if ph.is_primary), None)
        name = p.full_name if p else (lead.name if lead else None)
        out.append(
            TaskOut(
                id=t.id, type=t.type, status=t.status, priority=t.priority, due_at=t.due_at,
                overdue=t.status is TaskStatus.OPEN and t.due_at < now,
                attempts=t.attempts, last_attempt_at=t.last_attempt_at, outcome=t.outcome,
                outcome_reason=t.outcome_reason, note=t.note, script_code=t.script_code,
                patient_id=t.patient_id, patient_name=name,
                patient_phone=phone or (lead.phone if lead else None),
                patient_language=p.language.value if p else None,
                do_not_call=bool(p and p.do_not_call), lead_id=t.lead_id,
                lead_channel=lead.channel.value if lead else None, appointment_id=t.appointment_id,
                appointment_at=appt.starts_at if appt else None, campaign_id=t.campaign_id,
                created_at=t.created_at,
            )
        )  # fmt: skip
    return out


@router.get("")
async def list_tasks(
    session: SessionDep,
    _: Agent,
    view: Literal["today", "all"] = "today",
    types: Annotated[list[TaskType] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TaskOut]:
    _, end_of_today = clinic_time.day_bounds(clinic_time.today())
    until = end_of_today if view == "today" else clinic_time.now() + timedelta(days=3650)
    rows = await service.queue(session, until=until, types=types, limit=limit, offset=offset)
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
    return Summary(
        by_type=by_type, total_due=sum(by_type.values()), overdue=overdue or 0,
        lead_sla_breached=breached or 0,
    )  # fmt: skip


@router.get("/meta")
async def meta(_: Agent) -> dict[str, list[str]]:
    return {
        "outcomes": [o.value for o in Outcome],
        "reasons": list(REASONS),
        "types": [t.value for t in TaskType],
    }


@router.get("/patient/{patient_id}")
async def patient_tasks(patient_id: uuid.UUID, session: SessionDep, _: Agent) -> list[TaskOut]:
    rows = await session.scalars(
        select(Task).where(Task.patient_id == patient_id).order_by(Task.created_at.desc()).limit(50)
    )
    return await serialize(session, list(rows))


@router.post("/{task_id}/result")
async def record_result(
    task_id: uuid.UUID, body: ResultIn, request: Request, session: SessionDep, user: Agent
) -> TaskOut:
    task = await session.get(Task, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="task_not_found")
    if body.reason and body.reason not in REASONS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="unknown_reason")
    try:
        await service.record_result(
            session, task, user_id=user.id, outcome=body.outcome, reason=body.reason,
            note=body.note, callback_at=body.callback_at,
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
