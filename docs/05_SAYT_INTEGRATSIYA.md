# radeski.uz → CRM: saytdagi arizalar

Saytdagi "Qabulga yozilish" formasi to'ldirilganda ariza CRM'ga **murojaat** bo'lib tushadi,
operator navbatida "Yangi murojaat" vazifasi paydo bo'ladi va 15 ish daqiqalik SLA taymeri
boshlanadi.

Ikki yo'l bor, ikkalasi ham yoqilishi tavsiya etiladi:

| Yo'l | Tezligi | Kim sozlaydi |
|---|---|---|
| **Webhook** — sayt arizani darhol CRM'ga yuboradi | bir necha soniya | sayt jamoasi (quyidagi kod) |
| **Zaxira tekshiruv** — CRM har 5 daqiqada sayt admin API'sidan yangi arizalarni oladi | 5 daqiqagacha | `.env` da `SITE_ADMIN_USERNAME` / `SITE_ADMIN_PASSWORD` |

Bir ariza ikki yo'l bilan kelsa ham CRM'da **bitta** murojaat bo'ladi (saytdagi `id` bo'yicha).

## Webhook

- URL: `https://crm.devflix.uz/api/integrations/site/appointments` (serverning ichida:
  `http://127.0.0.1:9250/api/integrations/site/appointments`)
- Metod: `POST`, `Content-Type: application/json`
- Imzo: `X-Signature: sha256=<hex>` — so'rov tanasining **aynan o'sha baytlari** ustidan
  HMAC-SHA256, kalit `SITE_WEBHOOK_SECRET` (CRM `.env` idagi bilan bir xil bo'lishi shart)
- Javob: `202 {"lead_id": "...", "status": "created" | "duplicate"}`; imzo noto'g'ri bo'lsa `401`

Tana:

```json
{
  "id": "1234",
  "phone_number": "+998 90 000 22 44",
  "client_name": "Ism Familiya",
  "comment": "ixtiyoriy",
  "preferred_date": "2026-10-05",
  "service_name_uz": "ixtiyoriy"
}
```

`id` va `phone_number` majburiy, qolganlari ixtiyoriy. Telefon istalgan ko'rinishda bo'lishi
mumkin — CRM uni o'zi `+998XXXXXXXXX` ga keltiradi.

### Saytga qo'shiladigan kod (FastAPI)

Ariza bazaga saqlangandan keyin chaqiriladi. CRM ishlamay qolsa ham sayt formasi ishlashda
davom etadi — zaxira tekshiruv arizani keyinroq baribir olib keladi.

```python
import hashlib
import hmac
import json
import logging
import os

import httpx
from fastapi import BackgroundTasks

CRM_WEBHOOK_URL = os.environ.get("CRM_WEBHOOK_URL", "")
CRM_WEBHOOK_SECRET = os.environ.get("CRM_WEBHOOK_SECRET", "")
log = logging.getLogger(__name__)


def send_to_crm(appointment) -> None:
    if not CRM_WEBHOOK_URL or not CRM_WEBHOOK_SECRET:
        return
    body = json.dumps(
        {
            "id": str(appointment.id),
            "phone_number": appointment.phone_number,
            "client_name": appointment.client_name,
            "comment": appointment.comment,
            "preferred_date": appointment.preferred_date.isoformat()
            if appointment.preferred_date
            else None,
            "service_name_uz": appointment.service.name_uz if appointment.service else None,
        },
        ensure_ascii=False,
    ).encode()
    signature = hmac.new(CRM_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    try:
        httpx.post(
            CRM_WEBHOOK_URL,
            content=body,
            headers={"Content-Type": "application/json", "X-Signature": f"sha256={signature}"},
            timeout=5,
        )
    except httpx.HTTPError:
        log.warning("CRM webhook failed; the CRM poller will pick the request up")


# arizani saqlaydigan endpoint ichida:
#     background_tasks.add_task(send_to_crm, appointment)
```

Maydon nomlari (`appointment.phone_number` va h.k.) saytdagi modelga moslab o'zgartiriladi.

### Kalitni yaratish va tekshirish

```bash
openssl rand -hex 32
```

Chiqqan qiymat CRM `.env` ida `SITE_WEBHOOK_SECRET`, saytda `CRM_WEBHOOK_SECRET` bo'lib yoziladi.
Keyin CRM'ni `--no-deps` bilan qayta ishga tushirish kifoya:

```bash
docker compose -p radeski-crm -f docker-compose.prod.yml up -d --no-deps api
```

Qo'lda sinash (serverda):

```bash
BODY='{"id":"test-1","phone_number":"900002244","client_name":"Sinov"}'
SIG=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$SITE_WEBHOOK_SECRET" | cut -d' ' -f2)
curl -s -X POST http://127.0.0.1:9250/api/integrations/site/appointments \
  -H 'Content-Type: application/json' -H "X-Signature: sha256=$SIG" -d "$BODY"
```

Sinov murojaatini keyin CRM'da "Murojaatlar" sahifasidan "Yo'qotildi" deb yopib qo'ying.
