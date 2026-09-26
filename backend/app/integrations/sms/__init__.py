"""SMS providers (Uzbekistan). Only pre-moderated template texts are sent (TZ 4.10)."""

from typing import Protocol

from app.core.config import get_settings


class SendError(RuntimeError):
    """The provider refused or could not be reached; the message stays retryable."""


class SmsSender(Protocol):
    name: str

    async def send(self, phone: str, text: str, ref: str) -> str:
        """phone is E.164; ref is our message id; returns the provider's message id."""
        ...


def get_sms_sender() -> SmsSender | None:
    provider = get_settings().sms_provider
    if provider == "eskiz":
        from app.integrations.sms.eskiz import EskizSms

        return EskizSms()
    if provider == "playmobile":
        from app.integrations.sms.playmobile import PlaymobileSms

        return PlaymobileSms()
    return None
