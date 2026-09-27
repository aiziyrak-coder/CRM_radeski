import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError

from app.core.deps import SessionDep, client_ip, require_roles
from app.modules.audit import service as audit
from app.modules.catalog import sync as site_sync
from app.modules.catalog.models import (
    Branch,
    CatalogSyncRun,
    Doctor,
    DoctorService,
    Resource,
    ResourceKind,
    Service,
    ServiceCategory,
    SyncStatus,
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
DEVICE_TYPE = r"^[a-z0-9_]{2,50}$"


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
    device_type: str | None = Field(default=None, pattern=DEVICE_TYPE)
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
    duration_confirmed: bool
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
    device_type: str | None = Field(default=None, pattern=DEVICE_TYPE)
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


class ServiceBulkIn(BaseModel):
    service_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    duration_min: int | None = Field(default=None, ge=5, le=600)
    device_type: str | None = Field(default=None, pattern=DEVICE_TYPE)
    clear_device: bool = False  # device_type=None can't say "remove the device" on its own


class DeviceTypeOut(BaseModel):
    device_type: str
    resources: int  # active devices of this type (any branch)
    services: int  # active services that need it


class DoctorServicesIn(BaseModel):
    service_ids: list[uuid.UUID] = Field(max_length=2000)


class DoctorServiceLink(BaseModel):
    doctor_id: uuid.UUID
    service_id: uuid.UUID


class SyncRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    started_at: datetime
    finished_at: datetime
    trigger: str
    user_id: uuid.UUID | None
    status: SyncStatus
    counts: dict[str, Any] | None
    error: str | None


class SyncStateOut(BaseModel):
    last: SyncRunOut | None
    last_ok: SyncRunOut | None


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
    if body.kind is ResourceKind.ROOM:
        body.device_type = None  # a room serves any service
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
    if body.kind is ResourceKind.DEVICE and not body.device_type:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="device_type_required")
    if body.kind is ResourceKind.ROOM:
        body.device_type = None  # a room serves any service
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
    # "davomiylik to'ldirilmagan": still the sync's placeholder duration
    duration_missing: bool = False,
    device_type: Annotated[str | None, Query(max_length=50)] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ServicePage:
    filters = []
    if active_only:
        filters.append(Service.is_active.is_(True))
    if category_id:
        filters.append(Service.category_id == category_id)
    if duration_missing:
        filters.append(Service.duration_confirmed.is_(False))
    if device_type:
        filters.append(Service.device_type == device_type)
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
    if "duration_min" in changes:
        service.duration_confirmed = True
    audit.record(
        session, "catalog.service", user_id=user.id, entity="service", entity_id=service.id,
        after=changes, ip=client_ip(request),
    )  # fmt: skip
    await session.commit()
    return ServiceOut.model_validate(service)


@router.post("/services/bulk")
async def bulk_update_services(
    body: ServiceBulkIn, request: Request, session: SessionDep, user: Admin
) -> dict[str, int]:
    """One duration / device for many services at once (e.g. a whole laser category)."""
    values: dict[str, Any] = {}
    if body.duration_min is not None:
        values |= {"duration_min": body.duration_min, "duration_confirmed": True}
    if body.clear_device:
        values["device_type"] = None
    elif body.device_type is not None:
        values["device_type"] = body.device_type
    if not values:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="nothing_to_change")
    ids = set(body.service_ids)
    found = set(await session.scalars(select(Service.id).where(Service.id.in_(ids))))
    if found != ids:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="service_not_found")
    await session.execute(update(Service).where(Service.id.in_(ids)).values(**values))
    audit.record(
        session, "catalog.service_bulk", user_id=user.id, entity="service",
        after={**values, "service_ids": sorted(str(i) for i in ids)}, ip=client_ip(request),
    )  # fmt: skip
    await session.commit()
    return {"updated": len(ids)}


