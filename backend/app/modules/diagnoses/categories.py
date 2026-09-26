"""Diagnosis categories and the rules that suggest them from free-text diagnoses.

Categories drive segmentation (which specialist, which campaign). Rules are *suggestions*:
a doctor approves the text -> category mapping before it is applied (TZ 4.8.4).

Rules are evaluated in order and the first match wins, so specific rules come before general
ones ("парапсориаз" before "псориаз", "себорейный кератоз" before "себорейный дерматит").
Stems are written in natural spelling (Russian / Uzbek Cyrillic / Latin) and compared in
app.core.text.search_key form. A stem starting with "=" must match a whole word.
"""

import enum
import re
from dataclasses import dataclass
from functools import cache

from app.core.text import search_key


class Specialty(enum.StrEnum):
    DERMATOLOGIST = "dermatologist"
    TRICHOLOGIST = "trichologist"
    COSMETOLOGIST = "cosmetologist"
    ONCODERMATOLOGIST = "oncodermatologist"
    PODOLOGIST = "podologist"


@dataclass(frozen=True)
class Category:
    code: str
    name_uz: str
    name_ru: str
    specialty: Specialty
    # each alternative is a tuple of stems that must all be present
    rules: tuple[tuple[str, ...], ...] = ()
    icd: tuple[str, ...] = ()  # ICD-10 prefixes, used when no keyword matched


DERM, TRICH, COSM, ONCO, POD = (
    Specialty.DERMATOLOGIST,
    Specialty.TRICHOLOGIST,
    Specialty.COSMETOLOGIST,
    Specialty.ONCODERMATOLOGIST,
    Specialty.PODOLOGIST,
)

