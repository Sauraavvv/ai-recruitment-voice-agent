"""Telephony providers (plan.md Module E). Exotel is the only one for the MVP."""

from app.config import Settings
from app.providers.telephony.base import TelephonyConfigError, TelephonyProvider


def create_telephony_provider(settings: Settings) -> TelephonyProvider:
    from app.providers.telephony.exotel_provider import ExotelProvider

    if not settings.exotel_configured:
        raise TelephonyConfigError("Telephony is not configured (EXOTEL_*, PUBLIC_BACKEND_URL)")
    return ExotelProvider(settings)


def webhook_token(settings: Settings) -> str:
    # Hex only: Exotel refuses a StatusCallback URL whose token has base64url characters
    # (HTTP 400 "Invalid 'StatusCallbackEvents' specified", real calls 2026-11-19).
    return settings.derived_secret("exotel-status-webhook", hex_only=True)


def stream_token(settings: Settings) -> str:
    return settings.derived_secret("exotel-voicebot-stream")


def status_callback_url(settings: Settings) -> str:
    base = (settings.public_backend_url or "").rstrip("/")
    # A short neutral path: Exotel refused the longer /api/v1/webhooks/exotel/status/... URL
    # with a misleading "Invalid 'StatusCallbackEvents'" (real calls 2026-11-19).
    return f"{base}/cb/{webhook_token(settings)}"


def stream_url(settings: Settings) -> str:
    """The URL to paste into the Exotel flow's Voicebot applet."""
    base = (settings.public_backend_url or "").rstrip("/")
    ws = base.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
    rate = settings.telephony_sample_rate
    suffix = f"?sample-rate={rate}" if rate != 8000 else ""
    return f"{ws}/api/v1/webhooks/exotel/stream/{stream_token(settings)}{suffix}"


__all__ = [
    "TelephonyProvider",
    "create_telephony_provider",
    "status_callback_url",
    "stream_token",
    "stream_url",
    "webhook_token",
]
