"""Print the URLs to configure in Exotel (they contain secrets: don't share them).

    python -m app.scripts.exotel_urls

- Voicebot applet URL: paste into the flow's Voicebot applet. The flow is Voicebot → Hangup.
- Status callback URL: sent with every call automatically (shown for reference).
"""

from app.config import get_settings
from app.providers.telephony import status_callback_url, stream_url
from app.providers.telephony.exotel_provider import flow_url


def main() -> None:
    settings = get_settings()
    if not settings.public_backend_url:
        raise SystemExit("PUBLIC_BACKEND_URL is not set (the tunnel's https:// URL)")
    print(f"Voicebot URL     : {stream_url(settings)}")
    print(f"Status callback  : {status_callback_url(settings)}")
    if settings.exotel_account_sid and settings.exotel_app_id:
        print(f"Flow URL (Url=)  : {flow_url(settings.exotel_account_sid, settings.exotel_app_id)}")
    missing = [
        name
        for name, value in {
            "EXOTEL_API_KEY": settings.exotel_api_key,
            "EXOTEL_API_TOKEN": settings.exotel_api_token,
            "EXOTEL_ACCOUNT_SID": settings.exotel_account_sid,
            "EXOTEL_SUBDOMAIN": settings.exotel_subdomain,
            "EXOTEL_CALLER_ID": settings.exotel_caller_id,
            "EXOTEL_APP_ID": settings.exotel_app_id,
        }.items()
        if not value
    ]
    if missing:
        print("Still missing:", ", ".join(missing))


if __name__ == "__main__":
    main()
