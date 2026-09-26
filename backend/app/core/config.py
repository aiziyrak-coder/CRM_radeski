from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Radeski CRM"
    environment: str = "local"  # local | test | production
    tz: str = "Asia/Tashkent"

    database_url: str = "postgresql+asyncpg://crm:crm@db:5432/crm"
    redis_url: str = "redis://redis:6379/0"

    # Auth
    jwt_secret: str = "dev-only-change-me"
    access_token_minutes: int = 15
    session_idle_minutes: int = 30  # TZ 5: session closes after 30 min of inactivity
    session_absolute_hours: int = 12  # one working shift
    login_max_attempts: int = 5
    login_lock_minutes: int = 15
    # failures for one username from any IP (distributed guessing); higher than the per-IP limit
    login_max_attempts_per_user: int = 20
    totp_roles: str = "admin,owner"  # roles that must use an authenticator app
    totp_replay_guard: bool = True
    # wrong authenticator codes per user (any IP, any challenge) before the second step locks
    totp_max_attempts: int = 5
    totp_lock_minutes: int = 15
    totp_challenge_max_attempts: int = 3  # codes one password challenge may be used for
    # catalog sync refuses to deactivate anything when a site list shrinks by more than this
    catalog_sync_max_shrink: float = 0.5

    # External services
    openai_api_key: str = ""
    # model names are settings so the STT benchmark (plan 4.1) can switch them without code
    # cheapest defaults (docs/07_AI.md "Narx"): only speech is sent to STT, analysis runs at
    # the half-price flex tier, and a daily budget stops new requests once it's used up
    ai_stt_model: str = "gpt-4o-mini-transcribe"
    ai_llm_model: str = "gpt-5.6-luna"
    ai_reasoning_effort: str = "low"  # empty for models without reasoning
    ai_service_tier: str = "flex"  # half price, slower; empty = standard
    ai_max_output_tokens: int = 3000
    ai_min_talk_seconds: int = 20  # shorter calls aren't worth analysing
    ai_daily_budget_usd: float = 1.0  # 0 = no limit
    site_api_url: str = "https://api.radeski.uz"
    # HMAC secret shared with radeski.uz for the form webhook (empty = webhook disabled)
    site_webhook_secret: str = ""
    # optional fallback polling of the site's admin API (empty = disabled)
    site_admin_username: str = ""
    site_admin_password: str = ""

    # Telephony (Asterisk): the dialplan posts call events with PBX_API_SECRET; softphone
    # passwords are HMAC(PBX_SIP_SECRET, "ext:<n>") — empty secrets switch telephony off
    pbx_api_secret: str = ""
    pbx_sip_secret: str = ""
    pbx_extensions: str = "101 102 103 104"
    sip_host: str = ""  # read here only to show whether the trunk is configured
    recordings_dir: str = "/recordings"
    # a call still "ringing" this long lost its hangup report: closed as missed by a beat job
    # (answered calls stay "ringing" until hangup, so keep this above the longest conversation)
    pbx_ringing_timeout_minutes: int = 60

    # Messaging (phase 5). Public address of the CRM, used for webhooks and SMS status callbacks
    public_url: str = "https://crm.radeski.uz"
    # automatic messages go out only between these clinic hours (a night SMS is a complaint)
    messages_from_hour: int = 9
    messages_to_hour: int = 20
    sms_provider: str = ""  # "eskiz" | "playmobile" | "" (off)
    eskiz_email: str = ""
    eskiz_password: str = ""
    eskiz_from: str = "4546"
    # part of the delivery-report URL given to Eskiz (empty = no delivery reports)
    eskiz_callback_secret: str = ""
    playmobile_url: str = "https://send.smsxabar.uz/broker-api/send"
    playmobile_login: str = ""
    playmobile_password: str = ""
    playmobile_originator: str = "3700"
    telegram_bot_token: str = ""
    telegram_webhook_secret: str = ""
    instagram_access_token: str = ""
    instagram_app_secret: str = ""
    instagram_verify_token: str = ""
    instagram_user_id: str = ""
    instagram_graph_version: str = "v23.0"

    # Task queue rules (TZ 4.4, 4.5)
    task_max_no_answer: int = 3  # unanswered attempts before a task is closed as "no answer"
    task_retry_after_minutes: int = 120  # first retry after an unanswered call
    task_retry_next_day_hour: int = 10  # later retries: the next working day at this hour
    task_thinking_workdays: int = 2  # "o'ylab ko'raman" -> call back in N working days
    lead_sla_minutes: int = 15  # first answer to an inquiry within N working minutes
    lost_lead_after_hours: int = 24  # an inquiry not booked within N hours becomes "lost"
    repeat_visit_lead_days: int = 3  # call N days before the doctor's recommended date
    reactivation_after_days: int = 180  # TZ 4.5: default 6 months since the last visit
    reactivation_daily_limit: int = 20
    # a message a worker took but never finished (crash mid-send) is marked failed after this;
    # not resent automatically: the provider may already have delivered it
    messages_sending_timeout_minutes: int = 10

    # Celery workers run each job in a fresh event loop: pooled asyncpg connections can't be reused
    db_null_pool: bool = False

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    weak = len(settings.jwt_secret) < 32 or settings.jwt_secret == "dev-only-change-me"
    if settings.is_production and weak:
        raise RuntimeError("JWT_SECRET must be set in production (at least 32 characters)")
    return settings
