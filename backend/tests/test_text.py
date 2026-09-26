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
        "90-165-43-41",  # nomer.xlsx format
        "901654341",  # patient export format
        "+998 90 165 43 41",
        "998901654341",
        "(90) 165-43-41",
        "8 90 165 43 41",
    ],
)
def test_phone_formats_normalize_to_e164(raw: str) -> None:
    assert normalize_uz_phone(raw) == "+998901654341"


@pytest.mark.parametrize("raw", ["", "12345", "0901654341", "99890165434", "abc"])
def test_invalid_phones_rejected(raw: str) -> None:
    with pytest.raises(InvalidPhoneError):
        normalize_uz_phone(raw)


def test_format_for_display() -> None:
    assert format_uz_phone("+998901654341") == "+998 90 165-43-41"


@pytest.mark.parametrize(
    ("q", "expected"),
    [("4341", "4341"), ("90 165", "90165"), ("+998901654341", "901654341"), ("Ali", None)],
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
