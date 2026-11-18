import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.database.models.enums import ImportBatchStatus
from app.services.import_validation import RowStatus


class ImportField(BaseModel):
    key: str
    label: str
    required: bool


class RowIssue(BaseModel):
    field: str
    code: str
    message: str


class ImportRow(BaseModel):
    row: int
    status: RowStatus
    values: dict[str, Any]
    errors: list[RowIssue]
    warnings: list[RowIssue]
    existing_candidate_id: str | None


class ReportError(BaseModel):
    row: int
    field: str
    message: str


class ImportReport(BaseModel):
    total_rows: int
    valid_candidates: int
    duplicate_candidates: int
    duplicates_in_file: int
    duplicates_existing: int
    invalid_candidates: int
    imported_candidates: int
    errors: list[ReportError]


class ImportOut(BaseModel):
    id: uuid.UUID
    status: ImportBatchStatus
    filename: str
    job_id: uuid.UUID
    created_at: datetime
    confirmed_at: datetime | None
    expires_at: datetime | None
    headers: list[str]
    column_mapping: dict[str, int | None]
    unmapped_columns: list[str]
    fields: list[ImportField]
    rows: list[ImportRow]
    report: ImportReport


class MappingUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    column_mapping: dict[str, int | None]


class ImportConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    consent_attested: bool
