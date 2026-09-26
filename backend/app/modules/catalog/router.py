import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from app.core.deps import SessionDep, client_ip, require_roles
from app.modules.audit import service as audit
from app.modules.catalog import sync as site_sync
from app.modules.catalog.models import (
    Branch,
    Doctor,
    Resource,
    ResourceKind,
    Service,
    ServiceCategory,
)
from app.modules.diagnoses.categories import Specialty
from app.modules.users.models import Role, User

# NOT NULL columns: an explicit null in a PATCH means "leave as is"
DOCTOR_REQUIRED = ("specialties", "is_active")
SERVICE_REQUIRED = ("duration_min", "requires_consultation", "is_consultation")

router = APIRouter(prefix="/catalog", tags=["catalog"])

ALL_STAFF = (Role.OPERATOR, Role.SUPERVISOR, Role.REGISTRAR, Role.DOCTOR, Role.OWNER, Role.ADMIN)
Reader = Annotated[User, Depends(require_roles(*ALL_STAFF))]
Admin = Annotated[User, Depends(require_roles(Role.ADMIN))]


class BranchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name_uz: str
    name_ru: str
    address_uz: str | None
    phone: str | None
    is_main: bool
    is_active: bool


class DoctorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name_uz: str
    name_ru: str
    title_uz: str | None
    title_ru: str | None
    specialties: list[Specialty]
    color: str | None
    is_active: bool
    user_id: uuid.UUID | None


class DoctorUpdate(BaseModel):
    specialties: list[Specialty] | None = None
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    is_active: bool | None = None
    user_id: uuid.UUID | None = None


class ResourceIn(BaseModel):
    branch_id: uuid.UUID
    name: str = Field(min_length=1, max_length=100)
    kind: ResourceKind
    device_type: str | None = Field(default=None, pattern=r"^[a-z0-9_]{2,50}$")
    is_active: bool = True


class ResourceOut(ResourceIn):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name_uz: str
    name_ru: str
    specialty: Specialty | None


class ServiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    category_id: uuid.UUID | None
    name_uz: str
    name_ru: str
    price: int | None
    is_active: bool
    duration_min: int
    device_type: str | None
    requires_consultation: bool
    is_consultation: bool
    course_sessions: int | None
    min_interval_days: int | None
    followup_call_days: int | None
    prep_uz: str | None
    prep_ru: str | None


class ServiceUpdate(BaseModel):
    duration_min: int | None = Field(default=None, ge=5, le=600)
    device_type: str | None = Field(default=None, pattern=r"^[a-z0-9_]{2,50}$")
    requires_consultation: bool | None = None
    is_consultation: bool | None = None
    course_sessions: int | None = Field(default=None, ge=1, le=50)
    min_interval_days: int | None = Field(default=None, ge=0, le=365)
    followup_call_days: int | None = Field(default=None, ge=0, le=365)
    prep_uz: str | None = Field(default=None, max_length=5000)
    prep_ru: str | None = Field(default=None, max_length=5000)


class ServicePage(BaseModel):
    total: int
    items: list[ServiceOut]


@router.get("/branches")
async def branches(session: SessionDep, _: Reader) -> list[BranchOut]:
    rows = await session.scalars(select(Branch).order_by(Branch.sort_order, Branch.name_uz))
    return [BranchOut.model_validate(b) for b in rows]


@router.get("/doctors")
async def doctors(session: SessionDep, _: Reader, active_only: bool = True) -> list[DoctorOut]:
    stmt = select(Doctor).order_by(Doctor.sort_order, Doctor.name_uz)
    if active_only:
        stmt = stmt.where(Doctor.is_active.is_(True))
    return [DoctorOut.model_validate(d) for d in await session.scalars(stmt)]


@router.patch("/doctors/{doctor_id}")
async def update_doctor(
    doctor_id: uuid.UUID, body: DoctorUpdate, request: Request, session: SessionDep, user: Admin
) -> DoctorOut:
    doctor = await session.get(Doctor, doctor_id)
    if doctor is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="doctor_not_found")
    changes = {
        k: v
        for k, v in body.model_dump(exclude_unset=True).items()
        if not (k in DOCTOR_REQUIRED and v is None)
    }
    if changes.get("user_id"):
        linked = await session.get(User, changes["user_id"])
        if linked is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="user_not_found")
        taken = await session.scalar(
            select(Doctor.id).where(Doctor.user_id == linked.id, Doctor.id != doctor.id)
        )
        if taken:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="user_already_linked")
    for field, value in changes.items():
        setattr(doctor, field, value)
    if "is_active" in changes:
        doctor.deactivated_by_sync = False  # an admin's decision; the site sync keeps it
    try:
        async with session.begin_nested():
            await session.flush()
    except IntegrityError:  # the same user linked to another doctor concurrently
        raise HTTPException(status.HTTP_409_CONFLICT, detail="user_already_linked") from None
    audit.record(
        session, "catalog.doctor", user_id=user.id, entity="doctor", entity_id=doctor.id,
        after={k: str(v) if isinstance(v, uuid.UUID) else v for k, v in changes.items()},
        ip=client_ip(request),
    )  # fmt: skip
    await session.commit()
    return DoctorOut.model_validate(doctor)


