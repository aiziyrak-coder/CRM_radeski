"""Inquiries: intake from any channel, SLA, patient matching (TZ 4.4)."""

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clinic_time
from app.core.events import emit
from app.core.text import search_key
from app.modules.leads.models import Lead, LeadChannel, LeadStage
from app.modules.patients import service as patients_service
from app.modules.patients.models import Patient, PatientKind, PatientPhone, Source

SLA_MINUTES = 15  # TZ 4.4: first answer within 15 working minutes


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
        source=source,
        interest=interest,
        note=note,
        stage=LeadStage.NEW,
        sla_due_at=clinic_time.add_working_minutes(now, SLA_MINUTES),
        external_id=external_id,
        created_by=created_by,
    )
    session.add(lead)
    await session.flush()
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


def mark_contacted(lead: Lead) -> None:
    if lead.first_response_at is None:
        lead.first_response_at = clinic_time.now()
    if lead.stage is LeadStage.NEW:
        lead.stage = LeadStage.CONTACTED


async def _merge_patients(session: AsyncSession, target: uuid.UUID, source: uuid.UUID) -> None:
    await session.execute(update(Lead).where(Lead.patient_id == source).values(patient_id=target))


patients_service.MERGE_HOOKS.append(_merge_patients)
