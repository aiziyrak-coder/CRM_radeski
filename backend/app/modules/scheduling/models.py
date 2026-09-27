import enum
import uuid
from datetime import date, datetime, time

from sqlalchemy import (
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    Time,
    text,
)
from sqlalchemy.dialects.postgresql import TSTZRANGE, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, Timestamps, UUIDPk, str_enum
from app.modules.patients.models import Source


class AppointmentStatus(enum.StrEnum):
    SCHEDULED = "scheduled"
    CONFIRMED = "confirmed"
    ARRIVED = "arrived"
    COMPLETED = "completed"
    NO_SHOW = "no_show"
    CANCELLED = "cancelled"
    RESCHEDULED = "rescheduled"


# statuses that occupy the doctor's / device's time
ACTIVE_STATUSES = (
    AppointmentStatus.SCHEDULED,
    AppointmentStatus.CONFIRMED,
    AppointmentStatus.ARRIVED,
    AppointmentStatus.COMPLETED,
)
_ACTIVE_SQL = "status IN ('scheduled', 'confirmed', 'arrived', 'completed')"


class RecommendationStatus(enum.StrEnum):
    OPEN = "open"
    BOOKED = "booked"
    DISMISSED = "dismissed"


class AbsenceKind(enum.StrEnum):
    VACATION = "vacation"
    SICK = "sick"
    OTHER = "other"


class DoctorSchedule(UUIDPk, Base):
    """Weekly working hours of a doctor at a branch (several rows per day = split shifts)."""

    __tablename__ = "doctor_schedules"
    __table_args__ = (
        CheckConstraint("weekday BETWEEN 0 AND 6", name="weekday_range"),
        CheckConstraint("start_time < end_time", name="start_before_end"),
    )

    doctor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("doctors.id", ondelete="CASCADE"), index=True
    )
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id"))
    weekday: Mapped[int] = mapped_column(SmallInteger)  # 0 = Monday
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)


class DoctorAbsence(UUIDPk, Base):
    __tablename__ = "doctor_absences"
    __table_args__ = (CheckConstraint("date_from <= date_to", name="from_before_to"),)

    doctor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("doctors.id", ondelete="CASCADE"), index=True
    )
    date_from: Mapped[date] = mapped_column(Date)
    date_to: Mapped[date] = mapped_column(Date)
    kind: Mapped[AbsenceKind] = mapped_column(
        str_enum(AbsenceKind, 10), default=AbsenceKind.OTHER, server_default="other"
    )
    reason: Mapped[str | None] = mapped_column(String(255))


class Appointment(UUIDPk, Timestamps, Base):
    __tablename__ = "appointments"
    __table_args__ = (
        CheckConstraint("starts_at < ends_at", name="starts_before_ends"),
        # TZ 4.3: double booking is impossible at the database level
        ExcludeConstraint(
            ("doctor_id", "="),
            ("during", "&&"),
            name="no_doctor_overlap",
            using="gist",
            where=text(_ACTIVE_SQL),
        ),
        ExcludeConstraint(
            ("resource_id", "="),
            ("during", "&&"),
            name="no_resource_overlap",
            using="gist",
            where=text(f"resource_id IS NOT NULL AND {_ACTIVE_SQL}"),
        ),
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id"), index=True)
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id"), index=True)
    doctor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("doctors.id"), index=True)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("resources.id"))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    during = mapped_column(TSTZRANGE, Computed("tstzrange(starts_at, ends_at)", persisted=True))
    status: Mapped[AppointmentStatus] = mapped_column(
        str_enum(AppointmentStatus, 12), default=AppointmentStatus.SCHEDULED, index=True
    )
    source: Mapped[Source | None] = mapped_column(str_enum(Source, 20))
    note: Mapped[str | None] = mapped_column(Text)
    cancel_reason: Mapped[str | None] = mapped_column(String(100))
    rescheduled_from_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("appointments.id", ondelete="SET NULL")
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    status_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    services: Mapped[list["AppointmentService"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", order_by="AppointmentService.position"
    )


class AppointmentService(UUIDPk, Base):
    __tablename__ = "appointment_services"

    appointment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("appointments.id", ondelete="CASCADE"), index=True
    )
    service_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("services.id"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    duration_min: Mapped[int] = mapped_column(Integer)  # snapshot at booking time
    price: Mapped[int | None] = mapped_column(Integer)  # snapshot at booking time


class Recommendation(UUIDPk, Timestamps, Base):
    """Doctor's "come back in N weeks" (TZ 4.3); drives the repeat-visit call task."""

    __tablename__ = "recommendations"

    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id"), index=True)
    doctor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("doctors.id"))
    appointment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("appointments.id", ondelete="SET NULL")
    )
    due_date: Mapped[date] = mapped_column(Date, index=True)
    service_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("services.id"))
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[RecommendationStatus] = mapped_column(
        str_enum(RecommendationStatus, 10), default=RecommendationStatus.OPEN, index=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
