"""Exotel v1 REST adapter (docs/telephony.md §2).

- Place a call: POST /v1/Accounts/{sid}/Calls/connect.json with `From` = the candidate and
  `Url` = our flow (Voicebot → Hangup). Exotel rings `From` first, then runs the flow.
- Status: GET /v1/Accounts/{sid}/Calls/{CallSid}.json; search: GET .../Calls.json.
- No automatic retry: a timed-out request may still have placed the call.
"""

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from app.config import Settings
from app.providers.telephony import exotel_models as em
from app.providers.telephony.base import (
    ProviderCall,
    ProviderCallStatus,
    TelephonyConfigError,
    TelephonyError,
    TelephonyProvider,
    TelephonyRejectedError,
    TelephonyTimeoutError,
)
from app.utils.log import get_logger
from app.utils.phone import normalize_phone

logger = get_logger(__name__)


def flow_url(account_sid: str, app_id: str) -> str:
    return f"http://my.exotel.com/{account_sid}/exoml/start_voice/{app_id}"


def _error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    exc = body.get("RestException") if isinstance(body, dict) else None
    if isinstance(exc, dict) and exc.get("Message"):
        return f"HTTP {response.status_code}: {exc['Message']}"
    return f"HTTP {response.status_code}"


class ExotelProvider(TelephonyProvider):
    name = em.PROVIDER

    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None):
        if not (
            settings.exotel_api_key
            and settings.exotel_api_token
            and settings.exotel_account_sid
            and settings.exotel_subdomain
            and settings.exotel_caller_id
            and settings.exotel_app_id
        ):
            raise TelephonyConfigError("Exotel settings are incomplete (EXOTEL_*)")
        self._sid = settings.exotel_account_sid
        self._caller_id = settings.exotel_caller_id
        self._flow_url = flow_url(settings.exotel_account_sid, settings.exotel_app_id)
        self._tz = settings.app_timezone
        self._time_limit = settings.max_call_duration_s
        self._ring_timeout = settings.ring_timeout_s
        host = settings.exotel_subdomain.removeprefix("https://").strip("/")
        self._client = httpx.AsyncClient(
            base_url=f"https://{host}/v1/Accounts/{self._sid}",
            auth=httpx.BasicAuth(
                settings.exotel_api_key.get_secret_value(),
                settings.exotel_api_token.get_secret_value(),
            ),
            timeout=httpx.Timeout(
                settings.exotel_read_timeout_s, connect=settings.exotel_connect_timeout_s
            ),
            transport=transport,
        )

    async def close(self) -> None:
        await self._client.aclose()

    def _raise_for(self, response: httpx.Response) -> None:
        if response.is_success:
            return
        message = _error_message(response)
        if response.status_code == 401:
            raise TelephonyConfigError(f"Exotel rejected the credentials ({message})")
        # 403 is also how Exotel refuses an unverified number on a trial account without KYC
        # ("Your account is not yet KYC compliant…", 2026-11-19): a refused call, not bad keys.
        if 400 <= response.status_code < 500:
            raise TelephonyRejectedError(message, status_code=response.status_code)
        raise TelephonyError(f"Exotel error ({message})")

    async def initiate_call(
        self, *, to_phone: str, call_attempt_id: str, status_callback_url: str
    ) -> ProviderCall:
        data: dict[str, str] = {
            "From": to_phone,  # connect-to-flow rings `From` first
            "CallerId": self._caller_id,
            "Url": self._flow_url,
            "CallType": "trans",
            "TimeLimit": str(self._time_limit),
            "TimeOut": str(self._ring_timeout),
            "CustomField": call_attempt_id.replace("-", ""),  # matching fallback
            # No StatusCallbackEvents: connect-to-flow answers HTTP 400 "Invalid
            # 'StatusCallbackEvents' specified" (real call 2026-11-19). The default callback
            # (form-encoded CallSid, Status, DateUpdated) comes at the end of every call, and
            # "answered" is known from the stream's `start`.
            "StatusCallback": status_callback_url,
            # No StatusCallbackEvents / StatusCallbackContentType: connect-to-flow answers HTTP 400
            # "Invalid 'StatusCallbackEvents' specified" to either (real calls 2026-11-19). The
            # default callback (form-encoded) still comes at the end; "answered" is known from
            # the stream's `start`.
        }
        try:
            response = await self._client.post("/Calls/connect.json", data=data)
        except httpx.TimeoutException as exc:
            # The call may exist: the caller must reconcile, not retry.
            raise TelephonyTimeoutError("Exotel did not answer in time") from exc
        except httpx.HTTPError as exc:
            # Connection refused/reset before sending: nothing placed.
            raise TelephonyError(f"Could not reach Exotel ({type(exc).__name__})") from exc
        self._raise_for(response)
        call = (response.json() or {}).get("Call") or {}
        sid = call.get("Sid")
        if not sid:
            raise TelephonyError("Exotel response had no Call.Sid")
        logger.info(
            "exotel_call_placed",
            call_attempt_id=call_attempt_id,
            provider_call_id=sid,
            provider_status=call.get("Status"),
        )
        return ProviderCall(provider_call_id=str(sid), raw_status=call.get("Status"))

    def _to_status(self, call: dict[str, Any]) -> ProviderCallStatus | None:
        sid = call.get("Sid")
        mapped = em.map_status(call.get("Status"))
        if not sid or mapped is None:
            return None
        status, reason = mapped
        details = call.get("Details") or {}
        raw_duration = details.get("ConversationDuration", call.get("Duration"))
        duration = "" if raw_duration is None else str(raw_duration)
        return ProviderCallStatus(
            provider_call_id=str(sid),
            raw_status=call.get("Status"),
            status=status.value,
            end_reason=reason.value if reason else None,
            start_time=em.parse_exotel_time(call.get("StartTime"), self._tz),
            end_time=em.parse_exotel_time(call.get("EndTime"), self._tz),
            duration_seconds=int(duration) if duration.isdigit() else None,
            recording_url=call.get("RecordingUrl") or None,
            raw={k: v for k, v in call.items() if k not in ("From", "To")},
        )

    async def get_call_status(self, provider_call_id: str) -> ProviderCallStatus | None:
        try:
            response = await self._client.get(
                f"/Calls/{provider_call_id}.json", params={"details": "true"}
            )
        except httpx.HTTPError as exc:
            raise TelephonyError(f"Could not reach Exotel ({type(exc).__name__})") from exc
        if response.status_code == 404:
            return None
        self._raise_for(response)
        return self._to_status((response.json() or {}).get("Call") or {})

    async def find_calls(self, *, to_phone: str, since: datetime) -> list[ProviderCallStatus]:
        local = since.astimezone(ZoneInfo(self._tz)).strftime("%Y-%m-%d %H:%M:%S")
        try:
            response = await self._client.get(
                "/Calls.json",
                params={"From": to_phone, "DateCreated": f"gte:{local}", "PageSize": "20"},
            )
        except httpx.HTTPError as exc:
            raise TelephonyError(f"Could not reach Exotel ({type(exc).__name__})") from exc
        self._raise_for(response)
        calls = (response.json() or {}).get("Calls") or []
        target = normalize_phone(to_phone).e164
        found = []
        for call in calls:
            numbers = {normalize_phone(str(call.get(k) or "")).e164 for k in ("From", "To")}
            status = self._to_status(call)
            if status and target in numbers:
                found.append(status)
        return found
