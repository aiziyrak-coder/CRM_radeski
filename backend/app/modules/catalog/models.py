"""Clinic catalog: branches, rooms/devices, doctors and services.

Names, prices and the doctor list come from radeski.uz (the site's admin is the source of
truth); CRM-only fields (duration, device, intervals, schedules) are edited here.
"""

import enum
import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamps, UUIDPk, str_enum
from app.modules.diagnoses.categories import Specialty


class ResourceKind(enum.StrEnum):
    ROOM = "room"  # consulting / procedure room
    DEVICE = "device"  # laser, IPL, Morpheus 8 ... (limits parallel procedures)


class Branch(UUIDPk, Timestamps, Base):
    __tablename__ = "branches"

    site_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    name_uz: Mapped[str] = mapped_column(String(255))
    name_ru: Mapped[str] = mapped_column(String(255))
    address_uz: Mapped[str | None] = mapped_column(String(500))
    phone: Mapped[str | None] = mapped_column(String(50))
    is_main: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class Resource(UUIDPk, Timestamps, Base):
    __tablename__ = "resources"

    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[ResourceKind] = mapped_column(str_enum(ResourceKind, 10))
    # for devices: what it does, matched against Service.device_type (e.g. "laser_epilation")
    device_type: Mapped[str | None] = mapped_column(String(50), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Doctor(UUIDPk, Timestamps, Base):
    __tablename__ = "doctors"

    site_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), unique=True
    )
    name_uz: Mapped[str] = mapped_column(String(255))
    name_ru: Mapped[str] = mapped_column(String(255))
    title_uz: Mapped[str | None] = mapped_column(String(255))
    title_ru: Mapped[str | None] = mapped_column(String(255))
    specialties: Mapped[list[Specialty]] = mapped_column(ARRAY(String(30)), default=list)
    color: Mapped[str | None] = mapped_column(String(9))  # schedule column colour
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class ServiceCategory(UUIDPk, Timestamps, Base):
    __tablename__ = "service_categories"

    site_id: Mapped[str] = mapped_column(String(100), unique=True)
    name_uz: Mapped[str] = mapped_column(String(255))
    name_ru: Mapped[str] = mapped_column(String(255))
    specialty: Mapped[Specialty | None] = mapped_column(str_enum(Specialty, 30))


class Service(UUIDPk, Timestamps, Base):
    __tablename__ = "services"

    site_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("service_categories.id"), index=True
    )
    name_uz: Mapped[str] = mapped_column(String(500))
    name_ru: Mapped[str] = mapped_column(String(500))
    price: Mapped[int | None] = mapped_column(Integer)  # UZS, informational (no billing in v1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # --- CRM-only parameters (TZ 4.2) ---
    duration_min: Mapped[int] = mapped_column(Integer, default=30)
    device_type: Mapped[str | None] = mapped_column(String(50))
    requires_consultation: Mapped[bool] = mapped_column(Boolean, default=False)
    is_consultation: Mapped[bool] = mapped_column(Boolean, default=False)
    course_sessions: Mapped[int | None] = mapped_column(Integer)
    min_interval_days: Mapped[int | None] = mapped_column(Integer)
    followup_call_days: Mapped[int | None] = mapped_column(Integer)
    prep_uz: Mapped[str | None] = mapped_column(Text)
    prep_ru: Mapped[str | None] = mapped_column(Text)


class DoctorService(Base):
    """Explicit "this doctor performs this service". Without any rows for a service, doctors
    are matched by specialty (see scheduling.service.eligible_doctors)."""

    __tablename__ = "doctor_services"
    __table_args__ = (UniqueConstraint("doctor_id", "service_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    doctor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("doctors.id", ondelete="CASCADE"))
    service_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("services.id", ondelete="CASCADE"))
