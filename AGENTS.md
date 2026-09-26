# Radeski CRM — Codex qoidalari

CRM + AI-assisted call center for Radeski Skin Clinic (Fergana & Kokand, Uzbekistan).
Read before any work: `docs/01_TZ.md` (requirements), `docs/02_ARXITEKTURA.md` (architecture), `docs/03_REJA.md` (phases & acceptance criteria).

## Communication
- Talk to the user in Uzbek (Latin). Docs in Uzbek. Code, identifiers, commits in English.
- UI strings only via i18n (`frontend/src/i18n/uz.json`, `ru.json`) — never hardcode UI text. Default language: uz (Latin).

## Stack
- Backend: Python 3.12, FastAPI, SQLAlchemy 2 (async), Alembic, Pydantic v2, Celery + Beat, PostgreSQL 16, Redis 7. Call recordings in the `radeski_crm_recordings` volume (stereo MP3 via ffmpeg).
- Frontend: React 19 + Vite + TypeScript, Tailwind, shadcn/ui, TanStack Query, i18next, react-big-calendar, JsSIP.
- Telephony: Asterisk 20 (PJSIP + WebRTC) in `telephony/` (compose profile `telephony`), Uztelecom SIP trunk. Call events reach the CRM from the dialplan over HTTP (`/api/telephony/events`, `X-PBX-Secret`), not ARI. Test calls without a trunk: `test-inbound` / `test-agent` contexts (docs/06_TELEFONIYA.md).
- AI: OpenAI API (official `openai` Python SDK, key in `.env` as `OPENAI_API_KEY`) for both STT (transcription) and LLM analysis with structured outputs (JSON Schema). No GPU on the server. Both behind adapter interfaces in `backend/app/integrations/{stt,llm}/`. Models are settings (`AI_STT_MODEL`, `AI_LLM_MODEL`); tests replace the adapters with fakes (`tests/test_ai.py`) and check request shapes with a fake HTTP transport (`tests/test_openai_adapters.py`). Bump `PROMPT_VERSION` in `app/modules/ai/prompts.py` whenever the analysis prompt changes.
- Deployment: same server as radeski.uz (our team's site, FastAPI). Separate compose project + separate DB; shared nginx (`crm.radeski.uz`). Site → CRM webhook for new appointment requests.
- Call center: 2 operators in shifts, only 1 online at a time → tasks go to a shared queue, not to a person.

## Rules
- Modular monolith: each module in `backend/app/modules/<name>/` with `models.py schemas.py service.py router.py tasks.py`. Modules talk through services/events, not each other's tables.
- Status changes only via service functions that emit domain events; task rules subscribe to events. All generators must be idempotent.
- Phones always stored as E.164 (`+998XXXXXXXXX`). Name search must be Cyrillic/Latin-insensitive (`fio_translit` + pg_trgm).
- Configurable values (durations, intervals, SLA minutes, retry counts) live in `settings`/DB, not constants.
- Every schema change = Alembic migration. Every business rule = a test.
- External services (STT, LLM, SMS, Telegram, Instagram, site API) only through `backend/app/integrations/` adapters.

## PII — strict
- Real patient files live in `data/` (git-ignored) or outside the repo. Never commit, paste into docs, log, or publish them.
- Tests use synthetic fixtures only.
- Before sending transcripts to an external LLM, mask phone numbers/document numbers.