@router.get("/resources")
async def resources(
    session: SessionDep, _: Reader, branch_id: uuid.UUID | None = None
) -> list[ResourceOut]:
    stmt = select(Resource).order_by(Resource.kind, Resource.name)
    if branch_id:
        stmt = stmt.where(Resource.branch_id == branch_id)
    return [ResourceOut.model_validate(r) for r in await session.scalars(stmt)]


@router.post("/resources", status_code=status.HTTP_201_CREATED)
async def create_resource(
    body: ResourceIn, request: Request, session: SessionDep, user: Admin
) -> ResourceOut:
    if body.kind is ResourceKind.DEVICE and not body.device_type:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="device_type_required")
    resource = Resource(**body.model_dump())
    session.add(resource)
    await session.flush()
    audit.record(
        session, "catalog.resource", user_id=user.id, entity="resource", entity_id=resource.id,
        after=body.model_dump(mode="json"), ip=client_ip(request),
    )  # fmt: skip
    await session.commit()
    return ResourceOut.model_validate(resource)


@router.put("/resources/{resource_id}")
async def update_resource(
    resource_id: uuid.UUID, body: ResourceIn, request: Request, session: SessionDep, user: Admin
) -> ResourceOut:
    resource = await session.get(Resource, resource_id)
    if resource is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="resource_not_found")
    for field, value in body.model_dump().items():
        setattr(resource, field, value)
    audit.record(
        session, "catalog.resource", user_id=user.id, entity="resource", entity_id=resource.id,
        after=body.model_dump(mode="json"), ip=client_ip(request),
    )  # fmt: skip
    await session.commit()
    return ResourceOut.model_validate(resource)


@router.get("/service-categories")
async def service_categories(session: SessionDep, _: Reader) -> list[CategoryOut]:
    rows = await session.scalars(select(ServiceCategory).order_by(ServiceCategory.name_uz))
    return [CategoryOut.model_validate(c) for c in rows]


@router.get("/services")
async def services(
    session: SessionDep,
    _: Reader,
    q: Annotated[str | None, Query(max_length=100)] = None,
    category_id: uuid.UUID | None = None,
    active_only: bool = True,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ServicePage:
    filters = []
    if active_only:
        filters.append(Service.is_active.is_(True))
    if category_id:
        filters.append(Service.category_id == category_id)
    if q and q.strip():
        like = f"%{q.strip()}%"
        filters.append(or_(Service.name_uz.ilike(like), Service.name_ru.ilike(like)))
    total = await session.scalar(select(func.count()).select_from(Service).where(*filters))
    rows = await session.scalars(
        select(Service)
        .where(*filters)
        .order_by(Service.is_consultation.desc(), Service.name_uz)
        .limit(limit)
        .offset(offset)
    )
    return ServicePage(total=total or 0, items=[ServiceOut.model_validate(s) for s in rows])


@router.patch("/services/{service_id}")
async def update_service(
    service_id: uuid.UUID, body: ServiceUpdate, request: Request, session: SessionDep, user: Admin
) -> ServiceOut:
    service = await session.get(Service, service_id)
    if service is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="service_not_found")
    changes = {
        k: v
        for k, v in body.model_dump(exclude_unset=True).items()
        if not (k in SERVICE_REQUIRED and v is None)
    }
    for field, value in changes.items():
        setattr(service, field, value)
    audit.record(
        session, "catalog.service", user_id=user.id, entity="service", entity_id=service.id,
        after=changes, ip=client_ip(request),
    )  # fmt: skip
    await session.commit()
    return ServiceOut.model_validate(service)


@router.post("/sync")
async def sync_catalog(request: Request, session: SessionDep, user: Admin) -> dict[str, int]:
    user_id = user.id  # read before a rollback expires the instance
    try:
        counts = await site_sync.sync_from_site(session)
    except site_sync.SyncAbortedError as exc:
        await session.rollback()
        audit.record(
            session, "catalog.sync_aborted", user_id=user_id,
            after={"entity": exc.entity, "fetched": exc.fetched, "active": exc.active},
            ip=client_ip(request),
        )  # fmt: skip
        await session.commit()
        raise HTTPException(status.HTTP_409_CONFLICT, detail="sync_aborted") from None
    except Exception as exc:  # noqa: BLE001 - site unreachable / bad response
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="site_unavailable") from exc
    audit.record(
        session, "catalog.sync", user_id=user.id, after=dict(counts), ip=client_ip(request)
    )
    await session.commit()
    return dict(counts)
