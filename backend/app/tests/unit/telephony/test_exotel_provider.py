import json
from datetime import UTC, datetime
from urllib.parse import parse_qs

import httpx
import pytest

from app.providers.telephony.base import (
    TelephonyConfigError,
    TelephonyRejectedError,
    TelephonyTimeoutError,
)
from app.providers.telephony.exotel_provider import ExotelProvider
from app.tests.conftest import make_settings

EXOTEL = {
    "exotel_api_key": "key",
    "exotel_api_token": "token",
    "exotel_account_sid": "acct1",
    "exotel_subdomain": "api.in.exotel.com",
    "exotel_caller_id": "08000000000",
    "exotel_app_id": "12345",
    "public_backend_url": "https://tunnel.example.com",
}


def _provider(handler: httpx.MockTransport) -> ExotelProvider:
    return ExotelProvider(make_settings(**EXOTEL), transport=handler)


async def test_initiate_call_request_and_response() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"Call": {"Sid": "sid-1", "Status": "in-progress"}})

    provider = _provider(httpx.MockTransport(handler))
    call = await provider.initiate_call(
        to_phone="+919000009001",
        call_attempt_id="0e3c1c9a-1d2b-4c5e-8f00-123456789abc",
        status_callback_url="https://cb",
    )
    await provider.close()
    assert (call.provider_call_id, call.raw_status) == ("sid-1", "in-progress")
    (req,) = seen
    assert str(req.url) == "https://api.in.exotel.com/v1/Accounts/acct1/Calls/connect.json"
    assert req.headers["authorization"].startswith("Basic ")
    form = {k: v[0] for k, v in parse_qs(req.content.decode()).items()}
    assert form["From"] == "+919000009001"
    assert form["CallerId"] == "08000000000"
    assert not any(k.startswith("StatusCallbackEvents") for k in form)
    assert form["Url"] == "http://my.exotel.com/acct1/exoml/start_voice/12345"
    assert form["CustomField"] == "0e3c1c9a1d2b4c5e8f00123456789abc"
    assert (form["CallType"], form["TimeLimit"], form["TimeOut"]) == ("trans", "900", "30")
    assert form["StatusCallback"] == "https://cb"
    assert "StatusCallbackContentType" not in form
    assert not any(k.startswith("StatusCallbackEvents") for k in form)


async def test_timeout_is_ambiguous_not_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("slow", request=request)

    provider = _provider(httpx.MockTransport(handler))
    with pytest.raises(TelephonyTimeoutError):
        await provider.initiate_call(to_phone="+91", call_attempt_id="a", status_callback_url="u")
    assert calls == 1


@pytest.mark.parametrize(
    ("status", "error"),
    [(401, TelephonyConfigError), (400, TelephonyRejectedError), (403, TelephonyRejectedError)],
)
async def test_error_mapping(status: int, error: type[Exception]) -> None:
    body = {"RestException": {"Status": status, "Message": "From number not verified"}}
    provider = _provider(httpx.MockTransport(lambda r: httpx.Response(status, json=body)))
    with pytest.raises(error) as exc:
        await provider.initiate_call(to_phone="+91", call_attempt_id="a", status_callback_url="u")
    assert "key" not in str(exc.value) and "token" not in str(exc.value)


async def test_get_call_status_maps_and_404_is_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/missing.json"):
            return httpx.Response(404, json={})
        return httpx.Response(
            200,
            json={
                "Call": {
                    "Sid": "sid-1",
                    "Status": "no-answer",
                    "StartTime": "2026-11-18 15:00:00",
                    "Details": {"ConversationDuration": 0},
                }
            },
        )

    provider = _provider(httpx.MockTransport(handler))
    status = await provider.get_call_status("sid-1")
    assert status is not None
    assert (status.status, status.end_reason, status.duration_seconds) == (
        "no_answer",
        "no_answer",
        0,
    )
    assert await provider.get_call_status("missing") is None


async def test_find_calls_filters_by_number() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["From"] == "+919000009001"
        assert request.url.params["DateCreated"].startswith("gte:2026-11-18 ")
        return httpx.Response(
            200,
            content=json.dumps(
                {
                    "Calls": [
                        {"Sid": "a", "Status": "completed", "From": "09000009001"},
                        {"Sid": "b", "Status": "completed", "From": "09999999999"},
                    ]
                }
            ),
        )

    provider = _provider(httpx.MockTransport(handler))
    found = await provider.find_calls(
        to_phone="+919000009001", since=datetime(2026, 11, 18, 9, 0, tzinfo=UTC)
    )
    assert [c.provider_call_id for c in found] == ["a"]


def test_incomplete_settings_rejected() -> None:
    with pytest.raises(TelephonyConfigError):
        ExotelProvider(make_settings(**{**EXOTEL, "exotel_app_id": None}))
