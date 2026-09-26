# ARXITEKTURA
## Radeski CRM + AI koll-markaz

Versiya 0.1 · 2026-09-26 · TZ bilan birga o'qiladi: [01_TZ.md](01_TZ.md)

---

## 1. Umumiy sxema

```
                ┌────────────────────────── Klinika serveri (O'zbekiston) ──────────────────────────┐
                │                                                                                    │
 Operator ──────┼─► nginx (HTTPS, crm.radeski.uz) ─┬─► web (React SPA, statik fayllar)                │
 brauzeri       │                                  ├─► api (FastAPI) ◄──► PostgreSQL 16              │
 (+ WebRTC      │                                  │        │   ▲         Redis 7 (navbat, kesh,     │
  softfon)      │                                  │        │   │          pub/sub)                  │
      │         │                                  └─► ws (WebSocket: qo'ng'iroq popup, vazifalar)  │
      │         │                                           │   │                                   │
      │  WSS/   │                                  worker (Celery) + beat (jadval bo'yicha ishlar)  │
      │  SRTP   │                                     │     │     │            │                    │
      └─────────┼─► Asterisk 20 (PJSIP, WebRTC) ──────┘     │     │            ▼                    │
                │      │  ARI/AMI hodisalari                │     │       MinIO (qo'ng'iroq yozuvlari│
                │      │  MixMonitor stereo yozuv ──────────┼─────┼─────►  S3-mos saqlash)          │
                └──────┼────────────────────────────────────┼─────┼────────────────────────────────┘
                       │                                    │     │
               Uztelecom SIP-trunk                          │     └──► OpenAI API: STT (transkripsiya)
               (virtual raqam)                              └───────► OpenAI API: LLM (tahlil, JSON chiqish)
                                                                  ├──► api.radeski.uz (katalog, sayt arizalari)
                                                                  ├──► Telegram Bot API / Instagram Graph API
                                                                  └──► SMS provayder (Eskiz / Playmobile)
```