CATEGORIES: tuple[Category, ...] = (
    # --- hair (trichology) ---
    Category(
        "alopecia_androgenic",
        "Androgen alopesiya",
        "Андрогенная алопеция",
        TRICH,
        (("андроген",),),
        ("L64",),
    ),
    Category(
        "alopecia_areata",
        "Uchoqli (o'choqli) alopesiya",
        "Гнездная (очаговая) алопеция",
        TRICH,
        (
            ("лопец", "гнезд"),
            ("лопец", "очаг"),
            ("лопец", "очог"),
            ("лопец", "ўчок"),
            ("лопец", "учок"),
            ("лопец", "очок"),
            ("лопец", "тотал"),
            ("лопец", "универс"),
        ),
        ("L63",),
    ),
    Category(
        "alopecia_diffuse",
        "Diffuz alopesiya",
        "Диффузная алопеция",
        TRICH,
        (("лопец", "диффуз"), ("телоген",)),
        ("L65",),
    ),
    Category(
        "hair_other",
        "Boshqa soch muammolari",
        "Другие проблемы волос",
        TRICH,
        (
            ("лопец",),
            ("трихотилломан",),
            ("лейкотрих",),
            ("соч", "оқариш"),
            ("соч", "окариш"),
            ("соч", "тўкил"),
            ("соч", "тукил"),
            ("выпадени", "волос"),
            ("седин",),
            ("трихоз",),
        ),
        ("L66", "L67", "L68"),
    ),
    # --- nails & feet (podology) ---
    Category(
        "nails_feet",
        "Tirnoq va oyoq patologiyasi",
        "Патология ногтей и стоп",
        POD,
        (("оних",), ("вросш",), ("тирнок",), ("тирноқ",), ("мозол",), ("мазол",), ("ногт",)),
        ("L60", "B35.1"),
    ),
    # --- skin tumours ---
    Category(
        "skin_cancer_suspect",
        "Teri o'smasi (xavfli bo'lishi mumkin)",
        "Новообразование кожи (подозрение на злокачественное)",
        ONCO,
        (
            ("=бкр",),
            ("базалиом",),
            ("меланом",),
            ("карцином",),
            ("актиническ",),
            ("=рак",),
            ("лейкоплак",),
            ("саркома",),
        ),
        ("C43", "C44", "D04", "L57.0"),
    ),
    Category(
        "nevus",
        "Xol (nevus)",
        "Невус (родинка)",
        ONCO,
        (("невус",), ("родинк",), ("=хол",)),
        ("D22",),
    ),
    Category(
        "benign_tumor",
        "Xavfsiz o'smalar (keratoma, gemangioma, ateroma)",
        "Доброкачественные образования",
        ONCO,
        (
            ("кератоз",),
            ("кератом",),
            ("гемангиом",),
            ("ангиом",),
            ("атером",),
            ("дерматофибром",),
            ("липом",),
            ("фибром",),
            ("кист",),
            ("милиум",),
            ("ксантелазм",),
            ("гранулем",),
            ("гранулём",),
            ("гранулиом",),
            ("жировик",),
            ("сирингом",),
            ("сиренгиом",),
            ("доброкачествен",),
            ("акрохорд",),
            ("гиперплази", "сальн"),
        ),
        ("D18", "D23", "L72", "L82", "D17"),
    ),
    # --- viral growths ---
    Category(
        "warts_papilloma",
        "So'gal, papilloma, kondiloma, mollyusk",
        "Бородавки, папилломы, кондиломы, моллюск",
        DERM,
        (
            ("бородав",),
            ("сўгал",),
            ("сугал",),
            ("папиллом",),
            ("кондилом",),
            ("кондиллом",),
            ("моллюск",),
            ("молюс",),
            ("кандилом",),
            ("бороав",),
            ("бороа",),
        ),
        ("B07", "A63.0", "B08.1"),
    ),
    # --- pigmentation ---
    Category(
        "pigmentation",
        "Pigmentatsiya (melazma, xloazma, dog'lar)",
        "Нарушения пигментации (мелазма, хлоазма)",
        COSM,
        (
            ("псевдовитилиго",),
            ("мелазм",),
            ("хлоазм",),
            ("меланодерм",),
            ("пигмент",),
            ("дисхроми", "белый"),
            ("лентиго",),
            ("веснуш",),
            ("сепкил",),
        ),
        ("L81",),
    ),
    Category("vitiligo", "Vitiligo", "Витилиго", DERM, (("витилиго",), ("витилего",)), ("L80",)),
    Category("dyschromia", "Diskromiya", "Дисхромия", DERM, (("дисхроми",),)),
    # --- papulosquamous ---
    Category("parapsoriasis", "Parapsoriaz", "Парапсориаз", DERM, (("парапсориаз",),), ("L41",)),
    Category("psoriasis", "Psoriaz", "Псориаз", DERM, (("псориаз",), ("псорияз",)), ("L40",)),
    Category(
        "atopic_dermatitis",
        "Atopik dermatit, neyrodermit",
        "Атопический дерматит, нейродермит",
        DERM,
        (("атопи",), ("нейродермит",), ("нейродермат",), ("лихен", "видал")),
        ("L20", "L28.0"),
    ),
    Category(
        "lichen_other",
        "Temiratkilar (qizil yassi, pushti)",
        "Лишаи (красный плоский, розовый)",
        DERM,
        (
            ("=кпл",),
            ("красный", "плоский"),
            ("питириаз",),
            ("жибер",),
            ("розовый", "лишай"),
            ("пуштиранг", "темиратки"),
            ("лихен",),
        ),
        ("L42", "L43", "L44"),
    ),
    # --- dermatitis / eczema ---
    Category("eczema", "Ekzema", "Экзема", DERM, (("экзем",), ("экзэм",)), ("L30",)),
    Category(
        "seborrheic_dermatitis",
        "Seboreyali dermatit",
        "Себорейный дерматит",
        DERM,
        (("себоре",), ("себорея",)),
        ("L21",),
    ),
    Category(
        "contact_allergic_dermatitis",
        "Allergik va kontakt dermatit",
        "Аллергический и контактный дерматит",
        DERM,
        (
            ("аллерги",),
            ("контакт",),
            ("кантакт",),
            ("стероид", "дерматит"),
            ("фотодерматит",),
            ("таглик", "дерматит"),
            ("пеленочн",),
            ("фиксирован", "эритем"),
            ("токсикодерм",),
            ("тарвок",),
            ("дерматит",),
        ),
        ("L23", "L24", "L25", "L27"),
    ),
    Category(
        "urticaria",
        "Eshakemi (krapivnitsa)",
        "Крапивница",
        DERM,
        (("крапивниц",), ("эшакем",), ("ангионевротич",)),
        ("L50", "T78.3"),
    ),
    # --- acne / rosacea ---
    Category(
        "rosacea",
        "Rozatsea, kuperoz",
        "Розацеа, купероз",
        COSM,
        (("розаце",), ("купероз",), ("пуштиранг", "хуснбузар"), ("демодек",), ("демодекоз",)),
        ("L71",),
    ),
    Category(
        "acne",
        "Akne (husnbuzar), postakne",
        "Акне (угревая болезнь), постакне",
        COSM,
        (("акне",), ("=угр",), ("угри",), ("угрев",), ("хуснбузар",), ("ҳуснбузар",), ("комедон",)),
        ("L70",),
    ),
    # --- infections ---
    Category(
        "pyoderma",
        "Piodermiya, follikulit, furunkul",
        "Пиодермия, фолликулит, фурункул",
        DERM,
        (
            ("фолликулит",),
            ("пиодерм",),
            ("стрептодерм",),
            ("стафилодерм",),
            ("импетиго",),
            ("фурункул",),
            ("карбункул",),
            ("панариций",),
            ("гидраденит",),
            ("абсцес",),
            ("абссес",),
            ("сикоз",),
        ),
        ("L01", "L02", "L03", "L08", "L73"),
    ),
    Category(
        "fungal",
        "Zamburug' kasalliklari (mikoz, temiratki)",
        "Грибковые заболевания (микозы)",
        DERM,
        (
            ("микоз",),
            ("микроспор",),
            ("трихофит",),
            ("эпидермофит",),
            ("эпидермафит",),
            ("кандид",),
            ("фавус",),
            ("tinea",),
            ("эритразм",),
            ("разноцвет",),
            ("отрубе",),
            ("отруб",),
            ("ранг", "баранг"),
        ),
        ("B35", "B36", "B37"),
    ),
    Category(
        "herpes_viral",
        "Virusli (gerpes, ekzantema, suvchechak)",
        "Вирусные (герпес, экзантема, ветряная оспа)",
        DERM,
        (
            ("герпес",),
            ("опоясыв",),
            ("ўраб", "олувчи"),
            ("ураб", "олувчи"),
            ("экзантем",),
            ("ветрянк",),
            ("вирусн",),
            ("вирусли",),
        ),
        ("B00", "B01", "B02", "B09"),
    ),
    Category(
        "scabies_parasitic",
        "Qo'tir va parazitar",
        "Чесотка и паразитарные",
        DERM,
        (("чесотк",), ("қўтир",), ("котир",), ("кутир",), ("педикул",)),
        ("B86", "B85"),
    ),
    # --- other dermatology ---
    Category(
        "pruritus",
        "Teri qichishi",
        "Кожный зуд, почесуха",
        DERM,
        (("зуд",), ("почесух",), ("пруриго",), ("қичиш",), ("кичиш",)),
        ("L28", "L29"),
    ),
    Category(
        "scars",
        "Chandiqlar va striyalar",
        "Рубцы и стрии",
        COSM,
        (
            ("рубц",),
            ("рубец",),
            ("келоид",),
            ("чандиқ",),
            ("чандик",),
            ("стрии",),
            ("атрофическ",),
            ("шрам",),
        ),
        ("L90", "L91"),
    ),
    Category(
        "dry_skin",
        "Quruq teri, ixtioz, keratodermiya",
        "Сухость кожи, ихтиоз, кератодермия",
        DERM,
        (("ксероз",), ("ксеродерм",), ("ихтиоз",), ("кератодерм",), ("сухость",), ("кератолиз",)),
        ("L85", "Q80"),
    ),
    Category(
        "hyperhidrosis", "Giperhidroz", "Гипергидроз", COSM, (("гипергидроз",),), ("L74", "R61")
    ),
    Category(
        "autoimmune",
        "Autoimmun va qon tomir kasalliklari",
        "Аутоиммунные и сосудистые заболевания кожи",
        DERM,
        (
            ("склеродерм",),
            ("волчанк",),
            ("пемфиг",),
            ("пузырчатк",),
            ("дерматомиозит",),
            ("пемфигоид",),
            ("красная", "волчан"),
            ("васкулит",),
            ("эритродерм",),
            ("мастоцитоз",),
        ),
        ("L93", "L10", "L12", "M34", "M33"),
    ),
    # --- non-diagnoses ---
    Category(
        "cosmetic",
        "Kosmetologik muolajalar",
        "Косметологические процедуры",
        COSM,
        (
            ("процедур",),
            ("не имеющие лечебных",),
            ("косметолог",),
            ("эпиляц",),
            ("татуаж",),
            ("биоревитализ",),
            ("чистк",),
            ("пилинг",),
            ("омолож",),
        ),
        ("Z41",),
    ),
    Category(
        "checkup",
        "Ko'rik / tekshiruv (tashxissiz)",
        "Осмотр / обследование (без диагноза)",
        DERM,
        (("=обс",), ("обслед",), ("консультац",), ("осмотр",), ("здоров",)),
        ("Z00", "Z01"),
    ),
    Category("other", "Boshqa", "Другое", DERM),
)

