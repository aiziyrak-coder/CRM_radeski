import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UUIDPk, str_enum


class TaskType(enum.StrEnum):
    """TZ 4.5 — the eleven reasons an operator calls someone."""

    CONFIRM_VISIT = "confirm_visit"
    MISSED_CALL = "missed_call"
    NEW_LEAD = "new_lead"
    LOST_LEAD = "lost_lead"
    NO_SHOW = "no_show"
    REPEAT_VISIT = "repeat_visit"
    POST_PROCEDURE = "post_procedure"
    COURSE_CONTINUE = "course_continue"
    REACTIVATION = "reactivation"
    CAMPAIGN = "campaign"
    CALLBACK = "callback"


# default priority (lower = more urgent) and the script shown for each type (TZ 4.5, 4.6).
# TZ 4.5: today's confirmations and missed calls first, then new inquiries, no-shows and repeat
# visits; campaigns and the cold base last
TASK_DEFAULTS: dict[TaskType, tuple[int, str]] = {
    TaskType.CONFIRM_VISIT: (4, "confirm"),
    TaskType.MISSED_CALL: (5, "incoming"),
    TaskType.NEW_LEAD: (8, "incoming"),
    TaskType.NO_SHOW: (15, "no_show"),
    TaskType.CALLBACK: (18, "incoming"),
    TaskType.REPEAT_VISIT: (20, "repeat_visit"),
    TaskType.POST_PROCEDURE: (25, "post_procedure"),
    TaskType.COURSE_CONTINUE: (25, "procedure"),
    TaskType.LOST_LEAD: (30, "thinking"),
    TaskType.REACTIVATION: (40, "reactivation"),
    TaskType.CAMPAIGN: (45, "reactivation"),
}

# outbound "marketing" calls: never to do-not-call patients, cancelled when DNC is set
OUTBOUND_TYPES = (TaskType.REACTIVATION, TaskType.CAMPAIGN, TaskType.LOST_LEAD)
# closed automatically once the patient books any appointment
CLOSED_BY_BOOKING = (
    TaskType.NEW_LEAD,
    TaskType.LOST_LEAD,
    TaskType.REPEAT_VISIT,
    TaskType.COURSE_CONTINUE,
    TaskType.REACTIVATION,
    TaskType.CAMPAIGN,
    TaskType.NO_SHOW,
    TaskType.MISSED_CALL,
    TaskType.CALLBACK,
)


class TaskStatus(enum.StrEnum):
    OPEN = "open"
    DONE = "done"
    CANCELLED = "cancelled"


class Outcome(enum.StrEnum):
    """TZ 4.5 call results (from a fixed list so reports can count them)."""

    BOOKED = "booked"
    CONFIRMED = "confirmed"
    RESCHEDULED = "rescheduled"
    CANCELLED = "cancelled"
    REFUSED = "refused"
    THINKING = "thinking"
    CALLBACK = "callback"
    NO_ANSWER = "no_answer"
    WRONG_NUMBER = "wrong_number"
    DO_NOT_CALL = "do_not_call"
    DONE = "done"  # conversation happened, nothing to book (e.g. post-procedure check is fine)


# outcomes that mean we actually spoke to the person (dial success rate)
REACHED = (
    Outcome.BOOKED, Outcome.CONFIRMED, Outcome.RESCHEDULED, Outcome.CANCELLED, Outcome.REFUSED,
    Outcome.THINKING, Outcome.CALLBACK, Outcome.DO_NOT_CALL, Outcome.DONE,
)  # fmt: skip

# TZ 4.5: reasons for refusals, cancellations and no-shows
REASONS = (
    "price", "time", "other_clinic", "better", "far", "no_need", "doctor", "illness",
    "forgot", "no_money", "other",
)  # fmt: skip


class Task(UUIDPk, Base):
    __tablename__ = "tasks"

    type: Mapped[TaskType] = mapped_column(str_enum(TaskType, 20), index=True)
    status: Mapped[TaskStatus] = mapped_column(
        str_enum(TaskStatus, 10), default=TaskStatus.OPEN, index=True
    )
    priority: Mapped[int] = mapped_column(SmallInteger)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    patient_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("patients.id"), index=True)
    lead_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("leads.id"), index=True)
    appointment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("appointments.id", ondelete="SET NULL")
    )
    recommendation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("recommendations.id", ondelete="SET NULL")
    )
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("campaigns.id", ondelete="SET NULL"), index=True
    )
    script_code: Mapped[str | None] = mapped_column(String(30))
    note: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    # unanswered attempts in a row: drives the retry ladder (TZ 4.5), reset once we get through
    no_answer_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[Outcome | None] = mapped_column(str_enum(Outcome, 15))
    outcome_reason: Mapped[str | None] = mapped_column(String(50))
    # generators are idempotent: one task per (rule, source object[, day])
    dedupe_key: Mapped[str | None] = mapped_column(String(120), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    # a supervisor took the task off the queue (why, in their words)
    cancel_reason: Mapped[str | None] = mapped_column(String(255))


class TaskAttempt(UUIDPk, Base):
    """Every call attempt / result an operator records (source of the daily report)."""

    __tablename__ = "task_attempts"

    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    task_type: Mapped[TaskType] = mapped_column(str_enum(TaskType, 20), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    patient_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("patients.id"))
    outcome: Mapped[Outcome] = mapped_column(str_enum(Outcome, 15), index=True)
    reason: Mapped[str | None] = mapped_column(String(50))
    note: Mapped[str | None] = mapped_column(Text)
    # written by the system (a booking closed the task), not an operator's call: reports skip it
    automatic: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class ShiftNote(UUIDPk, Base):
    """Handover between the two operators working in shifts (TZ 4.5)."""

    __tablename__ = "shift_notes"

    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
