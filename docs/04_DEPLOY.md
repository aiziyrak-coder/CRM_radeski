# SERVERGA JOYLASHTIRISH

Server umumiy: 23 ta loyiha, 87 ta konteyner, 40 ta domen. **Asosiy qoida: boshqa loyihalarning birortasi ham to'xtab qolmasligi kerak.**
Bu hujjat serverning umumiy yo'riqnomasini Radeski CRM uchun aniq qiymatlar bilan to'ldiradi.

## Radeski CRM parametrlari

| Parametr | Qiymat |
|---|---|
| Katalog | `/home/radeski-crm` |
| Compose loyiha nomi | `radeski-crm` (`docker-compose.prod.yml` ichida `name:` bilan qotirilgan) |
| HTTP port | `127.0.0.1:9250` (bo'sh 9200–9400 oralig'idan). Faqat `web` konteyneri port ochadi |
| Domen | `crm.devflix.uz` → A yozuvi `87.192.230.208` |
| Volume'lar | `radeski_crm_pgdata`, `radeski_crm_redisdata`, `radeski_crm_recordings` (qo'ng'iroq yozuvlari), `radeski_crm_pbx_sounds` (IVR ovozlari) |
| Zaxira | Har kuni 04:30 da (02:15, 03:00 va 03:15 boshqa loyihalarniki), 30 kun saqlanadi |
| Server | 32 yadro, 94 GB RAM (~20 GB bo'sh), 573 GB bo'sh disk, GPU yo'q |

## 1. Birinchi joylashtirishdan oldingi tekshiruv

```bash
ssh admin_root@192.168.0.101
```

```bash
docker ps --format '{{.Label "com.docker.compose.project"}}' | sort -u | grep -x radeski-crm
```
Bu buyruq hech narsa chiqarmasligi kerak, ya'ni `radeski-crm` nomi hali band emas.

```bash
ss -tln | grep ':9250 '
```
Bu ham hech narsa chiqarmasligi kerak, ya'ni port bo'sh.

```bash
docker ps -q | wc -l
```
Chiqqan sonni yozib qo'ying. Oxirida solishtiramiz.

## 2. Kodni olish va ishga tushirish

```bash
git clone https://github.com/aiziyrak-coder/CRM_radeski.git /home/radeski-crm
```

```bash
cd /home/radeski-crm && cp .env.example .env && sed -i "s/^DB_PASSWORD=.*/DB_PASSWORD=$(openssl rand -hex 24)/; s/^JWT_SECRET=.*/JWT_SECRET=$(openssl rand -hex 32)/" .env
```

```bash
cd /home/radeski-crm && docker compose -f docker-compose.prod.yml up -d --build
```

```bash
curl -s http://127.0.0.1:9250/api/health/ready
```
Kutilgan javob: `{"db":"ok","redis":"ok"}`.

Birinchi administratorni yarating. Parol ekranda so'raladi, buyruq tarixiga yozilmaydi:

```bash
cd /home/radeski-crm && docker compose -f docker-compose.prod.yml exec api python -m app.cli create-user --username admin --full-name "Tizim administratori" --role admin
```

Qolgan foydalanuvchilar (operatorlar, registratorlar, shifokorlar) CRM ichidagi **Foydalanuvchilar** sahifasidan qo'shiladi.

## 2a. Eski Excel bazasini import qilish (bir marta)

Fayllar serverga **git orqali emas**, to'g'ridan-to'g'ri nusxalanadi, chunki ularda bemorlarning shaxsiy ma'lumotlari bor. Import ishlashi uchun papkada quyidagilar bo'lishi kerak:
- `Список_всех_пациентов_по_клинике_за_весь_период.xlsx`;
- 7 ta tuman fayli;
- `ПСОРИАЗ, АТОПИК ДЕРМА, ВИТИЛИГО.xls`;
- `nomer.xlsx`.

```bash
mkdir -p /home/radeski-crm/data/legacy && chmod 700 /home/radeski-crm/data
```

Fayllarni o'z kompyuteringizdan yuboring (masalan, `scp`). Keyin avval sinov rejimida ishga tushiring, bu bosqichda bazaga hech narsa yozilmaydi:

```bash
cd /home/radeski-crm && docker compose -f docker-compose.prod.yml run --rm -v /home/radeski-crm/data/legacy:/import api python -m app.cli import-legacy --dir /import --dry-run
```

Raqamlar to'g'ri bo'lsa, haqiqiy import qiling. Uni qayta ishga tushirish xavfsiz, allaqachon kiritilganlar o'tkazib yuboriladi:

```bash
cd /home/radeski-crm && docker compose -f docker-compose.prod.yml run --rm -v /home/radeski-crm/data/legacy:/import api python -m app.cli import-legacy --dir /import
```

Muammoli qatorlar (xato telefon yoki sana) `data/legacy/import-problems.csv` fayliga yoziladi. Bu bemorlar tizimga baribir kiritiladi va kartasida "Ma'lumotni tekshirish kerak" belgisi turadi.

## 3. Domen va SSL (sudo kerak, bu qadamni server egasi bajaradi)

DNS: `crm.devflix.uz` uchun A yozuvi → `87.192.230.208` (2026-09-27 da ulangan).

Hammasi bitta skript bilan, u faqat shu domen uchun **yangi** fayl qo'shadi, boshqa saytlarga tegmaydi,
har qadamdan oldin `nginx -t` qiladi va nginx'ni faqat `reload` qiladi (xato bo'lsa o'z o'zgarishini
qaytaradi):

