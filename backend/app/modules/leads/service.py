"""Inquiries: intake from any channel, SLA, patient matching (TZ 4.4)."""

import uuid

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import object_session

from app.core import clinic_time
from app.core.config import get_settings
from app.core.events import emit
from app.core.text import search_key
from app.modules.leads.models import Lead, LeadChannel, LeadStage, LeadStageChange
from app.modules.patients import service as patients_service
from app.modules.patients.models import Patient, PatientKind, PatientPhone, Source
from app.modules.tasks.models import REASONS

# a lost inquiry's reason: the TZ 4.5 list, or the call result that ended it
LOST_REASONS = (*REASONS, "refused", "wrong_number", "do_not_call")

# TZ 4.4: the ad source is mandatory. Staff type it in; inquiries that arrive by themselves get
# it from the channel they came through.
CHANNEL_SOURCE: dict[LeadChannel, Source] = {
    LeadChannel.WEBSITE: Source.WEBSITE,
    LeadChannel.TELEGRAM: Source.TELEGRAM,
    LeadChannel.INSTAGRAM: Source.INSTAGRAM,
}


def default_source(channel: LeadChannel, patient: Patient | None) -> Source:
    """A call from a number we already know is a returning patient (or their first source);
    an unknown caller's source is asked for when the operator calls back."""
    if channel in CHANNEL_SOURCE:
        return CHANNEL_SOURCE[channel]
    if patient is not None and patient.kind in (PatientKind.ACTIVE, PatientKind.LEGACY):
        return Source.RETURNING
    if patient is not None and patient.source is not None:
        return patient.source
    return Source.OTHER


def _history(
    session: AsyncSession | None,
    lead: Lead,
    old: LeadStage | None,
    new: LeadStage,
    *,
    user_id: uuid.UUID | None = None,
    reason: str | None = None,
) -> None:
    target = session.sync_session if session is not None else object_session(lead)
    if target is None:  # a lead that was never added to a session has no history to keep
        return
    target.add(
        LeadStageChange(
            lead_id=lead.id, old_stage=old, new_stage=new, reason=reason, user_id=user_id,
            created_at=clinic_time.now(),
        )
    )  # fmt: skip


class LeadError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


async def find_patient_by_phone(session: AsyncSession, phone: str | None) -> Patient | None:
    if not phone:
        return None
    return await session.scalar(
        select(Patient)
        .join(PatientPhone)
        .where(PatientPhone.number == phone, Patient.merged_into_id.is_(None))
        .order_by(Patient.kind == PatientKind.COLD, Patient.created_at)  # prefer real patients
        .limit(1)
    )


async def create_lead(
    session: AsyncSession,
    *,
    channel: LeadChannel,
    phone: str | None,
    name: str | None = None,
    source: Source | None = None,
    interest: str | None = None,
    note: str | None = None,
    external_id: str | None = None,
    created_by: uuid.UUID | None = None,
) -> tuple[Lead, bool]:
    """Returns (lead, created). An external_id seen before returns the existing lead."""
    if external_id:
        existing = await session.scalar(select(Lead).where(Lead.external_id == external_id))
        if existing:
            return existing, False
    patient = await find_patient_by_phone(session, phone)
    now = clinic_time.now()
    lead = Lead(
        patient_id=patient.id if patient else None,
        phone=phone,
        name=name or (patient.full_name if patient else None),
        channel=channel,
        source=source or default_source(channel, patient),
        interest=interest,
        note=note,
        stage=LeadStage.NEW,
        # TZ 4.4: first answer within 15 working minutes
        sla_due_at=clinic_time.add_working_minutes(now, get_settings().lead_sla_minutes),
        external_id=external_id,
        created_by=created_by,
    )
    try:
        async with session.begin_nested():
            session.add(lead)
            await session.flush()
    except IntegrityError:
        # the same form delivered twice at once: the other request stored it first
        existing = (
            await session.scalar(select(Lead).where(Lead.external_id == external_id))
            if external_id
            else None
        )
        if existing is None:
            raise
        return existing, False
    _history(session, lead, None, LeadStage.NEW, user_id=created_by)
    await emit(session, "lead.created", lead=lead)
    return lead, True


