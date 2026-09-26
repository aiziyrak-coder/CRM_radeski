import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response

from app.core import clinic_time
from app.core.deps import CurrentUser, SessionDep, require_roles
from app.modules.reports import service
from app.modules.users.models import Role, User

router = APIRouter(prefix="/reports", tags=["reports"])
Manager = Annotated[User, Depends(require_roles(Role.SUPERVISOR, Role.OWNER, Role.ADMIN))]

KPI_LABELS = {
    "inbound_calls": "Kiruvchi qo'ng'iroqlar / Входящие звонки",
    "inbound_answer_rate": "Javob berilgan, % / Отвечено, %",
    "inbound_missed": "Javobsiz / Пропущено",
    "avg_wait_sec": "O'rtacha kutish, s / Среднее ожидание, с",
    "outbound_calls": "Chiquvchi qo'ng'iroqlar / Исходящие звонки",
    "talk_minutes": "Suhbat, daq / Разговор, мин",
    "leads_total": "Murojaatlar / Обращения",
    "lead_to_booking": "Murojaat → yozuv, % / Обращение → запись, %",
    "first_response_median_min": "Birinchi javob (mediana, daq) / Первый ответ (медиана, мин)",
    "sla_breached": "15 daqiqada javob berilmagan / Без ответа за 15 мин",
    "attempts": "Qo'ng'iroq urinishlari / Попытки звонков",
    "dial_rate": "Dozvon, % / Дозвон, %",
    "confirmation_rate": "Tasdiqlash, % / Подтверждение, %",
    "booking_to_visit": "Yozuv → tashrif, % / Запись → визит, %",
    "no_show_rate": "Kelmaganlar, % / Неявки, %",
    "repeat_rate": "Qayta yozuv, % / Повторная запись, %",
    "returned_patients": "Qaytarilgan bemorlar / Возвращённые пациенты",
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


@router.get("/operators")
async def operators(session: SessionDep, _: Manager) -> list[dict[str, Any]]:
    """Who the daily report can be filtered by: active operators and supervisors."""
    return await service.operators(session)


@router.get("/daily")
async def daily(
    session: SessionDep,
    user: CurrentUser,
    day: Annotated[date | None, Query(alias="date")] = None,
    user_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """An operator sees their own day; supervisors/owner/admin any operator or the whole team."""
    if user.role is Role.OPERATOR:
        user_id = user.id
    elif user.role not in (Role.SUPERVISOR, Role.OWNER, Role.ADMIN):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="forbidden")
    if day is not None:
        _check_day(day)
    return await service.daily(session, day or clinic_time.today(), user_id)


@router.get("/kpi")
async def kpi(
    session: SessionDep,
    _: Manager,
    date_from: Annotated[date, Query(alias="from")],
    date_to: Annotated[date, Query(alias="to")],
) -> dict[str, Any]:
    _check_range(date_from, date_to)
    return await service.kpi(session, date_from, date_to)


@router.get("/kpi.xlsx")
async def kpi_xlsx(
    session: SessionDep,
    _: Manager,
    date_from: Annotated[date, Query(alias="from")],
    date_to: Annotated[date, Query(alias="to")],
) -> Response:
    _check_range(date_from, date_to)
    data = await service.kpi(session, date_from, date_to)
    return Response(
        content=service.kpi_workbook(data, KPI_LABELS),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="kpi_{date_from}_{date_to}.xlsx"'},
    )
