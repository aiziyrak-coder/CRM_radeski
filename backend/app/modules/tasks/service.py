"""Task queue: creation (idempotent), results, auto-closing (TZ 4.5)."""

import uuid
from datetime import datetime, time, timedelta

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clinic_time
from app.core.config import get_settings
from app.core.events import emit
from app.modules.patients import service as patients_service
from app.modules.patients.models import Patient
from app.modules.tasks.models import (
    OUTBOUND_TYPES,
    REACHED,
    TASK_DEFAULTS,
    Outcome,
    Task,
    TaskAttempt,
    TaskStatus,
    TaskType,
)

# retry ladder, lead SLA etc. are settings (config.py "Task queue rules"), not constants


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
    outcome: Outcome | None,
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
    analysis_id: uuid.UUID | None = None,
) -> Task:
    """Stores an attempt and moves the task on: retry, reschedule a callback, or close it."""
    # two submits of the same task (double click, two operators) must not both apply:
    # lock the row and re-read it, the second one then sees the task closed
    await session.refresh(task, with_for_update=True)
    if task.status is not TaskStatus.OPEN:
        raise TaskError("task_closed")
    if outcome is Outcome.CALLBACK and callback_at is None:
        raise TaskError("callback_time_required")
    if outcome in (Outcome.REFUSED, Outcome.CANCELLED) and not reason:
        raise TaskError("reason_required")

    settings = get_settings()
    retry_next_day_at = time(settings.task_retry_next_day_hour)
    now = clinic_time.now()
    task.attempts += 1
    task.last_attempt_at = now
    if outcome is Outcome.NO_ANSWER:
        task.no_answer_count += 1
    elif outcome in REACHED:
        task.no_answer_count = 0  # we got through: the ladder starts over next time
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

    if outcome is Outcome.NO_ANSWER and task.no_answer_count < settings.task_max_no_answer:
        # TZ 4.5: retry in 2 hours, then the next working day (3 unanswered attempts in total)
        retry = (
            now + timedelta(minutes=settings.task_retry_after_minutes)
            if task.no_answer_count == 1
            else None
        )
        if retry is None or not clinic_time.is_open(retry):
            retry = clinic_time.next_workday_at(clinic_time.local(now).date(), retry_next_day_at)
        task.due_at = retry
    elif outcome is Outcome.CALLBACK:
        task.due_at = callback_at  # stays open, reappears at the promised time
        task.outcome = outcome
    elif outcome is Outcome.THINKING and task.outcome is not Outcome.THINKING:
        # a warm contact must not be dropped: one follow-up call, then the result is final
        if callback_at is None:
            callback_at = clinic_time.now()
            for _ in range(settings.task_thinking_workdays):
                callback_at = clinic_time.next_workday_at(
                    clinic_time.local(callback_at).date(), retry_next_day_at
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
    # subscribers: `task.no_answer_count` is the number of unanswered attempts in a row
    # (TZ 4.5 message after the 2nd one); `task.attempts` also counts answered calls
    await emit(
        session, "task.result", task=task, outcome=outcome, reason=reason, user_id=user_id,
        analysis_id=analysis_id, no_answer_count=task.no_answer_count,
    )  # fmt: skip
    return task


# --- supervisor actions (TZ 4.5: the call-center lead redistributes the queue) ---------------


async def _lock_open(session: AsyncSession, task: Task) -> None:
    await session.refresh(task, with_for_update=True)
    if task.status is not TaskStatus.OPEN:
        raise TaskError("task_closed")


async def reschedule(
    session: AsyncSession, task: Task, due_at: datetime, *, user_id: uuid.UUID
) -> None:
    """Moves an open task to another time (it leaves / joins today's queue accordingly)."""
    await _lock_open(session, task)
    old = task.due_at
    task.due_at = due_at
    await session.flush()
    await emit(session, "task.rescheduled", task=task, old=old, user_id=user_id)


async def set_priority(
    session: AsyncSession, task: Task, priority: int, *, user_id: uuid.UUID
) -> None:
    await _lock_open(session, task)
    old = task.priority
    task.priority = priority
    await session.flush()
    await emit(session, "task.priority_changed", task=task, old=old, user_id=user_id)


async def cancel(session: AsyncSession, task: Task, *, reason: str, user_id: uuid.UUID) -> None:
    """Takes a task off the queue without a call (e.g. duplicate, patient already handled)."""
    await _lock_open(session, task)
    task.status = TaskStatus.CANCELLED
    task.cancel_reason = reason
    task.completed_at = clinic_time.now()
    task.completed_by = user_id
    await session.flush()
    await emit(session, "task.cancelled", task=task, reason=reason, user_id=user_id)


async def queue(
    session: AsyncSession,
    *,
    until: datetime,
    types: list[TaskType] | None = None,
    campaign_id: uuid.UUID | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Task]:
    stmt = select(Task).where(Task.status == TaskStatus.OPEN, Task.due_at <= until)
    if types:
        stmt = stmt.where(Task.type.in_(types))
    if campaign_id:
        stmt = stmt.where(Task.campaign_id == campaign_id)
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
