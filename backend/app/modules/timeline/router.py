"""Patient card timeline (plan 2.5): every touchpoint with the patient in one feed."""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.deps import CurrentUser, SessionDep
from app.modules.catalog.models import Doctor, Service
from app.modules.leads.models import Lead
from app.modules.patients.models import Patient, PatientKind
from app.modules.scheduling.models import Appointment, Recommendation
from app.modules.tasks.models import Task, TaskAttempt, TaskStatus
from app.modules.telephony.models import Call, RecordingStatus
from app.modules.users.models import Role, User

router = APIRouter(prefix="/patients", tags=["timeline"])

PER_SOURCE = 100
# call notes are call-center material; doctors see the medical part of the history
SEES_CALLS = (Role.OPERATOR, Role.SUPERVISOR, Role.REGISTRAR, Role.OWNER, Role.ADMIN)

Kind = Literal[
    "registered", "legacy_visit", "lead", "appointment", "call", "planned_call", "recommendation",
    "phone",
]  # fmt: skip


class Event(BaseModel):
    kind: Kind
    at: datetime
    status: str | None = None  # appointment status, lead stage, call outcome, recommendation status
    title: str | None = None  # doctor, channel or task type
    detail: str | None = None  # services, interest or note
    reason: str | None = None
    user: str | None = None
    ref: uuid.UUID | None = None  # phone: the call id (recording)
    seconds: int | None = None  # phone: talk time


@router.get("/{patient_id}/timeline")
async def timeline(
    patient_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
    lang: Literal["uz", "ru"] = "uz",
) -> list[Event]:
    patient = await session.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="patient_not_found")

    def name(o: Doctor | Service) -> str:
        return o.name_ru if lang == "ru" else o.name_uz

    events: list[Event] = []
    if patient.kind in (PatientKind.LEGACY, PatientKind.COLD):
        # import time is meaningless for old records; the last known visit is what matters
        if patient.last_visit_at:
            events.append(Event(kind="legacy_visit", at=patient.last_visit_at))
    else:
        events.append(
            Event(
                kind="registered",
                at=patient.created_at,
                title=patient.source.value if patient.source else None,
            )
        )

    appts = list(
        await session.scalars(
            select(Appointment)
            .where(Appointment.patient_id == patient_id)
            .options(selectinload(Appointment.services))
            .order_by(Appointment.starts_at.desc())
            .limit(PER_SOURCE)
        )
    )
    recs = list(
        await session.scalars(
            select(Recommendation)
            .where(Recommendation.patient_id == patient_id)
            .order_by(Recommendation.created_at.desc())
            .limit(PER_SOURCE)
        )
    )
    doctor_ids = {a.doctor_id for a in appts} | {r.doctor_id for r in recs if r.doctor_id}
    service_ids = {s.service_id for a in appts for s in a.services} | {
        r.service_id for r in recs if r.service_id
    }
    doctors = (
        {d.id: d for d in await session.scalars(select(Doctor).where(Doctor.id.in_(doctor_ids)))}
        if doctor_ids
        else {}
    )
    services = (
        {s.id: s for s in await session.scalars(select(Service).where(Service.id.in_(service_ids)))}
        if service_ids
        else {}
    )
    for a in appts:
        doctor = doctors.get(a.doctor_id)
        events.append(
            Event(
                kind="appointment",
                at=a.starts_at,
                status=a.status.value,
                title=name(doctor) if doctor else None,
                detail=", ".join(
                    name(services[s.service_id]) for s in a.services if s.service_id in services
                )
                or None,
                reason=a.cancel_reason,
            )
        )
    for r in recs:
        doctor = doctors.get(r.doctor_id) if r.doctor_id else None
        service = services.get(r.service_id) if r.service_id else None
        events.append(
            Event(
                kind="recommendation",
                at=r.created_at,
                status=r.status.value,
                title=name(doctor) if doctor else None,
                detail=" — ".join(x for x in (name(service) if service else None, r.note) if x)
                or None,
                reason=r.due_date.isoformat(),
            )
        )

    for lead in await session.scalars(
        select(Lead)
        .where(Lead.patient_id == patient_id)
        .order_by(Lead.created_at.desc())
        .limit(PER_SOURCE)
    ):
        events.append(
            Event(
                kind="lead",
                at=lead.created_at,
                status=lead.stage.value,
                title=lead.channel.value,
                detail=lead.interest,
                reason=lead.lost_reason,
            )
        )

    if user.role in SEES_CALLS:
        attempts = await session.execute(
            select(TaskAttempt, User.full_name)
            .outerjoin(User, User.id == TaskAttempt.user_id)
            .where(TaskAttempt.patient_id == patient_id)
            .order_by(TaskAttempt.created_at.desc())
            .limit(PER_SOURCE)
        )
        for attempt, user_name in attempts:
            events.append(
                Event(
                    kind="call",
                    at=attempt.created_at,
                    status=attempt.outcome.value,
                    title=attempt.task_type.value,
                    detail=attempt.note,
                    reason=attempt.reason,
                    user=user_name,
                )
            )
        for task in await session.scalars(
            select(Task)
            .where(Task.patient_id == patient_id, Task.status == TaskStatus.OPEN)
            .order_by(Task.due_at)
            .limit(PER_SOURCE)
        ):
            events.append(
                Event(kind="planned_call", at=task.due_at, title=task.type.value, detail=task.note)
            )

        phone_calls = await session.execute(
            select(Call, User.full_name)
            .outerjoin(User, User.id == Call.user_id)
            .where(Call.patient_id == patient_id)
            .order_by(Call.started_at.desc())
            .limit(PER_SOURCE)
        )
        for call, user_name in phone_calls:
            events.append(
                Event(
                    kind="phone",
                    at=call.started_at,
                    status=call.status.value,
                    title=call.direction.value,
                    user=user_name,
                    ref=call.id if call.recording_status is RecordingStatus.READY else None,
                    seconds=call.talk_seconds,
                )
            )

    events.sort(key=lambda e: e.at, reverse=True)
    return events
