import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response

from app.core import clinic_time
from app.core.deps import SessionDep, client_ip, require_roles
from app.modules.audit import service as audit
from app.modules.patients.models import Source
from app.modules.reports import service
from app.modules.users.models import Role, User

router = APIRouter(prefix="/reports", tags=["reports"])
Manager = Annotated[User, Depends(require_roles(Role.SUPERVISOR, Role.OWNER, Role.ADMIN))]
# who may read the daily report at all (an operator only their own)
DailyReader = Annotated[
    User, Depends(require_roles(Role.OPERATOR, Role.SUPERVISOR, Role.OWNER, Role.ADMIN))
]

KPI_LABELS = {
    "inbound_calls": "Kiruvchi qo'ng'iroqlar / Входящие звонки",
    "inbound_answer_rate": "Javob berilgan, % / Отвечено, %",
    "inbound_missed": "Javobsiz / Пропущено",
    "missed_callback_avg_min": "Javobsizga qayta qo'ng'iroq, daq / Перезвон пропущенным, мин",
    "missed_not_called_back": "Qayta qo'ng'iroq qilinmagan / Не перезвонили",
    "avg_wait_sec": "O'rtacha kutish, s / Среднее ожидание, с",
    "outbound_calls": "Chiquvchi qo'ng'iroqlar / Исходящие звонки",
    "talk_minutes": "Suhbat, daq / Разговор, мин",
    "leads_total": "Murojaatlar / Обращения",
    "leads_handled": "Ishlov berilgan murojaatlar / Обработанные обращения",
    "lead_to_booking": "Murojaat → yozuv, % / Обращение → запись, %",
    "first_response_median_min": "Birinchi javob (mediana, daq) / Первый ответ (медиана, мин)",
    "sla_breached": "15 daqiqada javob berilmagan / Без ответа за 15 мин",
    "attempts": "Qo'ng'iroq urinishlari / Попытки звонков",
    "dial_rate": "Dozvon, % / Дозвон, %",
    "bookings": "Yozuvlar / Записи",
    "visits": "Tashriflar / Визиты",
    "confirmation_rate": "Tasdiqlash, % / Подтверждение, %",
    "booking_to_visit": "Yozuv → tashrif, % / Запись → визит, %",
    "no_show_rate": "Kelmaganlar, % / Неявки, %",
    "repeat_rate": "Qayta yozuv, % / Повторная запись, %",
    "returned_patients": "Qaytarilgan bemorlar / Возвращённые пациенты",
    "qa_score": "QA ball / Оценка QA",
}
DAILY_LABELS = {
    "inbound_calls": "Kiruvchi qo'ng'iroqlar / Входящие звонки",
    "inbound_missed": "Javobsiz / Пропущено",
    "outbound_calls": "Chiquvchi qo'ng'iroqlar / Исходящие звонки",
    "talk_minutes": "Suhbat, daq / Разговор, мин",
    "outbound_attempts": "Qo'ng'iroq natijalari / Результаты звонков",
    "reached": "Gaplashildi / Дозвонились",
    "dial_rate": "Dozvon, % / Дозвон, %",
    "new_leads": "Yangi murojaatlar / Новые обращения",
    "booked": "Yozilganlar / Записаны",
    "repeat_bookings": "Qayta yozuvlar / Повторные записи",
    "not_booked": "Yozilmaganlar / Не записаны",
    "cancellations": "Bekor qilishlar / Отмены",
    "reschedules": "Ko'chirishlar / Переносы",
    "no_shows": "Kelmaganlar / Неявки",
}
MIN_YEAR, MAX_YEAR = 2000, 2100  # beyond this a date is a typo (and 9999-12-31 overflows)
MAX_RANGE_DAYS = 366


def _check_day(day: date) -> None:
    if not MIN_YEAR <= day.year <= MAX_YEAR:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="bad_range")


def _check_range(date_from: date, date_to: date) -> None:
    _check_day(date_from)
    _check_day(date_to)
    if date_from > date_to or (date_to - date_from).days > MAX_RANGE_DAYS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="bad_range")


