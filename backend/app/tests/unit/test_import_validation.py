import pytest

from app.services.import_validation import (
    RowStatus,
    auto_map,
    build_report,
    check_mapping,
    normalize_header,
    unmapped_columns,
    validate_row,
    validate_rows,
)
from app.utils.candidate_fields import parse_experience

HEADERS = ["Candidate Name", "Mobile No.", "Applied For", "E-mail ID", "Exp", "Notes", "Extra"]
MAPPING = auto_map(HEADERS)


def row(
    name: str = "Test Person",
    phone: str = "9000000001",
    role: str = "Developer",
    email: str = "",
    exp: str = "",
    notes: str = "",
) -> list[str]:
    return [name, phone, role, email, exp, notes, "ignored"]


def test_normalize_header() -> None:
    assert normalize_header("  Mobile No. ") == "mobileno"
    assert normalize_header("E-mail_ID") == "emailid"


def test_auto_map_uses_synonyms() -> None:
    assert MAPPING == {
        "name": 0,
        "phone": 1,
        "applied_role": 2,
        "email": 3,
        "total_experience": 4,
        "current_company": None,
        "current_location": None,
        "resume_url": None,
        "source": None,
        "recruiter_notes": 5,
    }
    assert unmapped_columns(HEADERS, MAPPING) == ["Extra"]


def test_auto_map_never_reuses_a_column() -> None:
    # "location" and "city" both map to current_location; the second stays unmapped.
    mapping = auto_map(["Name", "Phone", "Role", "Location", "City"])
    assert mapping["current_location"] == 3
    assert unmapped_columns(["Name", "Phone", "Role", "Location", "City"], mapping) == ["City"]


def test_check_mapping() -> None:
    assert check_mapping(MAPPING, len(HEADERS)) == []
    assert check_mapping({"name": 0, "phone": 0}, 3) == [
        "The same column is mapped to more than one field"
    ]
    assert check_mapping({"name": 9}, 3) == ["Column 9 for 'name' doesn't exist"]
    assert check_mapping({"salary": 1}, 3) == ["Unknown field 'salary'"]


@pytest.mark.parametrize(
    ("raw", "years"),
    [("5", 5.0), ("5.5", 5.5), ("5 years", 5.0), ("5 yrs", 5.0), ("1 year", 1.0), ("5+", 5.0)],
)
def test_parse_experience(raw: str, years: float) -> None:
    assert parse_experience(raw) == years


@pytest.mark.parametrize("raw", ["five", "61", "-1", "5 months", "3-5"])
def test_parse_experience_rejects(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_experience(raw)


def test_valid_row_values_are_normalized() -> None:
    result = validate_row(2, row(email="Test@Example.COM", exp="4 yrs", notes="ok"), MAPPING)
    assert result.status == RowStatus.VALID
    assert result.values["phone"] == "+919000000001"
    assert result.values["email"] == "Test@example.com"
    assert result.values["total_experience"] == 4.0
    assert result.values["recruiter_notes"] == "ok"


def test_invalid_row_lists_every_problem() -> None:
    result = validate_row(7, row(name="", phone="123", role="", email="nope", exp="lots"), MAPPING)
    assert result.status == RowStatus.INVALID
    assert {(e.field, e.code) for e in result.errors} == {
        ("name", "required"),
        ("applied_role", "required"),
        ("phone", "phone_too_short"),
        ("email", "invalid_email"),
        ("total_experience", "invalid_experience"),
    }


def test_resume_url_must_be_http() -> None:
    mapping = auto_map(["Name", "Phone", "Role", "Resume"])
    bad = validate_row(2, ["A", "9000000001", "Dev", "javascript:alert(1)"], mapping)
    good = validate_row(2, ["A", "9000000001", "Dev", "https://example.com/cv.pdf"], mapping)
    assert bad.errors[0].code == "invalid_url"
    assert good.values["resume_url"] == "https://example.com/cv.pdf"


def test_missing_required_mapping_makes_rows_invalid() -> None:
    mapping = auto_map(["Name", "Phone"])  # no job role column
    result = validate_row(2, ["A", "9000000001"], mapping)
    assert result.status == RowStatus.INVALID
    assert result.errors[0].field == "applied_role"


def test_duplicates_in_file_and_existing() -> None:
    rows = [
        row(phone="9000000001"),
        row(phone="+91 90000 00001"),  # same as row 2 after normalization
        row(phone="9000000002"),  # exists already
        row(phone="9000000003"),
        row(name="", phone="9000000003"),  # invalid row doesn't claim a phone
    ]
    existing = {"+919000000002": "existing-id"}
    result = validate_rows(rows, [2, 3, 4, 5, 6], MAPPING, existing)
    assert [r.status for r in result] == [
        RowStatus.VALID,
        RowStatus.DUPLICATE_IN_FILE,
        RowStatus.DUPLICATE_EXISTING,
        RowStatus.VALID,
        RowStatus.INVALID,
    ]
    assert result[1].errors[0].message == "Same phone as row 2"
    assert result[2].existing_candidate_id == "existing-id"

    report = build_report(result)
    assert report["total_rows"] == 5
    assert report["valid_candidates"] == 2
    assert report["duplicate_candidates"] == 2
    assert report["duplicates_in_file"] == 1
    assert report["duplicates_existing"] == 1
    assert report["invalid_candidates"] == 1
    assert report["imported_candidates"] == 0
    assert {"row": 6, "field": "name", "message": "Candidate name is required"} in report["errors"]
