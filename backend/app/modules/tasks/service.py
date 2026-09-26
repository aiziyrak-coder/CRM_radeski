"""Task queue: creation (idempotent), results, auto-closing (TZ 4.5)."""

import uuid
from datetime import datetime, time, timedelta

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clinic_time
from app.core.events import emit
from app.modules.patients import service as patients_service
from app.modules.patients.models import Patient
from app.modules.tasks.models import (
    OUTBOUND_TYPES,
    TASK_DEFAULTS,
    Outcome,
    Task,
    TaskAttempt,
    TaskStatus,
    TaskType,
)

MAX_ATTEMPTS = 3  # TZ 4.5: then the task is closed as "no answer"
RETRY_AFTER_FIRST = timedelta(hours=2)
RETRY_NEXT_DAY_AT = time(10, 0)
THINKING_WORKDAYS = 2  # "o'ylab ko'raman" -> call back in two working days unless agreed otherwise


class TaskError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


async def create_task(
    session: AsyncSession,
    type_: TaskType,
    *,
    due_at: datetime,
    patient_id: uuid.UUID | None = None,
    lead_id: uuid.UUID | None = None,
    appointment_id: uuid.UUID | None = None,
    recommendation_id: uuid.UUID | None = None,
    campaign_id: uuid.UUID | None = None,
    dedupe_key: str | None = None,
    note: str | None = None,
    script_code: str | None = None,
    priority: int | None = None,
) -> bool:
    """False if a task with the same dedupe key already exists (generators re-run safely)."""
    if patient_id and type_ in OUTBOUND_TYPES:
        patient = await session.get(Patient, patient_id)
        if patient is None or patient.do_not_call:
            return False
    default_priority, default_script = TASK_DEFAULTS[type_]
    stmt = (
        insert(Task)
        .values(
            id=uuid.uuid4(),
            type=type_,
            status=TaskStatus.OPEN,
            priority=priority if priority is not None else default_priority,
            due_at=due_at,
            patient_id=patient_id,
            lead_id=lead_id,
            appointment_id=appointment_id,
            recommendation_id=recommendation_id,
            campaign_id=campaign_id,
            script_code=script_code or default_script,
            note=note,
            attempts=0,
            dedupe_key=dedupe_key,
            created_at=clinic_time.now(),
        )
        .on_conflict_do_nothing(index_elements=["dedupe_key"])
        .returning(Task.id)
    )
    created = await session.scalar(stmt)
    return created is not None


async def close_open(
    session: AsyncSession,
    *,
    types: tuple[TaskType, ...],
    patient_id: uuid.UUID | None = None,
    appointment_id: uuid.UUID | None = None,
    lead_id: uuid.UUID | None = None,
    outcome: Outcome,
    status: TaskStatus = TaskStatus.DONE,
) -> int:
    filters = [Task.status == TaskStatus.OPEN, Task.type.in_(types)]
    if patient_id:
        filters.append(Task.patient_id == patient_id)
    if appointment_id:
        filters.append(Task.appointment_id == appointment_id)
    if lead_id:
        filters.append(Task.lead_id == lead_id)
    result = await session.execute(
        update(Task)
        .where(*filters)
        .values(status=status, outcome=outcome, completed_at=clinic_time.now())
        .execution_options(synchronize_session=False)
    )
    return result.rowcount or 0


async def record_result(
    session: AsyncSession,
    task: Task,
    *,
    user_id: uuid.UUID,
    outcome: Outcome,
    reason: str | None = None,
    note: str | None = None,
    callback_at: datetime | None = None,
) -> Task:
    """Stores an attempt and moves the task on: retry, reschedule a callback, or close it."""
    if task.status is not TaskStatus.OPEN:
        raise TaskError("task_closed")
    if outcome is Outcome.CALLBACK and callback_at is None:
        raise TaskError("callback_time_required")
    if outcome in (Outcome.REFUSED, Outcome.CANCELLED) and not reason:
        raise TaskError("reason_required")

    now = clinic_time.now()
    task.attempts += 1
    task.last_attempt_at = now
    session.add(
        TaskAttempt(
            task_id=task.id,
            task_type=task.type,
            user_id=user_id,
            patient_id=task.patient_id,
            outcome=outcome,
            reason=reason,
            note=note,
            created_at=now,
        )
    )
    if note:
        task.note = f"{task.note}\n{note}" if task.note else note

    if outcome is Outcome.NO_ANSWER and task.attempts < MAX_ATTEMPTS:
        # TZ 4.5: retry in 2 hours, then the next working day
        retry = now + RETRY_AFTER_FIRST if task.attempts == 1 else None
        if retry is None or not clinic_time.is_open(retry):
            retry = clinic_time.next_workday_at(clinic_time.local(now).date(), RETRY_NEXT_DAY_AT)
        task.due_at = retry
    elif outcome is Outcome.CALLBACK:
        task.due_at = callback_at  # stays open, reappears at the promised time
        task.outcome = outcome
    elif outcome is Outcome.THINKING and task.outcome is not Outcome.THINKING:
        # a warm contact must not be dropped: one follow-up call, then the result is final
        if callback_at is None:
            callback_at = clinic_time.now()
            for _ in range(THINKING_WORKDAYS):
                callback_at = clinic_time.next_workday_at(
                    clinic_time.local(callback_at).date(), RETRY_NEXT_DAY_AT
                )
        task.due_at = callback_at
        task.outcome = outcome
        task.outcome_reason = reason
    else:
        task.status = TaskStatus.DONE
        task.outcome = outcome
        task.outcome_reason = reason
        task.completed_at = now
        task.completed_by = user_id

    if outcome is Outcome.DO_NOT_CALL and task.patient_id:
        patient = await session.get(Patient, task.patient_id)
        if patient:
            patient.do_not_call = True
            patient.do_not_call_reason = reason or note
            await close_open(
                session,
                types=OUTBOUND_TYPES,
                patient_id=patient.id,
                outcome=Outcome.DO_NOT_CALL,
                status=TaskStatus.CANCELLED,
            )

    await session.flush()
    await emit(session, "task.result", task=task, outcome=outcome, reason=reason, user_id=user_id)
    return task


async def queue(
    session: AsyncSession,
    *,
    until: datetime,
    types: list[TaskType] | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Task]:
    stmt = select(Task).where(Task.status == TaskStatus.OPEN, Task.due_at <= until)
    if types:
        stmt = stmt.where(Task.type.in_(types))
    stmt = stmt.order_by(Task.priority, Task.due_at).limit(limit).offset(offset)
    return list(await session.scalars(stmt))


async def _merge_patients(session: AsyncSession, target: uuid.UUID, source: uuid.UUID) -> None:
    # one open call per purpose: the survivor's task wins over the duplicate's
    target_types = select(Task.type).where(
        Task.patient_id == target, Task.status == TaskStatus.OPEN
    )
    await session.execute(
        update(Task)
        .where(
            Task.patient_id == source,
            Task.status == TaskStatus.OPEN,
            Task.type.in_(target_types),
        )
        .values(status=TaskStatus.CANCELLED, completed_at=clinic_time.now())
    )
    for model in (Task, TaskAttempt):
        await session.execute(
            update(model).where(model.patient_id == source).values(patient_id=target)
        )


patients_service.MERGE_HOOKS.append(_merge_patients)
