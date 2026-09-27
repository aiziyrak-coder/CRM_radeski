# Telefoniya (3-bosqich): ulash va tekshirish

## Qanday ishlaydi

```
Bemor ──► Uztelecom ──SIP/RTP──► ofis routeri ──► server: pbx (Asterisk 20)
                                                       │ IVR → "operators" navbati → 101…104
Operator brauzeri (JsSIP) ──wss://crm.radeski.uz/ws──► │
                                                       │ har qo'ng'iroq tugaganda:
                                                       └─HTTP─► CRM /api/telephony/events
                                                                 ├─ calls jadvali (jurnal)
                                                                 ├─ javobsiz → vazifa / murojaat
                                                                 └─ yozuv → worker → stereo MP3
```

- **Kiruvchi**: salomlashish (“suhbat yozib olinadi”) → navbat. Bir operator band bo'lsa, keyingi
  qo'ng'iroq musiqa bilan kutadi, har 30 soniyada “1 ni bosing — qayta qo'ng'iroq qilamiz” eshitiladi.
  90 soniyada javob bo'lmasa yoki hech kim onlayn bo'lmasa — yana 1 ni bosish taklif qilinadi.
- **Ish vaqtidan tashqari** (Du–Sha 08:00–18:00 dan tashqari): xabar + “1 ni bosing”.
- **Javobsiz qo'ng'iroq** avtomatik vazifa bo'ladi: bemor bazada bo'lsa — “Javobsiz qo'ng'iroq”
  (bir kunda bitta), bo'lmasa — yangi murojaat (15 daqiqalik SLA bilan). Bemor keyin o'zi
  qo'ng'iroq qilib operator bilan gaplashsa, vazifa o'zi yopiladi.
- **Chiquvchi**: operator vazifa yoki bemor kartasidagi “Qo'ng'iroq” tugmasini bosadi, qo'ng'iroq
  shu vazifa va bemorga bog'lanadi. Faqat O'zbekiston raqamlariga (9 xonali) ruxsat bor.
- **Yozuv**: faqat operator bilan gaplashilgan qism, chap kanal — operator, o'ng — bemor
  (4-bosqichda nutqni matnga aylantirish uchun). Tinglash: rahbar/admin — hammasi,
  operator — faqat o'zining qo'ng'iroqlari.
- **Popup**: qo'ng'iroq kelganda brauzerda oyna chiqadi: raqam, bemor (kartaga havola),
  ochiq vazifalar, keyingi qabul; notanish raqam uchun “Murojaat yaratish”.

## 1. `.env` ga qo'shish (serverda)

```bash
cd /home/radeski-crm
echo "PBX_API_SECRET=$(openssl rand -hex 32)" >> .env
echo "PBX_SIP_SECRET=$(openssl rand -hex 32)" >> .env
```

