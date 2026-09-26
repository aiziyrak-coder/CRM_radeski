"""Normalization helpers for Uzbek data: phone numbers and script-insensitive name search.

The clinic's data mixes Russian Cyrillic, Uzbek Cyrillic and Uzbek Latin with inconsistent
romanization ("Абдуллаев" / "Abdullayev" / "Abdullaev", "Қодиров" / "Qodirov" / "Kodirov").
`search_key` folds all of these to one comparable form; pg_trgm handles the remaining typos.
"""

import re
import unicodedata

# --- phones -----------------------------------------------------------------------------------

_UZ_NATIONAL_LEN = 9


class InvalidPhoneError(ValueError):
    pass


def normalize_uz_phone(raw: str) -> str:
    """'90-000-11-22', '900001122', '+998 90 000 11 22', '8 90 000 11 22' -> '+998900001122'."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 12 and digits.startswith("998"):
        digits = digits[3:]
    elif len(digits) == 10 and digits.startswith("8"):  # old domestic long-distance prefix
        digits = digits[1:]
    if len(digits) != _UZ_NATIONAL_LEN or digits[0] == "0":
        raise InvalidPhoneError(raw)
    return f"+998{digits}"


def format_uz_phone(e164: str) -> str:
    """'+998900001122' -> '+998 90 000-11-22' (display only)."""
    d = e164.removeprefix("+998")
    if len(d) != _UZ_NATIONAL_LEN:
        return e164
    return f"+998 {d[:2]} {d[2:5]}-{d[5:7]}-{d[7:]}"


def phone_digits_query(q: str) -> str | None:
    """If a search query looks like (part of) a phone number, return its significant digits."""
    digits = re.sub(r"\D", "", q)
    if len(digits) < 4 or len(digits) < len(re.sub(r"\s", "", q)) * 0.6:
        return None
    if digits.startswith("998") and len(digits) > 9:
        digits = digits[3:]
    return digits


# --- script-insensitive search key -------------------------------------------------------------

_CYR = {
    "а": "a", "б": "b", "в": "v", "г": "g", "ғ": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "j", "з": "z", "и": "i", "й": "y", "к": "k", "қ": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "ө": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ў": "o", "ф": "f", "х": "x", "ҳ": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh",
    "ъ": "", "ы": "i", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}  # fmt: skip

# applied in order, after transliteration; digraphs are protected before single-letter folds
_FOLDS: tuple[tuple[str, str], ...] = (
    ("sh", "\x01"),
    ("ch", "\x02"),
    ("kh", "x"),  # Russian-style romanization of Х
    ("zh", "j"),
    ("dj", "j"),
    ("q", "k"),  # Qodirov / Kodirov / Қодиров
    ("h", "x"),  # Hasan / Xasan / Ҳасан / Хасан
    ("ye", "e"),  # Abdullayev / Абдуллаев
    ("iy", "i"),  # Aliyev / Алиев
    ("yo", "o"),
    ("\x01", "sh"),
    ("\x02", "ch"),
)


def search_key(text: str) -> str:
    s = unicodedata.normalize("NFKC", text or "").lower()
    s = "".join(_CYR.get(ch, ch) for ch in s)
    # Uzbek Latin apostrophes (o', g', ʻ, ’, `) carry no meaning for matching
    s = re.sub(r"[^a-z0-9\s]", "", s)
    for old, new in _FOLDS:
        s = s.replace(old, new)
    return re.sub(r"\s+", " ", s).strip()
