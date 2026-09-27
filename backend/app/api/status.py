"""What is connected and what needs attention (home page). Staff only: /health stays minimal."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import String, cast, func, select

from app.core import clinic_time
from app.core.config import get_settings
from app.core.deps import SessionDep, require_roles
from app.integrations import openai_client
from app.integrations.instagram import get_instagram
from app.integrations.sms import get_sms_sender
from app.integrations.telegram import get_telegram
from app.modules.ai.models import AnalysisStatus, CallAnalysis
from app.modules.audit.models import AuditLog
from app.modules.catalog.models import Branch, Doctor, Resource, ResourceKind, Service
from app.modules.diagnoses.models import DiagnosisMapping, MappingStatus
from app.modules.leads.models import Lead, LeadStage
from app.modules.messaging.models import Conversation, Message, MessageStatus
from app.modules.patients.models import Patient, PatientKind
from app.modules.scheduling.models import Appointment, AppointmentStatus, DoctorSchedule
from app.modules.tasks.models import Task, TaskStatus, TaskType
from app.modules.telephony.models import (
    UNANSWERED_INBOUND,
    Call,
    CallDirection,
    RecordingStatus,
)
from app.modules.users.models import Role, User

router = APIRouter(prefix="/system", tags=["system"])
Staff = Annotated[
    User, Depends(require_roles(Role.OPERATOR, Role.SUPERVISOR, Role.OWNER, Role.ADMIN))
]


async def _count(session: SessionDep, stmt) -> int:
    return await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0


@router.get("/status")
async def system_status(session: SessionDep, user: Staff) -> dict[str, Any]:
    s = get_settings()
    start, end = clinic_time.day_bounds(clinic_time.today())
    week_ago = datetime.now(UTC) - timedelta(days=7)
    out: dict[str, Any] = {
        "today": {
            "missed_calls": await _count(
                session,
                select(Call.id).where(
                    Call.direction == CallDirection.IN,
                    Call.status.in_(UNANSWERED_INBOUND),
                    Call.started_at >= start,
                    Call.started_at < end,
                ),
            ),
            "unread_chats": await _count(
                session, select(Conversation.id).where(Conversation.unread > 0)
            ),
            # missed calls still waiting for a callback (what the header alert asks to handle)
            "missed_open": await _count(
                session,
                select(Task.id).where(
                    Task.type == TaskType.MISSED_CALL, Task.status == TaskStatus.OPEN
                ),
            ),
            # TZ 4.4: an inquiry unanswered past its SLA is shown to the supervisor (header alert)
            "leads_sla_breached": await _count(
                session,
                select(Lead.id).where(
                    Lead.first_response_at.is_(None),
                    Lead.sla_due_at < datetime.now(UTC),
                    Lead.stage == LeadStage.NEW,
                ),
            ),
        },
    }
    if user.role is not Role.OPERATOR:
        out["qa"] = {
            "red_flags_open": await _count(
                session,
                select(CallAnalysis.id).where(
                    CallAnalysis.has_red_flags,
                    CallAnalysis.flags_reviewed_at.is_(None),
                    CallAnalysis.created_at > week_ago,
                ),
            ),
        }
        last_call = await session.scalar(select(func.max(Call.started_at)))
        sms = get_sms_sender()
        out["integrations"] = {
            "telephony": bool(s.pbx_api_secret),
            "trunk": bool(s.sip_host),
            "last_call_at": last_call,
            "ai": openai_client.enabled(),
            "ai_spent_today_usd": round(await openai_client.spent_today(), 4),
            "ai_daily_budget_usd": s.ai_daily_budget_usd,
            "telegram": get_telegram() is not None,
            "instagram": get_instagram() is not None,
            "sms": sms.name if sms else None,
        }
        out["attention"] = {
            "recordings_failed": await _count(
                session,
                select(Call.id).where(
                    Call.recording_status == RecordingStatus.FAILED, Call.started_at > week_ago
                ),
            ),
            "analyses_failed": await _count(
                session,
                select(CallAnalysis.id).where(
                    CallAnalysis.status == AnalysisStatus.FAILED,
                    CallAnalysis.created_at > week_ago,
                ),
            ),
            "messages_failed": await _count(
                session,
                select(Message.id).where(
                    Message.status == MessageStatus.FAILED, Message.created_at > week_ago
                ),
            ),
            "messages_queued": await _count(
                session, select(Message.id).where(Message.status == MessageStatus.QUEUED)
            ),
        }
    return out


# --- admin: setup checklist -------------------------------------------------------------------

Admin = Annotated[User, Depends(require_roles(Role.ADMIN))]
# the site sync runs nightly; older than this means it has stopped
SYNC_STALE_AFTER = timedelta(days=3)
# the roles a working clinic needs at least one active account of
SETUP_ROLES = (Role.OPERATOR, Role.SUPERVISOR, Role.REGISTRAR, Role.DOCTOR)
# what every synced service starts with until someone fills in the real duration
DEFAULT_DURATION = Service.__table__.c.duration_min.default.arg


def _state(done: int, total: int) -> str:
    """ok = everything done, partial = some, todo = nothing yet."""
    if total and done >= total:
        return "ok"
    return "partial" if done else "todo"


def _item(key: str, status: str, link: str | None, **detail: Any) -> dict[str, Any]:
    return {"key": key, "status": status, "link": link, **detail}


@router.get("/setup")
async def setup_checklist(session: SessionDep, _: Admin) -> dict[str, Any]:
    """ "Tizimni sozlash": what is still missing before the clinic can work in the CRM. Each row
    has a status (ok / partial / todo / off) and the page where it is fixed."""
    s = get_settings()
    now = datetime.now(UTC)
    items: list[dict[str, Any]] = []

    # catalog from radeski.uz (TZ 4.2)
    site_services = await _count(
        session, select(Service.id).where(Service.site_id.is_not(None), Service.is_active)
    )
    site_doctors = await _count(
        session, select(Doctor.id).where(Doctor.site_id.is_not(None), Doctor.is_active)
    )
    branches = await _count(session, select(Branch.id).where(Branch.is_active))
    audited_sync = await session.scalar(
        select(func.max(AuditLog.created_at)).where(AuditLog.action == "catalog.sync")
    )
    # the nightly job isn't audited: the newest change it made is the best evidence it ran
    changed = await session.scalar(
        select(func.max(Service.updated_at)).where(Service.site_id.is_not(None))
    )
    last_sync = max((t for t in (audited_sync, changed) if t), default=None)
    fresh = last_sync is not None and now - last_sync < SYNC_STALE_AFTER
    items.append(
        _item(
            "catalog", "todo" if not site_services else "ok" if fresh else "partial",
            "/settings?tab=services", services=site_services, doctors=site_doctors,
            branches=branches, last_sync_at=last_sync,
        )
    )  # fmt: skip

    # doctors: weekly schedule and a login of their own (TZ 4.3)
    doctors = await _count(session, select(Doctor.id).where(Doctor.is_active))
    has_schedule = select(DoctorSchedule.id).where(DoctorSchedule.doctor_id == Doctor.id).exists()
    scheduled = await _count(session, select(Doctor.id).where(Doctor.is_active, has_schedule))
    items.append(
        _item("doctor_schedules", _state(scheduled, doctors), "/settings?tab=doctors",
              done=scheduled, total=doctors)
    )  # fmt: skip
    linked = await _count(
        session, select(Doctor.id).where(Doctor.is_active, Doctor.user_id.is_not(None))
    )
    items.append(
        _item("doctor_accounts", _state(linked, doctors), "/users", done=linked, total=doctors)
    )

    # rooms and devices per branch (TZ 4.2)
    kinds = dict(
        (
            await session.execute(
                select(Resource.kind, func.count())
                .where(Resource.is_active)
                .group_by(Resource.kind)
            )
        ).all()
    )
    has_resource = (
        select(Resource.id).where(Resource.branch_id == Branch.id, Resource.is_active).exists()
    )
    equipped = await _count(session, select(Branch.id).where(Branch.is_active, has_resource))
    items.append(
        _item(
            "resources", _state(equipped, branches), "/settings?tab=resources",
            rooms=kinds.get(ResourceKind.ROOM, 0), devices=kinds.get(ResourceKind.DEVICE, 0),
            done=equipped, total=branches,
        )
    )  # fmt: skip

    # service durations: the site has none, every service starts at the default. A duration
    # counts as filled once it differs from the default or an admin saved it (audit log).
    services = await _count(session, select(Service.id).where(Service.is_active))
    edited = select(AuditLog.entity_id).where(
        AuditLog.action == "catalog.service", AuditLog.after.has_key("duration_min")
    )
    with_duration = await _count(
        session,
        select(Service.id).where(
            Service.is_active,
            (Service.duration_min != DEFAULT_DURATION) | cast(Service.id, String).in_(edited),
        ),
    )
    items.append(
        _item("service_durations", _state(with_duration, services), "/settings?tab=services",
              done=with_duration, total=services)
    )  # fmt: skip

    # staff accounts (TZ 3)
    by_role = dict(
        (
            await session.execute(
                select(User.role, func.count()).where(User.is_active).group_by(User.role)
            )
        ).all()
    )
    roles = {r.value: by_role.get(r, 0) for r in SETUP_ROLES}
    present = sum(1 for n in roles.values() if n)
    items.append(_item("users", _state(present, len(roles)), "/users", roles=roles))

    # integrations: configured in the server's .env, so there is no page to link to
    last_call = await session.scalar(select(func.max(Call.started_at)))
    telephony = "off" if not s.pbx_api_secret else "ok" if s.sip_host and last_call else "partial"
    items.append(
        _item("telephony", telephony, None, trunk=bool(s.sip_host), last_call_at=last_call)
    )
    items.append(_item("ai", "ok" if openai_client.enabled() else "off", None))
    items.append(_item("telegram", "ok" if get_telegram() else "off", None))
    sms = get_sms_sender()
    items.append(_item("sms", "ok" if sms else "off", None, provider=sms.name if sms else None))
    items.append(_item("instagram", "ok" if get_instagram() else "off", None))

    # the one-off import of the old Excel base (TZ 2, 4.8.4)
    by_kind = dict(
        (
            await session.execute(
                select(Patient.kind, func.count())
                .where(Patient.merged_into_id.is_(None))
                .group_by(Patient.kind)
            )
        ).all()
    )
    legacy = by_kind.get(PatientKind.LEGACY, 0)
    items.append(
        _item(
            "legacy_import", "ok" if legacy else "todo", "/patients", legacy=legacy,
            cold=by_kind.get(PatientKind.COLD, 0), patients=sum(by_kind.values()),
        )
    )  # fmt: skip

    # diagnosis texts waiting for a doctor's approval (TZ 4.8.4)
    mapping = dict(
        (
            await session.execute(
                select(DiagnosisMapping.status, func.count()).group_by(DiagnosisMapping.status)
            )
        ).all()
    )
    waiting = mapping.get(MappingStatus.PENDING, 0) + mapping.get(MappingStatus.SUGGESTED, 0)
    approved = mapping.get(MappingStatus.APPROVED, 0)
    items.append(
        _item(
            "diagnoses", "ok" if approved and not waiting else "partial" if approved else "todo",
            "/diagnoses", waiting=waiting, approved=approved,
        )
    )  # fmt: skip
    return {
        "items": items,
        "done": sum(1 for i in items if i["status"] == "ok"),
        "total": len(items),
    }


# --- registrar / doctor: today at a glance ------------------------------------------------------

Anyone = Annotated[User, Depends(require_roles(*Role))]
S = AppointmentStatus


@router.get("/today")
async def today_visits(session: SessionDep, user: Anyone) -> dict[str, Any]:
    """Today's appointments by status: a registrar's branch, a doctor's own patients, the whole
    clinic for everyone else."""
    start, end = clinic_time.day_bounds(clinic_time.today())
    where = [Appointment.starts_at >= start, Appointment.starts_at < end]
    out: dict[str, Any] = {"scope": "all", "branch_id": None, "linked": True}
    if user.role is Role.REGISTRAR and user.branch_id:
        where.append(Appointment.branch_id == user.branch_id)
        out.update(scope="branch", branch_id=user.branch_id)
    elif user.role is Role.DOCTOR:
        mine = select(Doctor.id).where(Doctor.user_id == user.id)
        out.update(scope="doctor", linked=bool(await session.scalar(mine.limit(1))))
        where.append(Appointment.doctor_id.in_(mine))
    counts = dict(
        (
            await session.execute(
                select(Appointment.status, func.count()).where(*where).group_by(Appointment.status)
            )
        ).all()
    )
    n = {st.value: counts.get(st, 0) for st in S}
    out["counts"] = {
        **n,
        "expected": n["scheduled"] + n["confirmed"],  # booked for today, not here yet
        "came": n["arrived"] + n["completed"],
        "total": sum(v for k, v in n.items() if k not in ("cancelled", "rescheduled")),
    }
    out["next_at"] = await session.scalar(
        select(func.min(Appointment.starts_at)).where(
            *where,
            Appointment.status.in_((S.SCHEDULED, S.CONFIRMED)),
            Appointment.starts_at >= datetime.now(UTC),
        )
    )
    return out
