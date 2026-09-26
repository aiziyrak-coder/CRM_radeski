# SERVERGA JOYLASHTIRISH

Server umumiy: 23 ta loyiha, 87 ta konteyner, 40 ta domen. **Asosiy qoida: boshqa loyihalarning birortasi ham to'xtab qolmasligi kerak.**
Bu hujjat serverning umumiy yo'riqnomasini Radeski CRM uchun aniq qiymatlar bilan to'ldiradi.

## Radeski CRM parametrlari

| Parametr | Qiymat |
|---|---|
| Katalog | `/home/radeski-crm` |
| Compose loyiha nomi | `radeski-crm` (`docker-compose.prod.yml` ichida `name:` bilan qotirilgan) |
| HTTP port | `127.0.0.1:9250` (bo'sh 9200–9400 oralig'idan). Faqat `web` konteyneri port ochadi |
| Domen | `crm.radeski.uz` → A yozuvi `87.192.230.208` |
| Volume'lar | `radeski_crm_pgdata`, `radeski_crm_redisdata` |
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

1. DNS: `crm.radeski.uz` uchun A yozuvi → `87.192.230.208`.
2. **Yangi** nginx faylini yarating. Mavjud fayllarga tegmang:

```bash
sudo nano /etc/nginx/sites-available/crm.radeski.uz
```

```nginx
server {
    listen 80;
    server_name crm.radeski.uz;
    client_max_body_size 50m;

    location / {
        proxy_pass http://127.0.0.1:9250;
        proxy_http_version 1.1;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        # WebSocket: kiruvchi qo'ng'iroq popup'i, jonli vazifalar
        proxy_set_header Upgrade    $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 300s;
    }
}
```

3. Faylni yoqish va sintaksisni tekshirish:

```bash
sudo ln -s /etc/nginx/sites-available/crm.radeski.uz /etc/nginx/sites-enabled/
```

```bash
sudo nginx -t
```

4. **Faqat** `nginx -t` muvaffaqiyatli bo'lsa, `reload` qiling. `restart` emas:

```bash
sudo systemctl reload nginx
```

```bash
sudo certbot --nginx -d crm.radeski.uz
```

## 4. Zaxira nusxa (cron)

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
cd /home/radeski-crm && docker compose -f docker-compose.prod.yml up -d --build --no-deps api worker beat
```

```bash
cd /home/radeski-crm && docker compose -f docker-compose.prod.yml up -d --build --no-deps web
```

`web` ichidagi nginx `api` manzilini Docker DNS orqali qayta aniqlaydi. Shuning uchun faqat `api` qayta yaratilganda ham 502 chiqmaydi (lokal sinovda tekshirilgan).

## 6. Oxirgi tekshiruv

```bash
docker ps -q | wc -l
```
Son 1-qadamdagidan 6 taga ko'p bo'lishi kerak (web, api, worker, beat, db, redis).

```bash
docker ps -a --filter 'status=exited' --format '{{.Names}}\t{{.Status}}'
```
Bu yerda yangi to'xtagan konteyner chiqmasligi kerak.

## 7. Telefoniya (3-bosqich) uchun oldindan bilish kerak bo'lgan narsalar

- Server router ortida turibdi: ichki IP `192.168.0.101`, tashqi IP `87.192.230.208`. Tashqaridan 22-port yopiq, demak router faqat ayrim portlarni o'tkazadi.
- Uztelecom SIP-trunk va brauzer softfoni uchun routerda **UDP portlarni yo'naltirish** kerak bo'ladi: SIP (5060 yoki boshqa bo'sh port) va RTP oralig'i (masalan, UDP 30000–30200). Asterisk'da tashqi IP (`external_media_address`) ko'rsatiladi.
- Operator klinikada, server esa ofisda bo'lgani uchun operator ovozi internet orqali o'tadi. WebRTC uchun STUN (va kerak bo'lsa TURN) sozlanadi.
- Bu portlar TCP emas, UDP. Ular serverdagi mavjud TCP xizmatlarga xalaqit bermaydi, lekin router sozlamasini oldindan rejalashtirish kerak.
