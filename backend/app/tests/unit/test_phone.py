import pytest

from app.utils.phone import PhoneError, normalize_phone


@pytest.mark.parametrize(
    "raw",
    [
        "+91 98765 43210",
        "+919876543210",
        "09876543210",
        "919876543210",
        "9876543210",
        "98765-43210",
        "(+91)9876543210",
        "+91-98765-43210",
        "9876543210.0",  # Excel float
        "'9876543210",  # Excel text prefix
        "  98765 43210  ",
        "+91 (987) 654-3210",
    ],
)
def test_indian_mobile_formats_normalize_to_e164(raw: str) -> None:
    result = normalize_phone(raw)
    assert result.e164 == "+919876543210"
    assert result.error is None
    assert result.warning is None


@pytest.mark.parametrize(
    ("raw", "error"),
    [
        (None, PhoneError.REQUIRED),
        ("", PhoneError.REQUIRED),
        ("   ", PhoneError.REQUIRED),
        ("9.87654E+09", PhoneError.SCIENTIFIC_NOTATION),
        ("9.876543210e9", PhoneError.SCIENTIFIC_NOTATION),
        ("12345", PhoneError.TOO_SHORT),
        ("98765432101234", PhoneError.TOO_LONG),
        ("not a phone", PhoneError.UNPARSEABLE),
        ("+91 0000000000", PhoneError.INVALID),
    ],
)
def test_rejected_numbers(raw: str | None, error: str) -> None:
    result = normalize_phone(raw)
    assert result.e164 is None
    assert result.error == error


def test_landline_is_accepted_with_warning() -> None:
    result = normalize_phone("011 2345 6789")
    assert result.e164 == "+911123456789"
    assert result.warning == "not_mobile"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("+1 415 555 2671", "+14155552671"), ("+44 7911 123456", "+447911123456")],
)
def test_foreign_number_is_accepted_with_warning(raw: str, expected: str) -> None:
    result = normalize_phone(raw)
    assert result.e164 == expected
    assert result.warning == "foreign_number"


def test_default_region_is_configurable() -> None:
    assert normalize_phone("415 555 2671", default_region="US").e164 == "+14155552671"
