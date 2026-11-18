"""Domain errors raised by services. Rendered by the API's error handler as the error envelope."""

from typing import Any

from app.api.responses import AppError


def not_found(code: str, message: str) -> AppError:
    return AppError(404, code, message)


def conflict(code: str, message: str, details: Any = None) -> AppError:
    return AppError(409, code, message, details)


def unprocessable(code: str, message: str, details: Any = None) -> AppError:
    return AppError(422, code, message, details)


def gone(code: str, message: str) -> AppError:
    return AppError(410, code, message)
