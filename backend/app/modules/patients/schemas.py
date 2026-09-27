import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    computed_field,
    field_validator,
)

from app.core.text import InvalidPhoneError, format_uz_phone, normalize_uz_phone
from app.modules.patients.models import Gender, PatientKind, Source
from app.modules.users.models import Language


def _phone(value: str) -> str:
    try:
        return normalize_uz_phone(value)
    except InvalidPhoneError:
        raise ValueError("invalid_phone") from None


def _birth_date(value: date | None) -> date | None:
    # the legacy export has years like 0101 and 6989; reject anything implausible
    if value is not None and not (date(1900, 1, 1) <= value <= date.today()):
        raise ValueError("invalid_birth_date")
    return value


PhoneNumber = Annotated[str, AfterValidator(_phone)]
BirthDate = Annotated[date | None, AfterValidator(_birth_date)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=255)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
Tag = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]


class PhoneIn(BaseModel):
    number: PhoneNumber
    is_primary: bool = False
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)] | None = None


class PhoneUpdate(BaseModel):
    is_primary: bool | None = None
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)] | None = None


class PhoneOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    number: str
    is_primary: bool
    note: str | None
    wrong_number_at: datetime | None = None

    @computed_field
    @property
    def display(self) -> str:
        return format_uz_phone(self.number)


class PatientBase(BaseModel):
    birth_date: BirthDate = None
    gender: Gender = Gender.UNKNOWN
    address: ShortText | None = None
    district: Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)] | None = None
    language: Language = Language.UZ
    tags: list[Tag] = Field(default_factory=list, max_length=20)
    notes: Annotated[str, StringConstraints(max_length=5000)] | None = None


class PatientCreate(PatientBase):
    full_name: Name
    source: Source
    phones: list[PhoneIn] = Field(min_length=1, max_length=5)


class PatientUpdate(BaseModel):
    full_name: Name | None = None
    birth_date: BirthDate = None
    gender: Gender | None = None
    address: ShortText | None = None
    district: Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)] | None = None
    language: Language | None = None
    source: Source | None = None
    tags: list[Tag] | None = Field(default=None, max_length=20)
    notes: Annotated[str, StringConstraints(max_length=5000)] | None = None


class DoNotCallIn(BaseModel):
    do_not_call: bool
    reason: Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)] | None = None


class MergeIn(BaseModel):
    source_id: uuid.UUID


class ConditionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    raw_text: str
    category_code: str | None
    visit_type: str | None
    source: str


class _PrimaryPhoneFirst(BaseModel):
    @field_validator("phones", check_fields=False)
    @classmethod
    def _primary_first(cls, phones: list[PhoneOut]) -> list[PhoneOut]:
        # in-memory collections keep insertion order; the DB order_by only applies on load
        return sorted(phones, key=lambda p: not p.is_primary)


class PatientOut(_PrimaryPhoneFirst):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    birth_date: date | None
    gender: Gender
    address: str | None
    district: str | None
    language: Language
    kind: PatientKind
    source: Source | None
    tags: list[str]
    notes: str | None
    do_not_call: bool
    do_not_call_reason: str | None
    last_visit_at: datetime | None
    merged_into_id: uuid.UUID | None
    created_at: datetime
    phones: list[PhoneOut]
    conditions: list[ConditionOut]


class PatientListItem(_PrimaryPhoneFirst):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    birth_date: date | None
    district: str | None
    kind: PatientKind
    do_not_call: bool
    tags: list[str]
    last_visit_at: datetime | None
    phones: list[PhoneOut]


class PatientPage(BaseModel):
    total: int
    items: list[PatientListItem]


class DuplicateCheckIn(BaseModel):
    full_name: str = ""
    birth_date: date | None = None
    phones: list[PhoneNumber] = Field(default_factory=list, max_length=5)


class DuplicateCandidate(PatientListItem):
    reasons: list[Literal["phone", "name"]]
