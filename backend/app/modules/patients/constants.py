"""Reference data for the Fergana region (TZ 2: most patients come from here)."""

FERGANA_DISTRICTS: tuple[str, ...] = (
    # cities
    "Farg'ona shahri",
    "Marg'ilon shahri",
    "Qo'qon shahri",
    "Quvasoy shahri",
    # districts
    "Beshariq",
    "Bog'dod",
    "Buvayda",
    "Dang'ara",
    "Farg'ona tumani",
    "Furqat",
    "Oltiariq",
    "Qo'shtepa",
    "Quva",
    "Rishton",
    "So'x",
    "Toshloq",
    "Uchko'prik",
    "O'zbekiston",
    "Yozyovon",
)

# Placeholder for records that come without a name (cold base, psoriasis/vitiligo lists).
UNKNOWN_NAME = "Ismi noma'lum"

# How places are spelled in the legacy free-text addresses (Russian, Uzbek Cyrillic, Latin).
# Matching compares app.core.text.search_key() forms, longest alias first
# (so "Кувасой" wins over "Кува").
DISTRICT_SPELLINGS: dict[str, tuple[str, ...]] = {
    "Farg'ona shahri": (
        "Фергана",
        "Ферган",
        "Фаргона",
        "Фарғона",
        "Farg'ona",
        "Fergana",
        "Киргили",
    ),
    "Farg'ona tumani": (
        "Ферганский",
        "Фарғона тумани",
        "Farg'ona tumani",
        "Водил",
        "Воодил",
        "Чимён",
        "Чимиён",
        "Чимиен",
        "Шохимардон",
        "Шоҳимардон",
    ),
    "Marg'ilon shahri": ("Маргилон", "Маргилан", "Марғилон", "Marg'ilon", "Margilan"),
    "Qo'qon shahri": ("Коканд", "Каканд", "Куканд", "Кукон", "Қўқон", "Кўкон", "Qo'qon", "Kokand"),
    "Quvasoy shahri": ("Кувасой", "Кувасай", "Қувасой", "Quvasoy", "Kuvasay"),
    "Beshariq": ("Бешарик", "Бешариқ", "Beshariq"),
    "Bog'dod": ("Богдод", "Богдот", "Боғдод", "Багдад", "Богдадский", "Bog'dod"),
    "Buvayda": ("Бувайда", "Buvayda"),
    "Dang'ara": ("Дангара", "Данғара", "Dang'ara"),
    "Furqat": ("Фуркат", "Фурқат", "Фуркатский", "Furqat"),
    "Oltiariq": ("Олтиарик", "Олтиариқ", "Олтарик", "Алтарик", "Алтыарык", "Oltiariq"),
    "Qo'shtepa": ("Куштепа", "Қўштепа", "Кўштепа", "Qo'shtepa"),
    "Quva": ("Кува", "Қува", "Quva"),
    "Rishton": ("Риштон", "Риштан", "Rishton"),
    "So'x": ("Сох", "Сўх", "Сух", "So'x"),
    "Toshloq": ("Тошлок", "Тошлоқ", "Ташлак", "Тошлак", "Toshloq"),
    "Uchko'prik": ("Учкуприк", "Учкўприк", "Учкуприқ", "Uchko'prik"),
    "O'zbekiston": ("Узбекистон", "Ўзбекистон", "Узбекистан", "Узбекистанский", "O'zbekiston"),
    "Yozyovon": ("Ёзёвон", "Ёзевон", "Езевон", "Язявон", "Язёвон", "Язъяван", "Yozyovon"),
    # outside the Fergana region, kept for segmentation
    "Andijon viloyati": ("Андижон", "Андижан", "Андижанская", "Асака", "Кургонтепа", "Andijon"),
    "Namangan viloyati": ("Наманган", "Наманганская", "Namangan"),
    "Qirg'iziston": ("Киргизистон", "Киргистан", "Киргизия", "Қирғизистон", "Кыргызстан"),
    "Toshkent": ("Ташкент", "Тошкент", "Toshkent"),
}
