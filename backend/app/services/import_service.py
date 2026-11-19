"""Candidate import: upload -> preview (stored batch) -> optional remap -> confirm.

plan.md Module A. Import never modifies existing candidates.
"""

import asyncio
import uuid
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import ConsentSource, ImportBatch, ImportBatchStatus, User
from app.repositories import candidate_repo, import_repo
from app.services import job_service, sync_service
from app.services.errors import conflict, gone, not_found, unprocessable
from app.services.import_validation import (
    FIELD_LABELS,
    IMPORT_FIELDS,
    REQUIRED_FIELDS,
    ColumnMapping,
    RowStatus,
    ValidatedRow,
    auto_map,
    build_report,
    check_mapping,
    unmapped_columns,
    validate_rows,
)
from app.utils.file_parsing import FileParseError, parse_upload
from app.utils.log import get_logger

logger = get_logger(__name__)
PREVIEW_TTL = timedelta(hours=24)


def _mapping(batch: ImportBatch) -> ColumnMapping:
    return {f: batch.column_mapping.get(f) for f in IMPORT_FIELDS}


async def _validate(session: AsyncSession, batch: ImportBatch) -> list[ValidatedRow]:
    stored = batch.rows or []
    cells = [r["cells"] for r in stored]
    numbers = [r["row"] for r in stored]
    mapping = _mapping(batch)
    # First pass to learn the phones, then look them all up in one query.
    first = validate_rows(cells, numbers, mapping, {})
    phones = [r.values["phone"] for r in first if r.values.get("phone")]
    existing = await candidate_repo.ids_by_phone(session, phones)
    return validate_rows(cells, numbers, mapping, existing)


def _is_expired(batch: ImportBatch) -> bool:
    if batch.status == ImportBatchStatus.EXPIRED:
        return True
    return (
        batch.status == ImportBatchStatus.PREVIEW
        and batch.created_at < datetime.now(UTC) - PREVIEW_TTL
    )


async def _load_preview(session: AsyncSession, import_id: uuid.UUID) -> ImportBatch:
    """The batch, row-locked, if it is still an unexpired preview."""
    batch = await import_repo.get(session, import_id, for_update=True)
    if batch is None:
        raise not_found("import_not_found", "Import not found")
    if _is_expired(batch):
        raise gone("import_expired", "This preview has expired; upload the file again")
    if batch.status != ImportBatchStatus.PREVIEW:
        raise conflict("import_already_confirmed", "This import has already been confirmed")
    return batch


def present(batch: ImportBatch, rows: list[ValidatedRow] | None) -> dict[str, Any]:
    mapping = _mapping(batch)
    status = ImportBatchStatus.EXPIRED if _is_expired(batch) else batch.status
    return {
        "id": batch.id,
        "status": status,
        "filename": batch.filename,
        "job_id": batch.job_id,
        "created_at": batch.created_at,
        "confirmed_at": batch.confirmed_at,
        "expires_at": batch.created_at + PREVIEW_TTL
        if status == ImportBatchStatus.PREVIEW
        else None,
        "headers": batch.headers,
        "column_mapping": mapping,
        "unmapped_columns": unmapped_columns(batch.headers, mapping),
        "fields": [
            {"key": f, "label": FIELD_LABELS[f], "required": f in REQUIRED_FIELDS}
            for f in IMPORT_FIELDS
        ],
        "rows": [asdict(r) for r in rows] if rows is not None else [],
        "report": batch.report,
    }


async def upload(
    session: AsyncSession,
    user: User,
    job_id: uuid.UUID | None,
    filename: str,
    content: bytes,
) -> dict[str, Any]:
    job = await job_service.resolve(session, job_id)
    try:
        parsed = await asyncio.to_thread(parse_upload, filename, content)
    except FileParseError as exc:
        raise unprocessable(exc.code, exc.message) from None

    mapping = auto_map(parsed.headers)
    batch = ImportBatch(
        uploaded_by=user.id,
        job_id=job.id,
        filename=filename[:255],
        status=ImportBatchStatus.PREVIEW,
        headers=parsed.headers,
        column_mapping=mapping,
        rows=[
            {"row": number, "cells": cells}
            for number, cells in zip(parsed.row_numbers, parsed.rows, strict=True)
        ],
        report={},
    )
    rows = await _validate(session, batch)
    batch.report = build_report(rows)
    session.add(batch)
    await session.commit()
    await session.refresh(batch)
    logger.info(
        "import_uploaded",
        import_id=str(batch.id),
        rows=len(parsed.rows),
        valid=batch.report["valid_candidates"],
    )
    return present(batch, rows)


async def get(session: AsyncSession, import_id: uuid.UUID) -> dict[str, Any]:
    batch = await import_repo.get(session, import_id)
    if batch is None:
        raise not_found("import_not_found", "Import not found")
    if batch.status == ImportBatchStatus.PREVIEW and not _is_expired(batch):
        # Re-validate so the preview reflects candidates added since the upload.
        rows = await _validate(session, batch)
        batch.report = build_report(rows)
        return present(batch, rows)
    return present(batch, None)


async def remap(
    session: AsyncSession, import_id: uuid.UUID, mapping: dict[str, int | None]
) -> dict[str, Any]:
    batch = await _load_preview(session, import_id)
    problems = check_mapping(mapping, len(batch.headers))
    if problems:
        raise unprocessable("invalid_mapping", "; ".join(problems))
    batch.column_mapping = {f: mapping.get(f) for f in IMPORT_FIELDS}
    rows = await _validate(session, batch)
    batch.report = build_report(rows)
    await session.commit()
    await session.refresh(batch)
    return present(batch, rows)


async def confirm(
    session: AsyncSession, import_id: uuid.UUID, consent_attested: bool
) -> dict[str, Any]:
    if not consent_attested:
        raise unprocessable(
            "consent_required",
            "Confirm these candidates agreed to be contacted by phone about this role",
        )
    batch = await _load_preview(session, import_id)  # row-locked: no double confirm
    rows = await _validate(session, batch)
    now = datetime.now(UTC)
    to_insert = [
        {
            **row.values,
            "job_id": batch.job_id,
            "consent_source": ConsentSource.RECRUITER_ATTESTED_IMPORT.value,
            "consent_at": now,
        }
        for row in rows
        if row.status == RowStatus.VALID
    ]
    inserted = await candidate_repo.insert_ignoring_duplicates(session, to_insert)
    sync_service.record_changes(session, inserted)  # new rows for the sheet, same transaction

    batch.status = ImportBatchStatus.CONFIRMED
    batch.confirmed_at = now
    batch.rows = None  # candidate data now lives in `candidates`
    batch.report = build_report(rows, imported=len(inserted))
    await session.commit()
    await session.refresh(batch)
    logger.info(
        "import_confirmed",
        import_id=str(batch.id),
        imported=len(inserted),
        skipped_conflicts=len(to_insert) - len(inserted),
    )
    return present(batch, None)


async def expire_stale_previews(session: AsyncSession) -> int:
    count = await import_repo.expire_previews(session, datetime.now(UTC) - PREVIEW_TTL)
    await session.commit()
    return count
