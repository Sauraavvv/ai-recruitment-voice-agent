"""Pure import logic: header auto-mapping, row validation and duplicate classification.

No I/O here; `import_service` supplies the set of phones that already exist.
"""

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.utils import candidate_fields as rules
from app.utils.phone import PHONE_ERROR_MESSAGES, normalize_phone

IMPORT_FIELDS: tuple[str, ...] = (
    "name",
    "phone",
    "applied_role",
    "email",
    "total_experience",
    "current_company",
    "current_location",
    "resume_url",
    "source",
    "recruiter_notes",
)
REQUIRED_FIELDS: tuple[str, ...] = ("name", "phone", "applied_role")

FIELD_LABELS: dict[str, str] = {
    "name": "Candidate name",
    "phone": "Phone number",
    "applied_role": "Job role",
    "email": "Email",
    "total_experience": "Total experience",
    "current_company": "Current company",
    "current_location": "Current location",
    "resume_url": "Resume URL",
    "source": "Candidate source",
    "recruiter_notes": "Recruiter notes",
}

HEADER_SYNONYMS: dict[str, tuple[str, ...]] = {
    "name": ("name", "candidatename", "fullname"),
    "phone": (
        "phone",
        "phonenumber",
        "mobile",
        "mobileno",
        "mobilenumber",
        "contact",
        "contactnumber",
    ),
    "applied_role": ("jobrole", "role", "position", "appliedfor", "designation"),
    "email": ("email", "emailid", "mail"),
    "total_experience": ("totalexperience", "experience", "exp", "totalexp", "yearsofexperience"),
    "current_company": ("currentcompany", "company", "employer", "currentemployer"),
    "current_location": ("currentlocation", "location", "city"),
    "resume_url": ("resume", "resumeurl", "cv", "cvlink"),
    "source": ("source", "candidatesource"),
    "recruiter_notes": ("notes", "recruiternotes", "remarks", "comments"),
}

ColumnMapping = dict[str, int | None]  # field -> column index


class RowStatus(StrEnum):
    VALID = "valid"
    INVALID = "invalid"
    DUPLICATE_IN_FILE = "duplicate_in_file"
    DUPLICATE_EXISTING = "duplicate_existing"


def normalize_header(header: str) -> str:
    return re.sub(r"[^a-z0-9]", "", header.lower())


def auto_map(headers: list[str]) -> ColumnMapping:
    """Map each field to the first header matching one of its synonyms."""
    normalized = [normalize_header(h) for h in headers]
    mapping: ColumnMapping = {}
    used: set[int] = set()
    for field_name in IMPORT_FIELDS:
        mapping[field_name] = None
        for synonym in HEADER_SYNONYMS[field_name]:
            index = next(
                (i for i, h in enumerate(normalized) if h == synonym and i not in used), None
            )
            if index is not None:
                mapping[field_name] = index
                used.add(index)
                break
    return mapping


def check_mapping(mapping: ColumnMapping, header_count: int) -> list[str]:
    """Problems with a recruiter-supplied mapping (empty list = OK)."""
    problems = []
    for field_name, index in mapping.items():
        if field_name not in IMPORT_FIELDS:
            problems.append(f"Unknown field '{field_name}'")
        elif index is not None and not 0 <= index < header_count:
            problems.append(f"Column {index} for '{field_name}' doesn't exist")
    indexes = [i for i in mapping.values() if i is not None]
    if len(indexes) != len(set(indexes)):
        problems.append("The same column is mapped to more than one field")
    return problems


def unmapped_columns(headers: list[str], mapping: ColumnMapping) -> list[str]:
    used = {i for i in mapping.values() if i is not None}
    return [h for i, h in enumerate(headers) if i not in used and h]


@dataclass
class RowError:
    field: str
    code: str
    message: str


@dataclass
class ValidatedRow:
    row: int  # spreadsheet row number
    status: RowStatus
    values: dict[str, Any]
    errors: list[RowError] = field(default_factory=list)
    warnings: list[RowError] = field(default_factory=list)
    existing_candidate_id: str | None = None


def _text(values: dict[str, Any], errors: list[RowError], name: str, raw: str, limit: int) -> None:
    if not raw:
        values[name] = None
    elif len(raw) > limit:
        errors.append(RowError(name, "too_long", f"Longer than {limit} characters"))
    else:
        values[name] = raw


