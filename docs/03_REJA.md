# ISHLAB CHIQISH REJASI (bosqichlar)

Har bir bosqich **alohida ishlaydigan natija** beradi va klinikaga ko'rsatiladi. Keyingi bosqichga faqat qabul mezonlari bajarilgandan keyin o'tiladi.
Claude Code bilan ishlash tartibi: bitta sessiyada bitta vazifa (masalan, "0.3 — import"). Vazifa testlar bilan yopiladi.

---

## 0-bosqich. Asos va ma'lumotlar (~1–1.5 hafta)

| # | Vazifa | Qabul mezoni |
|---|---|---|
| 0.1 ✅ | Repozitoriy, Docker Compose (api, web, db, redis, minio, nginx), `.env.example`, CI (lint + test) | `docker compose up` bilan hammasi ko'tariladi, `/health` 200 qaytaradi |
| 0.2 ✅ | Foydalanuvchilar, rollar, login, JWT, audit, i18n (uz/ru), frontend karkasi (layout, menyu, tilni almashtirish) | 6 ta rol bilan kirish mumkin. Har bir rol faqat o'z menyusini ko'radi |
| 0.2b | Admin va rahbar uchun 2FA (TOTP) — TZ 5 talabi | Admin kirishda telefondagi ilova kodini so'raydi |
| 0.3 | Bemorlar moduli: model, CRUD, telefonni normallashtirish, translit qidiruv, dublikatlarni aniqlash | "Абдуллаев" ham, "abdullayev" ham topiladi. Takroriy raqam kiritilsa ogohlantirish chiqadi |
| 0.4 | **Import skripti**: asosiy fayl, 7 ta tuman fayli, psoriaz/vitiligo fayli, `nomer.xlsx`. F.I.Sh. katagini ajratish, xatolar hisoboti | ~6 700 bemor va ~47 500 sovuq raqam import qilinadi. Xato qatorlar alohida CSV'ga chiqadi. Qayta ishga tushirilsa dublikat yaratilmaydi |
| 0.5 | **Tashxislarni normallashtirish**: 1 422 xil yozuv → AI toifa taklif qiladi → admin panelda moslik jadvali → tasdiqlash → qo'llash | Shifokor jadvalni ko'rib tasdiqlaydi. Bemorlar toifa bo'yicha filtrlanadi |
| 0.6 | Katalogni radeski.uz'dan sinxronlash (filiallar, shifokorlar, yo'nalishlar, 806 narx) va qo'shimcha maydonlar formasi | Tungi sinxronizatsiya ishlaydi. Davomiylik va resurs qo'lda to'ldiriladi |

**Natija**: tozalangan va segmentlangan baza. Buni klinikaga darhol ko'rsatish mumkin, masalan: "trixologga tegishli alopesiyali 850 bemor".

## 1-bosqich. Jadval va yozuvlar (~2 hafta)

| # | Vazifa | Qabul mezoni |
|---|---|---|
| 1.1 | Kabinetlar, apparatlar, shifokor grafiklari, ta'tillar | Ikkala filial uchun grafik kiritilgan |
| 1.2 | Yozuv modeli, statuslar, `EXCLUDE` cheklovi (double-booking), ko'chirish va bekor qilish (sababi bilan) | Bir vaqtga ikki marta yozish imkonsiz. Ko'chirilgan yozuv tarixda saqlanadi |
| 1.3 | Bo'sh vaqt topuvchi | Xizmat tanlanganda 3 ta variant chiqadi. Lazer apparati bandligi va kurs intervali hisobga olinadi |
| 1.4 | Jadval UI: kunlik ko'rinish, shifokor yoki resurs ustunlari, filtrlar, yozuvni tez yaratish | Registrator 30 soniya ichida yozuv yaratadi |
| 1.5 | Registrator ekrani ("keldi/kelmadi") va shifokor ekrani ("keyingi qabul" tavsiyasi) | Tavsiya kiritilganda bemor kartasida ko'rinadi |

## 2-bosqich. Operator ish joyi (~2 hafta)