CATEGORY_BY_CODE: dict[str, Category] = {c.code: c for c in CATEGORIES}

_SPLIT = re.compile(r"[,.;:+/\n]|\bва\b|\bи\b|\bва\s", re.IGNORECASE)
_ICD = re.compile(r"\b([a-z])\s?(\d{2})(?:\s?\.?\s?(\d))?", re.IGNORECASE)


def normalize_text(raw: str) -> str:
    """Key under which identical diagnoses written slightly differently share one mapping."""
    text = re.sub(r"\s+", " ", raw or "").strip().lower()
    return text.strip(" ,.;:-?!")


@cache
def _compiled() -> list[tuple[str, list[list[re.Pattern[str]]], tuple[str, ...]]]:
    compiled = []
    for cat in CATEGORIES:
        alternatives = []
        for alt in cat.rules:
            patterns = []
            for stem in alt:
                whole = stem.startswith("=")
                key = search_key(stem.lstrip("="))
                patterns.append(re.compile(rf"\b{re.escape(key)}\b" if whole else re.escape(key)))
            alternatives.append(patterns)
        compiled.append((cat.code, alternatives, cat.icd))
    return compiled


def _by_keywords(part: str) -> str | None:
    key = search_key(re.sub(r"[^\w\s]", " ", part))
    for code, alternatives, _ in _compiled():
        if any(all(p.search(key) for p in alt) for alt in alternatives):
            return code
    return None


def _by_icd(text: str) -> str | None:
    for letter, major, minor in _ICD.findall(text):
        full = f"{letter.upper()}{major}" + (f".{minor}" if minor else "")
        # most specific prefix wins (B35.1 nails before B35 fungal)
        best = max(
            ((len(p), code) for code, _, icds in _compiled() for p in icds if full.startswith(p)),
            default=None,
        )
        if best:
            return best[1]
    return None


def suggest_category(raw: str) -> str | None:
    """Category of the first diagnosis mentioned in the text, or None if no rule matched."""
    text = normalize_text(raw)
    if not text:
        return None
    for part in _SPLIT.split(text):
        if part.strip() and (code := _by_keywords(part)):
            return code
    return _by_icd(text)