def validate_row(
    row_number: int, cells: list[str], mapping: ColumnMapping, default_role: str | None = None
) -> ValidatedRow:
    """`default_role` fills an empty job role (a requirement's upload: the role is its title)."""

    def cell(field_name: str) -> str:
        index = mapping.get(field_name)
        value = cells[index].strip() if index is not None and index < len(cells) else ""
        if field_name == "applied_role" and not value and default_role:
            return default_role
        return value

    values: dict[str, Any] = {}
    errors: list[RowError] = []
    warnings: list[RowError] = []

    for required in ("name", "applied_role"):
        raw = cell(required)
        if not raw:
            errors.append(RowError(required, "required", f"{FIELD_LABELS[required]} is required"))
        elif len(raw) > rules.MAX_NAME_LENGTH:
            errors.append(
                RowError(required, "too_long", f"Longer than {rules.MAX_NAME_LENGTH} characters")
            )
        else:
            values[required] = raw

    phone = normalize_phone(cell("phone"))
    if phone.e164 is None:
        code = phone.error or "phone_invalid"
        errors.append(RowError("phone", code, PHONE_ERROR_MESSAGES[code]))
    else:
        values["phone"] = phone.e164
        if phone.warning == "not_mobile":
            warnings.append(
                RowError("phone", "not_mobile", "This doesn't look like a mobile number")
            )
        elif phone.warning == "foreign_number":
            warnings.append(RowError("phone", "foreign_number", "Number is outside India"))

    email = cell("email")
    values["email"] = None
    if email:
        try:
            values["email"] = rules.normalize_email(email)
        except ValueError as exc:
            errors.append(RowError("email", "invalid_email", str(exc)))

    experience = cell("total_experience")
    values["total_experience"] = None
    if experience:
        try:
            values["total_experience"] = rules.parse_experience(experience)
        except ValueError as exc:
            errors.append(RowError("total_experience", "invalid_experience", str(exc)))

    resume = cell("resume_url")
    values["resume_url"] = None
    if resume:
        try:
            values["resume_url"] = rules.check_http_url(resume)
        except ValueError as exc:
            errors.append(RowError("resume_url", "invalid_url", str(exc)))

    for name in ("current_company", "current_location", "source"):
        _text(values, errors, name, cell(name), rules.MAX_TEXT_LENGTH)
    _text(values, errors, "recruiter_notes", cell("recruiter_notes"), rules.MAX_NOTES_LENGTH)

    status = RowStatus.INVALID if errors else RowStatus.VALID
    return ValidatedRow(row_number, status, values, errors, warnings)


def validate_rows(
    rows: list[list[str]],
    row_numbers: list[int],
    mapping: ColumnMapping,
    existing_phones: dict[str, str],
    default_role: str | None = None,
) -> list[ValidatedRow]:
    """Validate every row and flag duplicates.

    `existing_phones` maps E.164 phone -> existing candidate id. Within the file the first valid
    occurrence of a phone wins.
    """
    seen: dict[str, int] = {}
    result = []
    for row_number, cells in zip(row_numbers, rows, strict=True):
        validated = validate_row(row_number, cells, mapping, default_role)
        if validated.status == RowStatus.VALID:
            phone = validated.values["phone"]
            if phone in seen:
                validated.status = RowStatus.DUPLICATE_IN_FILE
                validated.errors.append(
                    RowError("phone", "duplicate_in_file", f"Same phone as row {seen[phone]}")
                )
            elif phone in existing_phones:
                validated.status = RowStatus.DUPLICATE_EXISTING
                validated.existing_candidate_id = existing_phones[phone]
                validated.errors.append(
                    RowError(
                        "phone",
                        "duplicate_existing",
                        "A candidate with this phone already exists; it won't be changed",
                    )
                )
            else:
                seen[phone] = row_number
        result.append(validated)
    return result


def build_report(rows: list[ValidatedRow], imported: int = 0) -> dict[str, Any]:
    """plan.md Module A report shape, plus per-row errors."""
    counts: dict[str, int] = {status.value: 0 for status in RowStatus}
    for row in rows:
        counts[row.status] += 1
    duplicates = counts[RowStatus.DUPLICATE_IN_FILE] + counts[RowStatus.DUPLICATE_EXISTING]
    return {
        "total_rows": len(rows),
        "valid_candidates": counts[RowStatus.VALID],
        "duplicate_candidates": duplicates,
        "duplicates_in_file": counts[RowStatus.DUPLICATE_IN_FILE],
        "duplicates_existing": counts[RowStatus.DUPLICATE_EXISTING],
        "invalid_candidates": counts[RowStatus.INVALID],
        "imported_candidates": imported,
        "errors": [
            {"row": row.row, "field": error.field, "message": error.message}
            for row in rows
            for error in row.errors
        ],
    }