**Asosiy tamoyillar:**
- **Modulli monolit.** Bitta backend ichida TZ'dagi M-01…M-11 modullari alohida paketlar sifatida turadi. Foydalanuvchilar ~15 ta (smenada bitta operator) bo'lgani uchun mikroservislar keraksiz murakkablik qo'shadi.
- **Hamma narsa bitta serverda, Docker Compose bilan.** Baza va qo'ng'iroq yozuvlari O'zbekistondagi serverda **saqlanadi**. Tahlil uchun OpenAI'ga faqat alohida qo'ng'iroq audiosi va transkripti vaqtincha yuboriladi (5-bo'lim).
- **Tashqi xizmatlar adapter orqali ulanadi.** STT, LLM, SMS va telefoniya uchun bir xil interfeys bo'ladi. Shunda provayderni kod o'zgartirmasdan almashtirish mumkin.
- **Og'ir ishlar orqa fonda bajariladi.** STT, AI tahlil, import, sinxronizatsiya va vazifa generatsiyasi worker navbatida ishlaydi, API tez javob beradi.

---

## 2. Texnologiyalar steki

| Qatlam | Tanlov | Nega |
|---|---|---|
| Backend | **Python 3.12, FastAPI**, Pydantic v2, SQLAlchemy 2 (async), Alembic | radeski.uz ham FastAPI'da. AI va ma'lumot bilan ishlash ekotizimi Python'da. Claude Code bu stekni yaxshi biladi |
| Fon vazifalari | **Celery + Celery Beat** (broker: Redis) | Jadval bo'yicha ishlar (07:30 tasdiqlash, sinxronizatsiya) va navbatlar uchun |
| Ma'lumotlar bazasi | **PostgreSQL 16** + `pg_trgm`, `unaccent` | Qidiruv (trigram), JSONB (AI natijalari), ishonchlilik |
| Kesh va real vaqt | **Redis 7** | Celery broker, pub/sub orqali WebSocket'ga hodisalar |
| Frontend | **React 19 + Vite + TypeScript**, Tailwind, shadcn/ui, TanStack Query, React Router, i18next (uz/ru) | Sayt ham Vite/React'da. Komponentlar tayyor |
| Kalendar | **react-big-calendar** (MIT, resurs ko'rinishi bor) | FullCalendar'ning resurs rejimi pullik litsenziya talab qiladi |
| Softfon | **JsSIP** (WebRTC) | Brauzerdan qo'ng'iroq qilish uchun |
| ATS | **Asterisk 20** (PJSIP, ARI) | Bepul, o'z serverda ishlaydi, stereo yozuv qiladi, Uztelecom SIP-trunk bilan ishlaydi |
| Fayl saqlash | **MinIO** | Qo'ng'iroq yozuvlari va import fayllari uchun |
| LLM | **OpenAI API** (rasmiy `openai` Python SDK, API kalit bilan), JSON sxema bo'yicha structured outputs | Jamoa qarori. Aniq model benchmarkda tanlanadi. Adapter orqali ulanadi, kerak bo'lsa boshqa provayderga almashtiriladi |
| STT | **OpenAI transkripsiya API** (serverda GPU yo'q) | O'zbekcha aralash nutq sifati haqiqiy yozuvlarda tekshiriladi (4.2-bo'lim). Adapter tufayli natija yomon bo'lsa, boshqa provayderga almashtirish mumkin |
| Joylashtirish | Docker Compose, nginx + Let's Encrypt | Bitta server, oddiy boshqaruv |
| Monitoring | Sentry (self-hosted yoki bulut), healthcheck, Uptime Kuma | Xatolar va to'xtab qolishlarni ko'rish uchun |

---

## 3. Ma'lumotlar modeli (asosiy jadvallar)

```
branches ─┬─ rooms (kabinetlar)
          └─ equipment (apparatlar: lazer, CO₂, Excimer…)

users (rol: operator | supervisor | registrar | doctor | owner | admin; til; filial)
doctors (user_id, mutaxassisliklar[], site_doctor_id)
doctor_schedules (doctor, branch, hafta_kuni, boshlanish, tugash, tanaffus)
doctor_absences (doctor, sana_dan, sana_gacha, sabab)

service_categories (site_id, nom_uz, nom_ru)            ← radeski.uz'dan
services (site_price_id, category, nom_uz, nom_ru, narx,
          davomiylik_min, resurs_turi, oldin_konsultatsiya,
          kurs_seanslar, min_interval_kun, keyingi_qongiroq_kun,
          tayyorgarlik_uz, tayyorgarlik_ru, faol)
doctor_services (doctor, service)

patients (fio, fio_translit, tugilgan_sana, jins, manzil, tuman, til,
          tur: faol|import|sovuq|lid, manba, teglar[], dnc (qo'ng'iroq qilinmasin),
          birinchi_murojaat, oxirgi_tashrif, legacy_ref)
patient_phones (patient, raqam_e164, asosiy, izoh)       — UNIQUE(raqam_e164) (ogohlantirish bilan)
diagnosis_categories (kod, nom_uz, nom_ru, mutaxassislik)
diagnosis_mappings (xom_matn → category, tasdiqlagan, sana)
patient_conditions (patient, category, xom_matn, manba)

appointments (patient, branch, doctor, room?, equipment?, boshlanish, tugash,
              status, manba, lead?, avvalgi_yozuv?, bekor_sababi?, yaratgan)
appointment_services (appointment, service, zona?)
recommendations (patient, doctor, appointment, muddat_sana, service?, izoh, holat)

leads (patient?, telefon, kanal, reklama_manbasi, qiziqish, bosqich,
       yoqotish_sababi?, masul_operator, sla_muddat, birinchi_javob_vaqti)

tasks (tur, patient, lead?, appointment?, campaign?, masul?, muddat, ustuvorlik,
       urinishlar, holat: ochiq|jarayonda|bajarildi|bekor, natija, natija_sababi, skript_kodi)
       — qoida bo'yicha takrorlanmaslik uchun: UNIQUE(tur, manba_obyekt, sana)

calls (yonalish, dan, ga, operator, patient?, task?, lead?, boshlanish, javob, tugash,
       kutish_s, davomiylik_s, holat, yozuv_kaliti, asterisk_uniqueid)
call_transcripts (call, provayder, til, segmentlar JSONB [{kanal, boshlanish, tugash, matn}])
call_analyses (call, model, prompt_versiya, suhbat_turi, ball, mezonlar JSONB,
               buzilishlar JSONB [{mezon, iqtibos, vaqt}], qizil_bayroqlar[], xulosa,
               natija_taklif, sabab_taklif, ajratilgan JSONB, operator_tasdiqladi, tuzatishlar JSONB)

conversations (kanal, tashqi_id, patient?, lead?)  /  messages (conversation, yo'nalish, matn,
               operator?, ai_taklif?, yuborildi)

campaigns (nom, segment_filtri JSONB, skript, operatorlar[], kunlik_limit, holat, muddat)
campaign_members (campaign, patient, holat, natija)

scripts (kod, sarlavha, til, matn_md, eslatmalar)
qa_criteria (kod, nom, tavsif, vazn, faol)
reasons (tur: rad|kelmaslik|bekor|yoqotish, kod, nom_uz, nom_ru)
message_templates (kod, kanal, til, matn, provayder_shablon_id)
settings (kalit, qiymat)            audit_log (user, amal, obyekt, oldin, keyin, vaqt)
```

**Muhim qarorlar:**
- `fio_translit` ustunida F.I.Sh.ning kirill→lotin normallashtirilgan varianti saqlanadi va `pg_trgm` indeksi qo'yiladi. Qidiruv so'rovi ham shu tartibda normallashtiriladi. Shunda "Абдуллаев" va "Abdullayev" bir xil topiladi.
- Telefon har doim E.164 formatida saqlanadi (`+998901234567`). Barcha kirish nuqtalari normallashtirishdan o'tadi: import, forma, telefoniya.
- Barcha statuslar Python `Enum` ko'rinishida saqlanadi. O'tishlar faqat servis funksiyalari orqali bajariladi va har bir o'tish hodisa chiqaradi.

---

## 4. Asosiy jarayonlar

### 4.1. Hodisalar va vazifalar dvigateli

Statuslar faqat servis qatlamida o'zgaradi. Har bir o'zgarish domen hodisasini chiqaradi, `rules` moduli unga obuna bo'lib vazifa yaratadi yoki yopadi.

| Hodisa | Qoida (TZ 4.5) |
|---|---|
| `appointment.status → kelmadi` | "Kelmagan bemor" vazifasi |
| `appointment.status → yakunlandi` va xizmatda `keyingi_qongiroq_kun` bor | "Muolajadan keyingi qo'ng'iroq" vazifasi (N kundan keyin) |
| `recommendation.created` | "Qayta qabul" vazifasi (muddatdan 3 kun oldin) |
| `appointment.created` shu bemor uchun | Tegishli qayta qabul, kurs va reaktivatsiya vazifalari avtomatik yopiladi |
| `call.missed` | "Javobsiz qo'ng'iroq" vazifasi, 15 daqiqa SLA |
| `lead.created` | "Yangi murojaat" vazifasi va SLA taymeri |

**Beat jadvali:**

| Vaqt | Ish |
|---|---|
| 07:30 | Bugungi yozuvlar uchun tasdiqlash vazifalari |
| Har 5 daqiqa | SLA muddati o'tgan murojaatlarni tekshirish va ogohlantirish |
| Har 5 daqiqa | Sayt arizalarini zaxira tekshiruvi (asosiy yo'l — webhook) |
| 02:00 | Katalogni sinxronlash, 24 soatlik "yo'qolgan murojaat" tekshiruvi, reaktivatsiya, kurs davomi |
| 19:00 | Kunlik hisobot snapshot'i |
| Dushanba 08:00 | Haftalik AI dayjest |

Barcha generatorlar **idempotent**: bir xil ish qayta ishga tushsa, dublikat vazifa yaratilmaydi (`tasks` dagi UNIQUE kalit). Xizmat davomiyligi va intervallar kabi qiymatlar `settings` jadvalidan olinadi, kodda qotirilmaydi.

### 4.2. Qo'ng'iroqni tahlil qilish konveyeri

```
Asterisk: qo'ng'iroq tugadi (ARI StasisEnd / AMI Hangup)
  → api: calls yozuvi yangilanadi, yozuv MinIO'ga yuklanadi
  → worker: transcribe(call)
        stereo → 2 kanal (L = operator, R = bemor)
        STT adapter → segmentlar [{kanal, t0, t1, matn}]
  → worker: analyze(call)
        OpenAI API (LLM, JSON sxema bo'yicha structured outputs)
          system: rol + 12 skript + qa_criteria + reasons ma'lumotnomasi (o'zgarmas, keshlanadi)
          user:   transkript (telefon raqamlarisiz) + suhbat konteksti (vazifa turi)
          chiqish: JSON sxema → call_analyses
  → ws: operatorga "AI xulosasi tayyor" xabari. Operator natijani tasdiqlaydi yoki tuzatadi
  → qizil bayroq bo'lsa: supervisorga bildirishnoma
```

- **STT sinovi (4-bosqichning birinchi ishi).** Serverda GPU yo'q, asosiy tanlov OpenAI transkripsiya API. Klinikaning 30 ta haqiqiy qo'ng'iroq yozuvi qo'lda transkripsiya qilinadi (etalon), so'ng OpenAI'ning transkripsiya modellari WER va 1 daqiqa narxi bo'yicha solishtiriladi. O'zbekcha (ayniqsa sheva va rus tili aralash) nutqda sifat yetarli bo'lmasa, adapter orqali o'zbek tiliga ixtisoslashgan bulutli STT ham sinab ko'riladi. Ikki kanalli (stereo) yozuv har kanalni alohida transkripsiya qilish imkonini beradi, bu sifatni oshiradi.
- **LLM chiqishi faqat sxema bo'yicha.** OpenAI'ning structured outputs (JSON Schema, strict) rejimi ishlatiladi. Natija Pydantic bilan tekshiriladi, xato bo'lsa bir marta qayta urinish qilinadi.
- **Keshlash.** Skriptlar, mezonlar va ma'lumotnomalar tizim promptining o'zgarmas qismida turadi (OpenAI takrorlanuvchi prefiksni avtomatik keshlaydi). Bu narxni sezilarli kamaytiradi, shuning uchun o'zgaruvchan qism (transkript) promptning oxirida turadi.
- **Sifat nazorati.** Operatorlarning tuzatishlari (`call_analyses.tuzatishlar`) eval to'plamiga aylanadi. Promptning har bir yangi versiyasi shu to'plamda tekshiriladi va `prompt_versiya` saqlanadi.
- **Rad javobi va xatolar.** Javobning yakunlanish sababi va refusal maydoni tekshiriladi, 429/5xx xatolarda qayta urinish qilinadi. Tahlil muvaffaqiyatsiz bo'lsa, qo'ng'iroq "qo'lda ko'rib chiqish" ro'yxatiga tushadi. Qo'ng'iroq jarayoni hech qachon to'xtab qolmaydi.

### 4.3. Kiruvchi qo'ng'iroq

```
Uztelecom → Asterisk: IVR (salom + "suhbat yozib olinadi") → queue(operators, ringall, 30s)
   ARI hodisasi → api: raqam bo'yicha bemor yoki murojaat qidiriladi (yo'q bo'lsa lead yaratiladi)
   → ws → operator brauzerida kartochka ochiladi, qo'ng'iroq JsSIP'da jiringlaydi
   30s ichida javob yo'q yoki ish vaqtidan tashqari → ovozli xabar + call.missed → vazifa
```

### 4.4. Bo'sh vaqt topuvchi (slot finder)

Kirish ma'lumotlari: xizmat(lar), filial, (ixtiyoriy) shifokor, qidiruv oralig'i, kunning qismi.
1. Xizmatni bajaradigan shifokorlar tanlanadi (`doctor_services`).
2. Har bir shifokor uchun grafik olinadi, band yozuvlar va ta'tillar chiqarib tashlanadi. Qolgan bo'sh oraliqlar xizmat davomiyligi bo'yicha qadamlarga bo'linadi.
3. Resurs bandligi bilan kesishma olinadi (kabinet yoki apparat).
4. Kurs intervali qoidasi qo'llanadi: shu xizmatning oxirgi seansidan beri `min_interval_kun` o'tgan bo'lishi kerak.
5. Natija saralanadi (eng yaqin vaqt, afzal ko'rilgan kun qismi) va eng yaxshi 3 varianti qaytariladi.

Yozuvni saqlash tranzaksiya ichida bajariladi. Double-booking PostgreSQL darajasida `EXCLUDE USING gist` cheklovi bilan bloklanadi: shifokor va vaqt oralig'i, resurs va vaqt oralig'i ustma-ust tushmasligi kerak.

### 4.5. Tashqi integratsiyalar

| Tizim | Yo'nalish | Usul |
|---|---|---|
| radeski.uz katalog | sayt → CRM | Tungi `GET /api/doctors, /services, /prices, /branches`. `site_*_id` bo'yicha upsert. Saytda o'chirilgan pozitsiya CRM'da `faol=false` bo'ladi |
| radeski.uz arizalar | sayt ↔ CRM | Sayt bizning jamoaniki va shu serverda. `POST /api/appointments` bajarilganda sayt backend'i CRM'ga **webhook** yuboradi (HMAC imzo bilan, ichki tarmoq orqali). Arizadan lead yaratiladi, keyin `PATCH /api/admin/appointments/{id}` bilan saytdagi status yangilanadi. Zaxira: har 5 daqiqada `GET /api/admin/appointments` |
| Telegram | ikki tomonlama | Bot API webhook (yoki Telegram Business ulanishi) → conversations/messages |
| Instagram | ikki tomonlama | Meta Graph API (Instagram Messaging). Meta ilovasi tekshiruvdan o'tishi kerak, bu vaqt oladi |
| SMS | CRM → bemor | Provayder adapteri (Eskiz yoki Playmobile), faqat tasdiqlangan shablonlar |
| Uztelecom | ikki tomonlama | Asterisk'da SIP-trunk (PJSIP registratsiyasi) |

---

## 5. Xavfsizlik va shaxsiy ma'lumotlar

- **Autentifikatsiya**: login va parol (argon2 hash). JWT access token (15 daqiqa) va refresh token (httpOnly cookie). Admin va rahbar uchun TOTP 2FA.
- **Avtorizatsiya**: rol va filial bo'yicha. Har bir endpoint'da `require_role(...)` dekoratori. Shifokor faqat o'z bemorlarining tavsiyalarini ko'radi.
- **Audit**: bemor kartasini ochish, eksport qilish va yozuvni tinglash `audit_log` ga yoziladi.
- **Tashqi AI'ga yuborish (OpenAI)**: STT uchun **qo'ng'iroq audiosining o'zi** yuboriladi. Audioda ism va raqamni niqoblab bo'lmaydi, shuning uchun uchta chora ko'riladi: (1) IVR'da "suhbat yozib olinadi va sifat nazorati uchun tahlil qilinadi" ogohlantirishi; (2) OpenAI tashkilot sozlamalarida ma'lumotni o'qitishda ishlatmaslik va minimal saqlash muddati; (3) LLM'ga ketadigan transkriptda telefon va hujjat raqamlari regex bilan niqoblanadi, bemor ID'si o'rniga vaqtinchalik kalit ishlatiladi. Yakuniy sxemani yurist tasdiqlashi kerak.
- **Sirlar**: `.env` fayli serverda turadi, git'ga kirmaydi. API kalitlar faqat backend'da saqlanadi.
- **Tarmoq**: tashqariga faqat 443 (nginx) va SIP/RTP portlari (faqat Uztelecom IP'lari uchun) ochiladi. Baza, Redis va MinIO faqat ichki Docker tarmog'ida.
- **Zaxira**: har kuni `pg_dump` + MinIO mirror ikkinchi diskka yoki O'zbekistondagi ikkinchi serverga. Oyiga bir marta tiklash sinovi o'tkaziladi.

---

## 6. Repozitoriy tuzilmasi

```
CRM_radeski/
├── CLAUDE.md                 # Claude Code uchun qoidalar
├── docker-compose.yml        # api, worker, beat, web, db, redis, minio, asterisk, nginx
├── .env.example
├── docs/                     # TZ, arxitektura, reja, seed ma'lumotlar (ochiq)
├── backend/
│   ├── pyproject.toml
│   ├── alembic/
│   ├── app/
│   │   ├── main.py  core/ (config, db, security, events, i18n)
│   │   ├── modules/
│   │   │   ├── patients/  catalog/  scheduling/  leads/  tasks/  scripts/
│   │   │   ├── telephony/ ai/  campaigns/  messaging/  reports/  users/  audit/
│   │   │   │   (har birida: models.py schemas.py service.py router.py tasks.py)
│   │   ├── integrations/ (site_api, asterisk, stt/, llm/, sms/, telegram/, instagram/)
│   │   └── workers/ (celery_app.py, beat_schedule.py)
│   └── tests/
├── frontend/
│   └── src/ (pages/, features/<modul>/, components/ui, lib/api, i18n/{uz,ru}.json, softphone/)
├── telephony/asterisk/       # pjsip.conf, extensions.conf, ari.conf shablonlari
├── scripts/import/           # bir martalik Excel importi va tozalash
└── data/                     # ⚠ haqiqiy bemor fayllari — .gitignore'da, hech qachon commit qilinmaydi
```

---

## 7. Server talablari (dastlabki baho)

Server bitta, unda radeski.uz ham turibdi. GPU yo'q: STT va LLM OpenAI API orqali ishlaydi.

| Komponent | Resurs (taxminiy) |
|---|---|
| CRM (api, worker, web, PostgreSQL, Redis, MinIO) + Asterisk | 2–4 vCPU, 4–8 GB RAM |
| radeski.uz (mavjud) | Hozirgi iste'moli o'lchanadi |
| Qo'ng'iroq yozuvlari | Kuniga ~150 qo'ng'iroq × 3 daqiqa ≈ oyiga ~5–10 GB (opus/mp3 formatida). 12 oy uchun 100 GB zaxira |
| **Jami tavsiya** | **4 vCPU, 8–16 GB RAM, 200 GB SSD** |

- Sayt va CRM alohida Docker Compose loyihalari va alohida bazalar sifatida ishlaydi, umumiy nginx orqali ulanadi: `radeski.uz` va `crm.radeski.uz`. CRM'dagi xato saytni to'xtatib qo'ymasligi kerak.
- Asterisk'ning SIP va RTP portlari firewall'da faqat Uztelecom IP manzillari uchun ochiladi.
