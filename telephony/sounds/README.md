# IVR ovozli xabarlari

Fayllar: **WAV, 8000 Hz, mono, 16-bit**. Har birida matn avval o'zbekcha, keyin ruscha.
Hozirgi fayllar OpenAI TTS bilan yaratilgan va qaytadan matnga o'girib tekshirilgan (tushunarli).
Klinika xohlasa, ularni diktor ovozi bilan almashtirish mumkin — nomlar o'zgarmasa bo'ldi.

| Fayl | Qachon | Matn (o'zbekcha qismi) |
|---|---|---|
| `welcome.wav` | ish vaqtida, navbatdan oldin | "Assalomu alaykum, Radeski Skin Clinic. Suhbat sifat nazorati uchun yozib olinadi." |
| `after-hours.wav` | ish vaqtidan tashqari | "... Klinika dushanbadan shanbagacha, soat sakkizdan o'n sakkizgacha ishlaydi." |
| `press-1-callback.wav` | navbatda har 30 soniyada va navbatdan keyin | "Sizga qayta qo'ng'iroq qilishimizni xohlasangiz, bir raqamini bosing." |
| `callback-ok.wav` | 1 bosilgandan keyin | "Rahmat, operatorimiz sizga tez orada qo'ng'iroq qiladi." |
| `goodbye.wav` | xayrlashuv | "Katta rahmat. Salomat bo'ling, xayr." |

To'liq matnlar (ruscha qismi bilan): `backend/app/modules/telephony/prompts.py`. Ish vaqti
matni `app/core/clinic_time.py` dagi soatlardan olinadi.

Fayl bo'lmasa Asterisk shu qadamni jimgina o'tkazib yuboradi (qo'ng'iroq to'xtamaydi).

## Qayta yaratish (matn yoki ish vaqti o'zgarsa)

```bash
docker compose -p radeski-crm -f docker-compose.prod.yml run --rm --no-deps \
  -v "$(pwd)/telephony/sounds:/out" api python -m app.cli generate-prompts --out /out
```

Faqat ayrimlarini: `--only welcome goodbye`; boshqa ovoz: `--voice coral`. Narxi bir necha sent
(kunlik AI chegarasiga kiradi). Tinglab ko'ring, so'ng `pbx` ni qayta yig'ing:

```bash
docker compose -p radeski-crm -f docker-compose.prod.yml --profile telephony up -d --build --no-deps pbx
```

## Diktor yozuvidan o'girish

```bash
ffmpeg -i welcome.mp3 -ar 8000 -ac 1 -sample_fmt s16 welcome.wav
```

Serverda fayllarni `radeski_crm_pbx_sounds` volume'iga (konteyner ichida
`/opt/radeski/sounds-custom`) qo'ysangiz, ular shu papkadagilardan ustun turadi — obrazni qayta
yig'ish shart emas, faqat `pbx` ni qayta ishga tushiring.