Qolganlari (`.env.example` dagi “Telephony” bo'limi):

| O'zgaruvchi | Qiymat |
|---|---|
| `PBX_PUBLIC_IP` | ofisning tashqi IP manzili (hozir `87.192.230.208`) |
| `SIP_HOST`, `SIP_PORT` | Uztelecom beradi (registrar/proxy manzili) |
| `SIP_USERNAME`, `SIP_PASSWORD` | Uztelecom beradi. Parolda `;` bo'lmasin |
| `SIP_NUMBER` | klinika raqami (chiquvchi qo'ng'iroqda ko'rinadi) |
| `SIP_DIAL_PREFIX` | Uztelecom qaysi formatni kutadi: `998` (standart), `8` yoki bo'sh |
| `PBX_OPEN_HOURS`, `PBX_OPEN_DAYS` | ish vaqti (standart `08:00-17:59`, `mon-sat`) |

`SIP_HOST` bo'sh bo'lsa ham PBX ishlaydi: softfonlar ulanadi, exo-test (600) va operatorlar
o'rtasidagi qo'ng'iroqlar ishlaydi — trunkni kutmasdan sinab ko'rish mumkin.

## 2. Router (ofis) — port yo'naltirish

Serverga (`192.168.0.101`) **UDP** portlar:

| Port | Nima uchun |
|---|---|
| `5060/udp` | SIP (Uztelecom) |
| `17000–17039/udp` | ovoz (RTP): Uztelecom va operatorlar brauzeri |

Iloji bo'lsa `5060/udp` ni faqat Uztelecom IP manzillari uchun oching (ular aytib beradi).
RTP portlarini hamma uchun ochish kerak — operatorlar klinikadan (boshqa IP) ulanadi.

Serverdagi boshqa loyihalar bu portlarni ishlatmayotganini tekshiring:

```bash
sudo ss -lunp | grep -E ':(5060|170[0-3][0-9])\b' || echo "bo'sh"
```

## 3. Ishga tushirish

```bash
docker compose -p radeski-crm -f docker-compose.prod.yml --profile telephony up -d --build pbx
docker compose -p radeski-crm -f docker-compose.prod.yml up -d --build --no-deps api worker worker-ai beat web
docker compose -p radeski-crm -f docker-compose.prod.yml logs --tail 30 pbx
```

Tekshirish:

```bash
# trunk ro'yxatdan o'tganmi ("Registered" bo'lishi kerak)
docker compose -p radeski-crm -f docker-compose.prod.yml exec pbx asterisk -rx "pjsip show registrations"
# qaysi operatorlar onlayn
docker compose -p radeski-crm -f docker-compose.prod.yml exec pbx asterisk -rx "queue show operators"
```

## 4. Operatorlarga ichki raqam berish

CRM → **Foydalanuvchilar** → operator qatorida **Ichki raqam** (101–104). Operator qayta
kirganda yuqori o'ng burchakda `● 101 Onlayn` chiqadi. Birinchi marta brauzer mikrofonga ruxsat
so'raydi — “Ruxsat berish”. Tekshirish: shu belgini bosib **“Mikrofonni sinash (exo-test 600)”** —
o'z ovozingizni eshitishingiz kerak.

Operatorga faqat **quloqchin (mikrofonli)** kerak; brauzer — Chrome yoki Edge.

## 5. Ovozli xabarlar

Tayyor: o'zbek + rus tilida 5 ta fayl (OpenAI TTS bilan yaratilgan, qaytadan matnga o'girib
tekshirilgan). Qaysi fayl qachon eshitilishi, matni, qayta yaratish yoki diktor yozuviga
almashtirish — `telephony/sounds/README.md`.

## 6. Muammolar

| Belgi | Sabab / yechim |
|---|---|
| `● Aloqa yo'q` (qizil) | `pbx` ishlamayapti yoki host nginx `/ws` ni o'tkazmayapti (`Upgrade` sarlavhalari 04_DEPLOY.md dagi kabi bo'lishi kerak) |
| Qo'ng'iroq bor, ovoz yo'q | RTP portlari (17000–17039/udp) routerda yo'naltirilmagan yoki `PBX_PUBLIC_IP` noto'g'ri |
| Kiruvchi qo'ng'iroq kelmaydi | `pjsip show registrations` — `Rejected` bo'lsa login/parol, `Unregistered` bo'lsa 5060/udp |
| Chiquvchi “operator tarmog'i xatosi” | `SIP_DIAL_PREFIX` ni o'zgartirib ko'ring (`998` ↔ `8` ↔ bo'sh) |
| Jurnalda “Yozuv tayyorlanmoqda…” ko'p turadi | `worker` ishlamayapti; har 30 daqiqada qayta urinish bor |

Trunksiz sinov (CLI orqali kiruvchi qo'ng'iroq simulyatsiyasi):

```bash
docker compose -p radeski-crm -f docker-compose.prod.yml exec pbx \
  asterisk -rx "channel originate Local/900002244@test-inbound application Wait 20"
```
