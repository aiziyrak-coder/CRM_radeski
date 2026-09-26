"""Shared test helpers (no fixtures here — those live in conftest.py)."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Tashkent")


def next_monday() -> date:
    today = date.today()
    return today + timedelta(days=(7 - today.weekday()) % 7 or 7) + timedelta(days=7)


def at(day: date, hh: int, mm: int = 0) -> str:
    return datetime.combine(day, time(hh, mm), TZ).isoformat()


def booking(c: dict, starts_at: str, doctor: str = "d1", service: str = "consult", **extra) -> dict:
    return {
        "patient_id": c["patient"],
        "branch_id": c["branch"],
        "doctor_id": c[doctor],
        "service_ids": [c[service]],
        "starts_at": starts_at,
        **extra,
    }
