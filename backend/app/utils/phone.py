"""Phone number normalization to E.164 (plan.md Module A: the duplicate-detection key)."""

import re
from dataclasses import dataclass

import phonenumbers
from phonenumbers import NumberParseException, PhoneNumberType

DEFAULT_REGION = "IN"

# Excel turns long numbers into floats ("9876543210.0") or scientific notation ("9.87654E+09").
_FLOAT_FORM = re.compile(r"^\+?\d+\.0+$")
_SCIENTIFIC_FORM = re.compile(r"^[+-]?\d+(\.\d+)?[eE][+-]?\d+$")


class PhoneError:
    REQUIRED = "phone_required"
    SCIENTIFIC_NOTATION = "phone_scientific_notation"
    UNPARSEABLE = "phone_unparseable"
    TOO_SHORT = "phone_too_short"
    TOO_LONG = "phone_too_long"
    INVALID = "phone_invalid"


PHONE_ERROR_MESSAGES = {
    PhoneError.REQUIRED: "Phone number is required",
    PhoneError.SCIENTIFIC_NOTATION: (
        "Phone number was converted to scientific notation by Excel and lost digits; "
        "format the phone column as text and re-enter it"
    ),
    PhoneError.UNPARSEABLE: "Phone number could not be read",
    PhoneError.TOO_SHORT: "Phone number is too short",
    PhoneError.TOO_LONG: "Phone number is too long",
    PhoneError.INVALID: "Phone number is not a valid number",
}


@dataclass(frozen=True)
class PhoneResult:
    e164: str | None
    error: str | None = None
    warning: str | None = None

    @property
    def ok(self) -> bool:
        return self.e164 is not None


def _clean(raw: str) -> str:
    value = raw.strip().lstrip("'").strip()
    if _FLOAT_FORM.match(value):
        value = value.split(".", 1)[0]
    # "(+91)9876543210" -> "+919876543210"
    value = re.sub(r"^\(\+(\d{1,3})\)", r"+\1", value)
    return value


def normalize_phone(raw: str | None, default_region: str = DEFAULT_REGION) -> PhoneResult:
    """Return the E.164 form, or an error code from `PhoneError`.

    Non-mobile numbers are accepted with a warning: they may still be reachable by voice.
    """
    if raw is None or not raw.strip():
        return PhoneResult(None, PhoneError.REQUIRED)
    value = _clean(raw)
    if _SCIENTIFIC_FORM.match(value):
        return PhoneResult(None, PhoneError.SCIENTIFIC_NOTATION)

    digits = re.sub(r"\D", "", value)
    # "919876543210" (country code without "+") for the default region.
    country_code = phonenumbers.country_code_for_region(default_region)
    if (
        not value.startswith("+")
        and not value.startswith("0")
        and digits.startswith(str(country_code))
        and len(digits) > 10
    ):
        value = "+" + digits

    try:
        number = phonenumbers.parse(value, default_region)
    except NumberParseException as exc:
        if exc.error_type == NumberParseException.TOO_SHORT_NSN:
            return PhoneResult(None, PhoneError.TOO_SHORT)
        if exc.error_type == NumberParseException.TOO_LONG:
            return PhoneResult(None, PhoneError.TOO_LONG)
        return PhoneResult(None, PhoneError.UNPARSEABLE)

    possible = phonenumbers.is_possible_number_with_reason(number)
    if possible == phonenumbers.ValidationResult.TOO_SHORT:
        return PhoneResult(None, PhoneError.TOO_SHORT)
    if possible == phonenumbers.ValidationResult.TOO_LONG:
        return PhoneResult(None, PhoneError.TOO_LONG)
    if not phonenumbers.is_valid_number(number):
        return PhoneResult(None, PhoneError.INVALID)

    e164 = phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)
    warning = None
    mobile_types = (PhoneNumberType.MOBILE, PhoneNumberType.FIXED_LINE_OR_MOBILE)
    if phonenumbers.region_code_for_number(number) != default_region:
        warning = "foreign_number"
    elif phonenumbers.number_type(number) not in mobile_types:
        warning = "not_mobile"
    return PhoneResult(e164, None, warning)
