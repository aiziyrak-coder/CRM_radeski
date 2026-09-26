# IVR ovozli xabarlari

Fayllar: **WAV, 8000 Hz, mono, 16-bit**. Nomi va matni (UZ, keyin RU):

| Fayl | Qachon | Matn (taklif) |
|---|---|---|
| `welcome.wav` | ish vaqtida, navbatdan oldin | "Assalomu alaykum, Radeski Skin Clinic. Suhbat sifat nazorati uchun yozib olinadi. Iltimos, kuting, operator hozir javob beradi." |
| `after-hours.wav` | ish vaqtidan tashqari | "Klinika dushanbadan shanbagacha soat 8 dan 18 gacha ishlaydi." |
| `press-1-callback.wav` | navbatda har 30 soniyada va navbatdan keyin | "Qayta qo'ng'iroq qilishimizni istasangiz, 1 ni bosing." |
| `callback-ok.wav` | 1 bosilgandan keyin | "Rahmat, operatorimiz sizga tez orada qo'ng'iroq qiladi." |
| `goodbye.wav` | xayrlashuv | "Qo'ng'iroq uchun rahmat. Salomat bo'ling." |

Fayl bo'lmasa Asterisk shu qadamni jimgina o'tkazib yuboradi (qo'ng'iroq to'xtamaydi).

## Qayerga qo'yiladi

Serverda `radeski_crm_pbx_sounds` volume'iga (konteyner ichida `/opt/radeski/sounds-custom`)
yoki shu papkaga (keyin `pbx` obrazini qayta yig'ish kerak). So'ng:

```bash
docker compose -p radeski-crm -f docker-compose.prod.yml --profile telephony up -d --no-deps pbx
```

## Tayyor audiodan o'girish

```bash
ffmpeg -i welcome.mp3 -ar 8000 -ac 1 -sample_fmt s16 welcome.wav
```

Ovozni sun'iy intellekt bilan yaratish ham mumkin: `python -m app.cli generate-prompts`
(OpenAI TTS, `OPENAI_API_KEY` kerak) — yozilgan fayllar tekshirib, yoqsa shu yerga qo'yiladi.
