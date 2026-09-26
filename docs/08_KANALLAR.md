# Kanallar va eslatmalar (5-bosqich)

## Nima ishlaydi

- **Yagona inbox** (“Chatlar”): Telegram, Instagram Direct va SMS yozishmalari bitta oynada.
  Yangi yozgan odamdan **murojaat** va “Yangi murojaat” vazifasi (15 daqiqalik SLA) yaratiladi;
  operator javob berganda murojaat “bog'lanildi” bo'ladi. Suhbatni bemor kartasiga bog'lash,
  qabulga yozish, shablon qo'yish va **AI javob loyihasi** (operator o'qib, tuzatib yuboradi —
  AI o'zi hech narsa yubormaydi).
- Telegram'da bemor telefon raqamini yuborsa (tugma bilan), suhbat bazadagi bemorga avtomatik
  bog'lanadi.
- **Avtomatik xabarlar** (faqat tasdiqlangan shablonlar, TZ 4.10):
  - yozuv yaratilganda — tasdiq (2-skriptdagi va'da);
  - qabuldan bir kun oldin soat 10:00 da — eslatma (xizmatning tayyorgarlik matni bilan);
  - ikkinchi javobsiz qo'ng'iroqdan keyin — “bog'lana olmadik” (11-skript).
  Bemor Telegram'da yozgan bo'lsa — Telegram'ga, aks holda SMS. Kechasi (20:00–09:00) yuborilmaydi,
  ertalab ketadi. Har biri bir marta (qayta ishga tushsa ham takrorlanmaydi).
- Shablonlar: Sozlamalar → **Xabar shablonlari** (UZ/RU).
- Bemor kartasida: “SMS yozish”; tarix tasmasida barcha xabarlar.

## Telegram

1. @BotFather → `/newbot` → token.
2. `.env`:
   ```
   TELEGRAM_BOT_TOKEN=123456:ABC...
   TELEGRAM_WEBHOOK_SECRET=<openssl rand -hex 16>
   PUBLIC_URL=https://crm.radeski.uz
   ```
3. ```bash
   docker compose -p radeski-crm -f docker-compose.prod.yml up -d --no-deps api worker beat
   docker compose -p radeski-crm -f docker-compose.prod.yml exec api python -m app.cli telegram-setup
   ```
   “Webhook o'rnatildi … (bot @…)” chiqishi kerak.

**Telegram Business** (klinikaning o'z akkaunti orqali, bot emas): Telegram Premium →
Settings → Telegram Business → Chatbots → shu botni ulang. Keyin mijozlar klinika akkauntiga
yozgan xabarlar ham CRM'ga tushadi, operator javobi klinika nomidan ketadi. Klinika xodimi
telefondan o'zi javob bersa, u ham tarixda ko'rinadi.

## SMS

**Eskiz** (notify.eskiz.uz) yoki **Playmobile**. Shartnoma va “from” (nickname) olingach:

```
SMS_PROVIDER=eskiz
ESKIZ_EMAIL=...
ESKIZ_PASSWORD=...
ESKIZ_FROM=4546        # tasdiqlangan jo'natuvchi nomi
```

yoki `SMS_PROVIDER=playmobile` + `PLAYMOBILE_LOGIN/PASSWORD/ORIGINATOR`.

**Muhim:** O'zbekistonda SMS matni provayderda **moderatsiyadan** o'tadi. Sozlamalardagi
shablonlar matnini provayderga yuboring, tasdiqlangandan keyin CRM'dagi matn **so'zma-so'z** bir
xil bo'lishi kerak (o'zgaruvchilar `{sana}`, `{vaqt}` va h.k. provayderda `%w` ko'rinishida
tasdiqlanadi). Eskiz yetkazish hisobotini `/api/integrations/sms/eskiz` ga yuboradi — xabar
holati “yetkazildi”ga o'zgaradi.

## Instagram Direct

Meta ilovasi kerak (Instagram API with Instagram Login), `instagram_business_manage_messages`
ruxsati Meta tekshiruvidan o'tadi (bir necha hafta).

1. developers.facebook.com → App → Instagram → API setup with Instagram login.
2. Webhook: `https://crm.radeski.uz/api/integrations/instagram/webhook`, verify token —
   `.env` dagi `INSTAGRAM_VERIFY_TOKEN`, obuna: `messages`.
3. `.env`:
   ```
   INSTAGRAM_ACCESS_TOKEN=...   # uzoq muddatli token
   INSTAGRAM_APP_SECRET=...     # webhook imzosi uchun
   INSTAGRAM_VERIFY_TOKEN=...
   INSTAGRAM_USER_ID=...        # klinika akkauntining IG user id
   ```

Instagram qoidasi: foydalanuvchi oxirgi marta yozganidan keyin **24 soat** ichida javob berish
mumkin — javobni kechiktirmang.

## Tekshirish

- “Chatlar” sahifasining yuqorisida ulangan kanallar yashil ko'rinadi.
- Xabar “navbatda” qolib ketsa — `worker` va `beat` ishlayotganini tekshiring (har daqiqada
  navbat yuboriladi, 3 marta urinadi).