async def ensure_patient(session: AsyncSession, lead: Lead, user_id: uuid.UUID | None) -> Patient:
    """Booking needs a patient card: reuse the matched one or create a LEAD-kind patient."""
    if lead.patient_id:
        patient = await session.get(Patient, lead.patient_id)
        if patient and not patient.merged_into_id:
            return patient
        if patient and patient.merged_into_id:
            lead.patient_id = patient.merged_into_id
            return await session.get(Patient, patient.merged_into_id)  # type: ignore[return-value]
    name = (lead.name or "").strip() or "Ismi noma'lum"
    patient = Patient(
        full_name=name,
        search_key=search_key(name),
        kind=PatientKind.LEAD,
        source=lead.source,
        tags=[],
        created_by=user_id,
        phones=[PatientPhone(number=lead.phone, is_primary=True)] if lead.phone else [],
        conditions=[],
    )
    session.add(patient)
    await session.flush()
    lead.patient_id = patient.id
    # tasks created for the bare inquiry now belong to the patient (timeline, auto-closing)
    from app.modules.tasks.models import Task, TaskAttempt

    task_ids = select(Task.id).where(Task.lead_id == lead.id).scalar_subquery()
    await session.execute(
        update(TaskAttempt)
        .where(TaskAttempt.task_id.in_(task_ids), TaskAttempt.patient_id.is_(None))
        .values(patient_id=patient.id)
    )
    await session.execute(
        update(Task)
        .where(Task.lead_id == lead.id, Task.patient_id.is_(None))
        .values(patient_id=patient.id)
    )
    return patient


def mark_contacted(lead: Lead, user_id: uuid.UUID | None = None) -> None:
    if lead.first_response_at is None:
        lead.first_response_at = clinic_time.now()
    if lead.stage is LeadStage.NEW:
        lead.stage = LeadStage.CONTACTED
        _history(None, lead, LeadStage.NEW, LeadStage.CONTACTED, user_id=user_id)


async def change_stage(
    session: AsyncSession,
    lead: Lead,
    stage: LeadStage,
    *,
    lost_reason: str | None = None,
    user_id: uuid.UUID | None = None,
    contacted: bool = True,
) -> None:
    """The only way a lead moves between stages; task rules react to `lead.stage_changed`
    (e.g. a lost or booked inquiry no longer needs its open calls). `contacted=False` when
    nobody actually spoke to the person (a wrong number is not a first response)."""
    if lost_reason is not None and lost_reason not in LOST_REASONS:
        raise LeadError("unknown_reason")
    if stage is LeadStage.LOST:
        lost_reason = lost_reason or lead.lost_reason
        if not lost_reason:
            raise LeadError("reason_required")
        lead.lost_reason = lost_reason
    elif lost_reason is not None:
        lead.lost_reason = lost_reason
    old = lead.stage
    if contacted and stage is not LeadStage.NEW:
        mark_contacted(lead, user_id)
    current = lead.stage  # mark_contacted may have logged new -> contacted already
    lead.stage = stage
    if current is not stage:
        _history(
            session, lead, current, stage, user_id=user_id,
            reason=lost_reason if stage is LeadStage.LOST else None,
        )  # fmt: skip
    if old is stage:
        return
    await emit(session, "lead.stage_changed", lead=lead, old=old, new=stage, user_id=user_id)


async def _merge_patients(session: AsyncSession, target: uuid.UUID, source: uuid.UUID) -> None:
    await session.execute(update(Lead).where(Lead.patient_id == source).values(patient_id=target))


patients_service.MERGE_HOOKS.append(_merge_patients)
