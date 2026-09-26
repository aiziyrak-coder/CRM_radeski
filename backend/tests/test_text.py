import pytest

from app.core.text import (
    InvalidPhoneError,
    format_uz_phone,
    normalize_uz_phone,
    phone_digits_query,
    search_key,
)


@pytest.mark.parametrize(
    "raw",
    [
        "90-000-11-22",  # nomer.xlsx format
        "900001122",  # patient export format
        "+998 90 000 11 22",
        "998900001122",
        "(90) 000-11-22",
        "8 90 000 11 22",
    ],
)
def test_phone_formats_normalize_to_e164(raw: str) -> None:
    assert normalize_uz_phone(raw) == "+998900001122"


@pytest.mark.parametrize("raw", ["", "12345", "0900001122", "99890000112", "abc"])
def test_invalid_phones_rejected(raw: str) -> None:
    with pytest.raises(InvalidPhoneError):
        normalize_uz_phone(raw)


def test_format_for_display() -> None:
    assert format_uz_phone("+998900001122") == "+998 90 000-11-22"


@pytest.mark.parametrize(
    ("q", "expected"),
    [("1122", "1122"), ("90 000", "90000"), ("+998900001122", "900001122"), ("Ali", None)],
)
def test_phone_query_detection(q: str, expected: str | None) -> None:
    assert phone_digits_query(q) == expected


@pytest.mark.parametrize(
    "variants",
    [
        ("Абдуллаев", "Abdullayev", "Abdullaev", "ABDULLAYEV"),
        ("Қодиров", "Qodirov", "Kodirov", "Кодиров"),
        ("Ҳасанов", "Хасанов", "Xasanov", "Hasanov", "Khasanov"),
        ("Алиев", "Aliyev", "Aliev"),
        ("Ғофурова", "G'ofurova", "Gʻofurova", "Гофурова"),
        ("Ўринбоев", "O'rinboyev", "O‘rinboev"),
        ("Шахзодбек", "Shahzodbek", "Shaxzodbek"),
        ("Жасур", "Jasur", "Zhasur"),
    ],
)
def test_search_key_is_script_insensitive(variants: tuple[str, ...]) -> None:
    keys = {search_key(v) for v in variants}
    assert len(keys) == 1, keys


def test_search_key_keeps_word_boundaries() -> None:
    assert search_key("  Каримова   Дилноза ") == "karimova dilnoza"