def report_filters(
    branch_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    source: Source | None = None,
    category_id: uuid.UUID | None = None,
) -> service.Filters:
    """TZ 4.11 filters: branch, operator, source (reklama manbasi), service direction."""
    return service.Filters(branch_id, user_id, source, category_id)


FiltersDep = Annotated[service.Filters, Depends(report_filters)]


@router.get("/operators")
async def operators(session: SessionDep, _: Manager) -> list[dict[str, Any]]:
    """Who the daily report can be filtered by: active operators and supervisors."""
    return await service.operators(session)


def _daily_scope(user: User, f: service.Filters) -> service.Filters:
    """An operator sees their own day; supervisors/owner/admin any operator or the whole team."""
    if user.role is Role.OPERATOR:
        return service.Filters(f.branch_id, user.id, f.source, f.category_id)
    return f


@router.get("/daily")
async def daily(
    session: SessionDep,
    user: DailyReader,
    f: FiltersDep,
    day: Annotated[date | None, Query(alias="date")] = None,
) -> dict[str, Any]:
    if day is not None:
        _check_day(day)
    f = _daily_scope(user, f)
    return await service.daily(session, day or clinic_time.today(), f.user_id, f)


@router.get("/daily.xlsx")
async def daily_xlsx(
    request: Request,
    session: SessionDep,
    user: DailyReader,
    f: FiltersDep,
    day: Annotated[date | None, Query(alias="date")] = None,
) -> Response:
    if day is not None:
        _check_day(day)
    day = day or clinic_time.today()
    f = _daily_scope(user, f)
    data = await service.daily(session, day, f.user_id, f)
    who = (await session.get(User, f.user_id)).full_name if f.user_id else "—"
    audit.record(
        session, "report.export", user_id=user.id, entity="daily",
        after={"date": str(day), **{k: v for k, v in f.as_dict().items() if v}},
        ip=client_ip(request),
    )  # fmt: skip
    await session.commit()
    return Response(
        content=service.daily_workbook(data, DAILY_LABELS, who),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="daily_{day}.xlsx"'},
    )


@router.get("/kpi")
async def kpi(
    session: SessionDep,
    _: Manager,
    f: FiltersDep,
    date_from: Annotated[date, Query(alias="from")],
    date_to: Annotated[date, Query(alias="to")],
    compare: bool = False,
) -> dict[str, Any]:
    """KPIs of the period; `compare` adds `previous` (the equally long period before it)."""
    _check_range(date_from, date_to)
    if compare:
        return await service.kpi_compared(session, date_from, date_to, f)
    return await service.kpi(session, date_from, date_to, f)


@router.get("/series")
async def series(
    session: SessionDep,
    _: Manager,
    f: FiltersDep,
    date_from: Annotated[date, Query(alias="from")],
    date_to: Annotated[date, Query(alias="to")],
) -> dict[str, Any]:
    """Daily trend figures, inquiries by source and the inquiry funnel of the period."""
    _check_range(date_from, date_to)
    return await service.series(session, date_from, date_to, f)


@router.get("/kpi.xlsx")
async def kpi_xlsx(
    request: Request,
    session: SessionDep,
    user: Manager,
    f: FiltersDep,
    date_from: Annotated[date, Query(alias="from")],
    date_to: Annotated[date, Query(alias="to")],
) -> Response:
    _check_range(date_from, date_to)
    data = await service.kpi(session, date_from, date_to, f)
    # TZ 3/8: exports are audited (who took which period's figures out of the CRM)
    audit.record(
        session, "report.export", user_id=user.id, entity="kpi",
        after={
            "from": str(date_from), "to": str(date_to),
            **{k: v for k, v in f.as_dict().items() if v},
        },
        ip=client_ip(request),
    )  # fmt: skip
    await session.commit()
    return Response(
        content=service.kpi_workbook(data, KPI_LABELS),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="kpi_{date_from}_{date_to}.xlsx"'},
    )