```bash
cd /home/radeski-crm && sudo bash scripts/install-nginx.sh
```

Skript: HTTP sayt → `certbot certonly --webroot` (so'ralsa hisobni tanlang) → HTTPS + HTTP'dan
yo'naltirish + HSTS. Sertifikat certbot tomonidan avtomatik yangilanadi.

Bu serverga xos ikki narsa (skriptda hisobga olingan):
- ayrim saytlar `listen 192.168.0.101:80/443` bilan aniq IP'da tinglaydi — nginx bunday IP'ga kelgan
  so'rovni faqat shu IP'ni ko'rsatgan bloklar orasidan tanlaydi, shuning uchun CRM bloki ham
  `192.168.0.101` ni aniq ko'rsatadi (aks holda Let's Encrypt tekshiruvi boshqa saytga tushib 404 beradi);
- ofis ichidan (LAN) tashqi IP orqali ochilmasligi mumkin (router "hairpin" qilmaydi) — ichkarida
  sinash uchun: `curl --resolve crm.devflix.uz:443:192.168.0.101 https://crm.devflix.uz/api/health/ready`.

`nginx -t` dagi `protocol options redefined` ogohlantirishlari boshqa saytlarniki, CRM'ga aloqasi yo'q.

### Admin kirishi (2FA)

Admin va rahbar (owner) har kirishda telefon ilovasidagi 6 xonali kodni kiritadi. Birinchi kirishda
ekranda QR kod chiqadi — Google Authenticator / Aegis / Microsoft Authenticator bilan skanerlang.
Telefon yo'qolsa: boshqa admin Foydalanuvchilar sahifasida "2FA'ni qayta ulash"ni bosadi, yagona
admin bo'lsa — serverda:

```bash
docker compose -p radeski-crm -f docker-compose.prod.yml exec api python -m app.cli reset-totp --username admin
```

## 4. Zaxira nusxa (cron)

Telefoniyani ulash — alohida: `docs/06_TELEFONIYA.md`.

Crontab faqat qo'shish usulida o'zgartiriladi, hech qachon almashtirilmaydi:

```bash
crontab -l > ~/crontab-$(date +%F).bak
```

```bash
{ crontab -l; echo "30 4 * * * /home/radeski-crm/scripts/backup.sh >> /home/radeski-crm/cron.log 2>&1"; } | crontab -
```

```bash
crontab -l
```

## 5. Kod yangilanganda

Faqat o'zgargan xizmatga teging va `--no-deps` flagini ishlating, shunda baza qayta yaratilmaydi:

```bash
cd /home/radeski-crm && git pull
```

```bash
cd /home/radeski-crm && docker compose -f docker-compose.prod.yml up -d --build --no-deps api worker worker-ai beat
```

```bash
cd /home/radeski-crm && docker compose -f docker-compose.prod.yml up -d --build --no-deps web
```

Telefoniya ulangan bo'lsa (`--profile telephony`), Asterisk konfiguratsiyasi o'zgarganda:

```bash
cd /home/radeski-crm && docker compose -f docker-compose.prod.yml --profile telephony up -d --build --no-deps pbx
```

`web` ichidagi nginx `api` manzilini Docker DNS orqali qayta aniqlaydi. Shuning uchun faqat `api` qayta yaratilganda ham 502 chiqmaydi (lokal sinovda tekshirilgan).

## 6. Oxirgi tekshiruv

```bash
docker ps -q | wc -l
```
Son 1-qadamdagidan 7 taga ko'p bo'lishi kerak (web, api, worker, worker-ai, beat, db, redis);
telefoniya yoqilgan bo'lsa 8 ta (+ pbx).

```bash
docker ps -a --filter 'status=exited' --format '{{.Names}}\t{{.Status}}'
```
Bu yerda yangi to'xtagan konteyner chiqmasligi kerak.

## 7. Qo'shimcha modullarni ulash

Har biri alohida, kerakli ma'lumot kelganda yoqiladi (bo'sh qolsa CRM ishlayveradi):

| Modul | Nima kerak | Qo'llanma |
|---|---|---|
| Telefoniya | Uztelecom SIP login/parol, routerda UDP 5060 va 17000–17039 | `docs/06_TELEFONIYA.md` |
| AI tahlil | `OPENAI_API_KEY` | `docs/07_AI.md` |
| Telegram / SMS / Instagram | bot tokeni, SMS shartnomasi, Meta ilovasi | `docs/08_KANALLAR.md` |
| Sayt arizalari | sayt jamoasi webhook kodini qo'shadi | `docs/05_SAYT_INTEGRATSIYA.md` |

Bosh sahifadagi "Tizim holati" (admin, rahbar, koll-markaz rahbari) qaysi modul ulanganini va
e'tibor talab qiladigan xatolarni (yuborilmagan xabarlar, tahlil qilinmagan yozuvlar) ko'rsatadi.
