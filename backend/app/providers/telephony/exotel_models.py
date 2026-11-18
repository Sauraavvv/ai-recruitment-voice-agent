"""Exotel payloads, status mapping and stream messages (docs/telephony.md).

Field names are from Exotel's v1 docs (read 2026-11-18) and are checked against payloads captured
on real calls (app/tests/fixtures/exotel/). One table maps Exotel statuses to internal ones.
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.database.models.enums import CallEndReason, CallStatus

PROVIDER = "exotel"

# Exotel Call.Status / StatusCallback Status → (internal status, end reason when terminal)
STATUS_MAP: dict[str, tuple[CallStatus, CallEndReason | None]] = {
    "queued": (CallStatus.INITIATING, None),
    "ringing": (CallStatus.RINGING, None),
    "in-progress": (CallStatus.IN_PROGRESS, None),
    "completed": (CallStatus.COMPLETED, None),  # who hung up is decided by the stream side
    "busy": (CallStatus.BUSY, CallEndReason.BUSY),
    "no-answer": (CallStatus.NO_ANSWER, CallEndReason.NO_ANSWER),
    "failed": (CallStatus.FAILED, CallEndReason.PROVIDER_FAILED),
    "canceled": (CallStatus.CANCELLED, CallEndReason.CANCELLED),
    "cancelled": (CallStatus.CANCELLED, CallEndReason.CANCELLED),
}


def map_status(raw: str | None) -> tuple[CallStatus, CallEndReason | None] | None:
    if not raw:
        return None
    return STATUS_MAP.get(raw.strip().lower())


def parse_exotel_time(value: Any, tz: str) -> datetime | None:
    """Exotel timestamps are 'YYYY-MM-DD HH:mm:ss' in the account's local time [verify: IST]."""
    if not value or not isinstance(value, str):
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value.strip()[:19], fmt).replace(tzinfo=ZoneInfo(tz))
        except ValueError:
            continue
    try:  # ISO with offset
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _int(value: Any) -> int | None:
    try:
        return int(float(value)) if value not in (None, "", "null") else None
    except (TypeError, ValueError):
        return None


def _str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text and text.lower() != "null" else None


@dataclass(frozen=True)
class StatusCallback:
    """A normalized StatusCallback webhook."""

    call_sid: str | None
    event_type: str  # "terminal", "answered", or "status" when Exotel doesn't say
    raw_status: str | None
    custom_field: str | None
    date_updated: str | None
    start_time: datetime | None
    end_time: datetime | None
    duration_seconds: int | None
    recording_url: str | None
    legs: list[dict[str, Any]] = field(default_factory=list)

    def dedupe_key(self) -> str:
        """Same call + event + status + provider timestamp = the same delivery."""
        basis = "|".join(
            [
                PROVIDER,
                self.call_sid or "",
                self.event_type,
                self.raw_status or "",
                self.date_updated or "",
            ]
        )
        return hashlib.sha256(basis.encode()).hexdigest()


def flatten_form(items: list[tuple[str, str]]) -> dict[str, Any]:
    """Form fields like `Legs[0][Status]` → {"Legs": [{"Status": ...}]}; plain keys kept."""
    out: dict[str, Any] = {}
    for key, value in items:
        if "[" not in key:
            out[key] = value
            continue
        head, _, rest = key.partition("[")
        parts = [head, *(p.rstrip("]") for p in rest.split("["))]
        node: Any = out
        for i, part in enumerate(parts):
            last = i == len(parts) - 1
            nxt_is_index = not last and parts[i + 1].isdigit()
            if isinstance(node, list):
                idx = int(part)
                while len(node) <= idx:
                    node.append({} if not last else None)
                if last:
                    node[idx] = value
                else:
                    if not isinstance(node[idx], (dict, list)):
                        node[idx] = [] if nxt_is_index else {}
                    node = node[idx]
            else:
                if last:
                    node[part] = value
                else:
                    node = node.setdefault(part, [] if nxt_is_index else {})
    return out


def parse_status_callback(payload: dict[str, Any], *, tz: str) -> StatusCallback:
    legs = payload.get("Legs") or []
    if isinstance(legs, str):
        try:
            legs = json.loads(legs)
        except ValueError:
            legs = []
    duration = _int(payload.get("ConversationDuration"))
    if duration is None:
        duration = _int((payload.get("Details") or {}).get("ConversationDuration"))
    return StatusCallback(
        call_sid=_str(payload.get("CallSid")),
        event_type=(_str(payload.get("EventType")) or "status").lower(),
        raw_status=_str(payload.get("Status") or payload.get("CallStatus")),
        custom_field=_str(payload.get("CustomField")),
        date_updated=_str(payload.get("DateUpdated")),
        start_time=parse_exotel_time(payload.get("StartTime"), tz),
        end_time=parse_exotel_time(payload.get("EndTime"), tz),
        duration_seconds=duration,
        recording_url=_str(payload.get("RecordingUrl")),
        legs=[leg for leg in legs if isinstance(leg, dict)] if isinstance(legs, list) else [],
    )


# --- Voicebot stream -------------------------------------------------------------------------


@dataclass(frozen=True)
class StreamStart:
    stream_sid: str | None
    call_sid: str | None
    account_sid: str | None
    from_number: str | None
    to_number: str | None
    custom_parameters: dict[str, str]
    encoding: str | None
    sample_rate: int | None


def parse_stream_start(message: dict[str, Any]) -> StreamStart:
    start = message.get("start") or {}
    fmt = start.get("media_format") or {}
    params = start.get("custom_parameters") or {}
    return StreamStart(
        stream_sid=_str(message.get("stream_sid") or start.get("stream_sid")),
        call_sid=_str(start.get("call_sid")),
        account_sid=_str(start.get("account_sid")),
        from_number=_str(start.get("from")),
        to_number=_str(start.get("to")),
        custom_parameters={str(k): str(v) for k, v in params.items()}
        if isinstance(params, dict)
        else {},
        encoding=_str(fmt.get("encoding")),
        sample_rate=_int(fmt.get("sample_rate")),
    )


# Exotel names for our TELEPHONY_ENCODING values
# Exotel announces "base64" (the transport) for 16-bit PCM payloads (real call 2026-11-19).
ENCODING_ALIASES = {
    "slin": {"raw", "slin", "linear16", "pcm", "base64"},
    "mulaw": {"mulaw", "ulaw"},
}


def media_format_matches(start: StreamStart, *, encoding: str, sample_rate: int) -> bool:
    """True unless the start message announces a different format than configured."""
    if start.encoding and start.encoding.lower() not in ENCODING_ALIASES.get(encoding, set()):
        return False
    return not (start.sample_rate and start.sample_rate != sample_rate)


def message_shape(message: Any) -> Any:
    """Field names and value types/lengths only, for logs and fixtures (never content)."""
    if isinstance(message, dict):
        return {k: message_shape(v) for k, v in message.items()}
    if isinstance(message, list):
        return [message_shape(v) for v in message[:3]]
    if isinstance(message, str):
        return f"str[{len(message)}]"
    return type(message).__name__
