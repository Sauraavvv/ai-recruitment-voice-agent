"""Structured logging with secret redaction and phone masking."""

import logging
import re
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog

SENSITIVE_KEY = re.compile(r"key|token|secret|password|authorization|cookie", re.IGNORECASE)
REDACTED = "[redacted]"


def mask_phone(phone: str | None) -> str | None:
    """`+919876543210` -> `+91******3210`. Keeps country code and last four digits."""
    if not phone:
        return phone
    digits_start = 3 if phone.startswith("+") else 0
    if len(phone) <= digits_start + 4:
        return "*" * len(phone)
    return phone[:digits_start] + "*" * (len(phone) - digits_start - 4) + phone[-4:]


def redact_sensitive(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    for key in list(event_dict):
        if key != "event" and SENSITIVE_KEY.search(key):
            event_dict[key] = REDACTED
    return event_dict


def configure_logging(level: str = "INFO", json_output: bool = False) -> None:
    renderer: Any = (
        structlog.processors.JSONRenderer() if json_output else structlog.dev.ConsoleRenderer()
    )
    log_level = logging.getLevelName(level.upper())
    if not isinstance(log_level, int):
        log_level = logging.INFO

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            redact_sensitive,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )
    # Route stdlib loggers (uvicorn, sqlalchemy, arq) to stdout at the same level.
    logging.basicConfig(
        level=log_level, stream=sys.stdout, format="%(levelname)s %(name)s %(message)s"
    )


def get_logger(name: str | None = None) -> Any:
    return structlog.get_logger(name)
