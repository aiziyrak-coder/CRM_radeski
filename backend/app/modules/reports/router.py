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
    return await service.daily(session, day or clinic_time.today(), user_id)


@router.get("/kpi")
async def kpi(
    session: SessionDep,
    _: Manager,
    date_from: Annotated[date, Query(alias="from")],
    date_to: Annotated[date, Query(alias="to")],
) -> dict[str, Any]:
    if date_from > date_to or (date_to - date_from).days > 366:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="bad_range")
    return await service.kpi(session, date_from, date_to)


@router.get("/kpi.xlsx")
async def kpi_xlsx(
    session: SessionDep,
    _: Manager,
    date_from: Annotated[date, Query(alias="from")],
    date_to: Annotated[date, Query(alias="to")],
) -> Response:
    data = await service.kpi(session, date_from, date_to)
    return Response(
        content=service.kpi_workbook(data, KPI_LABELS),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="kpi_{date_from}_{date_to}.xlsx"'},
    )
