import enum
import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, Timestamps, UUIDPk, str_enum
from app.modules.users.models import Language


class Gender(enum.StrEnum):
    MALE = "male"
    FEMALE = "female"
    UNKNOWN = "unknown"


class PatientKind(enum.StrEnum):
    ACTIVE = "active"  # has visited / created in CRM
    LEGACY = "legacy"  # imported from the old Excel export
    COLD = "cold"  # hand-collected potential clients (nomer.xlsx)
    LEAD = "lead"  # contacted the clinic but never came


class Source(enum.StrEnum):
    """How the patient first found the clinic (TZ 4.4, mandatory for new leads)."""

    INSTAGRAM = "instagram"
    TELEGRAM = "telegram"
    GOOGLE = "google"
    MAPS = "maps"  # 2GIS / Yandex / Google Maps
    WEBSITE = "website"
    RECOMMENDATION = "recommendation"
    ADVERTISING = "advertising"
    RETURNING = "returning"
    IMPORT = "import"
    COLD_BASE = "cold_base"
    OTHER = "other"


class Patient(UUIDPk, Timestamps, Base):
    __tablename__ = "patients"

    full_name: Mapped[str] = mapped_column(String(255))
    # script-insensitive form of full_name for search (app.core.text.search_key)
    search_key: Mapped[str] = mapped_column(String(255))
    birth_date: Mapped[date | None] = mapped_column(Date)
    gender: Mapped[Gender] = mapped_column(str_enum(Gender, 10), default=Gender.UNKNOWN)
    address: Mapped[str | None] = mapped_column(String(500))
    district: Mapped[str | None] = mapped_column(String(100), index=True)
    language: Mapped[Language] = mapped_column(str_enum(Language, 5), default=Language.UZ)
    kind: Mapped[PatientKind] = mapped_column(str_enum(PatientKind, 10), index=True)
    source: Mapped[Source | None] = mapped_column(str_enum(Source, 20))
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(50)), default=list)
    notes: Mapped[str | None] = mapped_column(Text)

    do_not_call: Mapped[bool] = mapped_column(Boolean, default=False)
    do_not_call_reason: Mapped[str | None] = mapped_column(String(255))

    last_visit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    legacy_ref: Mapped[str | None] = mapped_column(String(100), index=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    # soft-deleted after a merge; every read path filters these out
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("patients.id", ondelete="SET NULL"), index=True
    )

    phones: Mapped[list["PatientPhone"]] = relationship(
        back_populates="patient",
        cascade="all, delete-orphan",
        order_by="(PatientPhone.is_primary.desc(), PatientPhone.created_at)",
        lazy="selectin",
    )

    __table_args__ = (
        Index(
            "ix_patients_search_key_trgm",
            "search_key",
            postgresql_using="gin",
            postgresql_ops={"search_key": "gin_trgm_ops"},
        ),
    )


class PatientPhone(UUIDPk, Base):
    """Not unique across patients: family members (a child and parent) often share a number.
    Shared numbers are surfaced as duplicate warnings instead of being blocked."""

    __tablename__ = "patient_phones"

    patient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), index=True
    )
    number: Mapped[str] = mapped_column(String(16))  # E.164, +998XXXXXXXXX
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str | None] = mapped_column(String(100))  # e.g. "onasi", "ishxona"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    patient: Mapped[Patient] = relationship(back_populates="phones")

    __table_args__ = (
        Index("ix_patient_phones_number", "number"),
        Index(
            "ix_patient_phones_number_trgm",
            "number",
            postgresql_using="gin",
            postgresql_ops={"number": "gin_trgm_ops"},
        ),
    )