@router.get("/device-types")
async def device_types(session: SessionDep, _: Reader) -> list[DeviceTypeOut]:
    """Device types known to the clinic: from its devices and from services that need one."""
    resources = dict(
        (
            await session.execute(
                select(Resource.device_type, func.count())
                .where(Resource.device_type.is_not(None), Resource.is_active.is_(True))
                .group_by(Resource.device_type)
            )
        ).all()
    )
    services = dict(
        (
            await session.execute(
                select(Service.device_type, func.count())
                .where(Service.device_type.is_not(None), Service.is_active.is_(True))
                .group_by(Service.device_type)
            )
        ).all()
    )
    # the type of a switched-off device is still known (with 0 active devices)
    known = set(
        await session.scalars(select(Resource.device_type).where(Resource.device_type.is_not(None)))
    )
    return [
        DeviceTypeOut(device_type=t, resources=resources.get(t, 0), services=services.get(t, 0))
        for t in sorted(known | set(services))
    ]


# --- doctor <-> service links (TZ 4.2) ---------------------------------------------------------


@router.get("/doctor-services")
async def doctor_services(
    session: SessionDep, _: Reader, doctor_id: uuid.UUID | None = None
) -> list[DoctorServiceLink]:
    """Explicit links. A service with no links at all is matched to doctors by specialty."""
    stmt = select(DoctorService.doctor_id, DoctorService.service_id)
    if doctor_id:
        stmt = stmt.where(DoctorService.doctor_id == doctor_id)
    rows = await session.execute(stmt)
    return [DoctorServiceLink(doctor_id=d, service_id=s) for d, s in rows]


@router.put("/doctors/{doctor_id}/services")
async def set_doctor_services(
    doctor_id: uuid.UUID,
    body: DoctorServicesIn,
    request: Request,
    session: SessionDep,
    user: Admin,
) -> list[DoctorServiceLink]:
    """Replaces the doctor's explicit service list."""
    if await session.get(Doctor, doctor_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="doctor_not_found")
    ids = set(body.service_ids)
    if ids:
        found = set(await session.scalars(select(Service.id).where(Service.id.in_(ids))))
        if found != ids:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="service_not_found")
    before = sorted(
        str(i)
        for i in await session.scalars(
            select(DoctorService.service_id).where(DoctorService.doctor_id == doctor_id)
        )
    )
    await session.execute(delete(DoctorService).where(DoctorService.doctor_id == doctor_id))
    session.add_all(DoctorService(doctor_id=doctor_id, service_id=i) for i in ids)
    audit.record(
        session, "catalog.doctor_services", user_id=user.id, entity="doctor",
        entity_id=doctor_id, before={"service_ids": before},
        after={"service_ids": sorted(str(i) for i in ids)}, ip=client_ip(request),
    )  # fmt: skip
    await session.commit()
    return [DoctorServiceLink(doctor_id=doctor_id, service_id=i) for i in sorted(ids)]


# --- site sync ---------------------------------------------------------------------------------


@router.get("/sync")
async def sync_state(session: SessionDep, _: Reader) -> SyncStateOut:
    """The last catalog sync and the last successful one (settings page)."""
    newest = select(CatalogSyncRun).order_by(CatalogSyncRun.started_at.desc()).limit(1)
    last = await session.scalar(newest)
    last_ok = await session.scalar(newest.where(CatalogSyncRun.status == SyncStatus.OK))
    return SyncStateOut(
        last=SyncRunOut.model_validate(last) if last else None,
        last_ok=SyncRunOut.model_validate(last_ok) if last_ok else None,
    )


@router.post("/sync")
async def sync_catalog(request: Request, session: SessionDep, user: Admin) -> dict[str, int]:
    user_id = user.id  # read before a rollback expires the instance
    run = await site_sync.run_and_record(session, trigger="manual", user_id=user_id)
    if run.status is SyncStatus.ABORTED:
        audit.record(
            session, "catalog.sync_aborted", user_id=user_id, after=run.counts,
            ip=client_ip(request),
        )  # fmt: skip
        await session.commit()
        raise HTTPException(status.HTTP_409_CONFLICT, detail="sync_aborted")
    if run.status is SyncStatus.FAILED:
        await session.commit()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="site_unavailable")
    counts = dict(run.counts or {})
    audit.record(session, "catalog.sync", user_id=user_id, after=counts, ip=client_ip(request))
    await session.commit()
    return counts