| # | Vazifa | Qabul mezoni |
|---|---|---|
| 2.1 | Hodisalar tizimi va vazifa qoidalari (TZ 4.5 dagi 11 ta tur), Celery Beat jadvali, idempotentlik | Har bir qoida uchun test bor. Qayta ishga tushirilsa dublikat yaratilmaydi |
| 2.2 | Vazifalar navbati UI: umumiy navbat, ustuvorlik, filtrlar, vazifa kartochkasi, natija formasi, qayta urinishlar, smena topshirish izohi | Operator ertalab tayyor ro'yxatni ko'radi. Natija kiritilganda vazifa yopiladi yoki keyingisi yaratiladi |
| 2.3 | Murojaatlar va voronka, SLA taymerlari, radeski.uz backend'iga webhook qo'shish (va zaxira tekshiruv) | Saytdan yuborilgan ariza bir necha soniyada CRM'da paydo bo'ladi. 15 daqiqa o'tsa qizarib ko'rinadi |
| 2.4 | Skriptlar moduli (12 skript, RU/UZ, o'rinlarni to'ldirish) va sabablar ma'lumotnomalari | Vazifa ochilganda to'g'ri skript bemor ma'lumotlari bilan chiqadi |
| 2.5 | Bemor kartasi: yagona tarix tasmasi | Barcha hodisalar vaqt tartibida ko'rinadi |
| 2.6 | Hisobotlar: operatorning kunlik hisoboti va KPI dashboard, Excel eksport | TZ 4.11 dagi barcha ko'rsatkichlar hisoblanadi |

**Natija**: telefoniyasiz ham ishlaydigan CRM. Operator oddiy telefondan qo'ng'iroq qilib, natijani tizimga kiritadi. Klinika shu bosqichdan boshlab tizimdan **haqiqiy foydalanishni boshlaydi**.

## 3-bosqich. Telefoniya (~1.5–2 hafta)

| # | Vazifa | Qabul mezoni |
|---|---|---|
| 3.1 | Asterisk konteyneri, Uztelecom SIP-trunk, IVR, bitta operatorli navbat (kutish musiqasi, "1 ni bosing — qayta qo'ng'iroq"), stereo yozuv | Tashqi raqamga qo'ng'iroq qilib bo'ladi. Operator band bo'lsa, ikkinchi qo'ng'iroq navbatda kutadi yoki qayta qo'ng'iroq vazifasiga aylanadi |
| 3.2 | JsSIP softfon brauzerda: kiruvchi va chiquvchi qo'ng'iroq, ushlab turish, o'chirish | Operator faqat quloqchin bilan ishlaydi |
| 3.3 | ARI hodisalari → `calls` jadvali, kiruvchi qo'ng'iroqda kartochka popup'i, javobsiz qo'ng'iroq vazifasi | Qo'ng'iroq kelganda 2 soniyada karta ochiladi |
| 3.4 | Click-to-call: vazifadan qo'ng'iroq, qo'ng'iroqni vazifa va bemorga bog'lash, yozuvni tinglash | Qo'ng'iroq jurnali to'liq, yozuvlar tinglanadi |

## 4-bosqich. AI tahlil (~2 hafta)

| # | Vazifa | Qabul mezoni |
|---|---|---|
| 4.1 | **STT benchmark**: 30 ta haqiqiy qo'ng'iroq, etalon transkript, OpenAI transkripsiya modellari (sifat yetmasa, o'zbek tiliga ixtisoslashgan zaxira provayder) | WER va narx jadvali. Model tanlanadi |
| 4.2 | STT adapteri va transkripsiya vazifasi | Qo'ng'iroq tugaganidan 5 daqiqa ichida transkript tayyor |
| 4.3 | Tahlil prompti, JSON sxema, `call_analyses`, QA mezonlarini sozlash | 30 ta qo'ng'iroqda natija va buzilishlar rahbar bahosiga ≥ 85% mos keladi |
| 4.4 | Operator UI: xulosani tasdiqlash yoki tuzatish, natijani avtomatik to'ldirish | Operator natijani 1 tugma bilan tasdiqlaydi |
| 4.5 | QA paneli va qizil bayroq bildirishnomalari | Rahbar buzilishni ko'radi va yozuvning o'sha joyini tinglaydi |
| 4.6 | Qo'ng'iroqdan oldin bemor haqida qisqa ma'lumot, haftalik AI dayjest | — |

## 5-bosqich. Kanallar va eslatmalar (~2 hafta, Meta tekshiruviga bog'liq)

| # | Vazifa |
|---|---|
| 5.1 | Telegram: bot yoki Business ulanishi, yagona inbox |
| 5.2 | SMS provayderi, shablonlar, yozuv tasdig'i va eslatmalar |
| 5.3 | Instagram Direct (Meta ilovasi tekshiruvidan o'tgach) |
| 5.4 | Chatlar uchun AI javob loyihasi |

## 6-bosqich. Rivojlantirish

- Suhbat davomida operatorga jonli maslahatchi (real vaqtdagi STT).
- Kampaniyalar UI'ni kengaytirish va A/B skriptlar.
- Kassa va to'lovlar (agar klinika xohlasa).

---

**Umumiy baho**: 1–3-bosqichlar (ishlaydigan CRM + telefoniya) taxminan 5–6 hafta. AI va kanallar bilan birga taxminan 10–12 hafta.
Bu baho bitta dasturchi Claude Code bilan kuniga to'liq ishlaganiga asoslangan va 7-bo'limdagi ochiq savollarga javobga bog'liq.
