"""Candidate import: upload -> preview (stored batch) -> optional remap -> confirm.

plan.md Module A. Import never modifies existing candidates.
"""

import asyncio
import uuid
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.responses import AppError
from app.database.models import ConsentSource, ImportBatch, ImportBatchStatus, Requirement, User
from app.repositories import candidate_repo, import_repo
from app.services import job_service, requirement_service
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


async def _default_role(session: AsyncSession, batch: ImportBatch) -> str | None:
    """A requirement's upload doesn't need a job-role column: the role is its title."""
    if batch.requirement_id is None:
        return None
    requirement = await session.get(Requirement, batch.requirement_id)
    return requirement.title if requirement else None


async def _organization(session: AsyncSession, batch: ImportBatch) -> uuid.UUID:
    """The company the uploaded candidates belong to: the requirement's, or the uploader's."""
    if batch.requirement_id is not None:
        requirement = await session.get(Requirement, batch.requirement_id)
        if requirement is not None:
            return requirement.organization_id
    uploader = await session.get(User, batch.uploaded_by)
    if uploader is None:
        raise not_found("import_not_found", "Import not found")
    return uploader.organization_id


async def _validate(session: AsyncSession, batch: ImportBatch) -> list[ValidatedRow]:
    stored = batch.rows or []
    cells = [r["cells"] for r in stored]
    numbers = [r["row"] for r in stored]
    mapping = _mapping(batch)
    role = await _default_role(session, batch)
    # First pass to learn the phones, then look them all up in one query.
    first = validate_rows(cells, numbers, mapping, {}, role)
    phones = [r.values["phone"] for r in first if r.values.get("phone")]
    existing = await candidate_repo.ids_by_phone(
        session,
        phones,
        organization_id=await _organization(session, batch),
        requirement_id=batch.requirement_id,
    )
    return validate_rows(cells, numbers, mapping, existing, role)


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
        "requirement_id": batch.requirement_id,
        "created_at": batch.created_at,
        "confirmed_at": batch.confirmed_at,
        "expires_at": batch.created_at + PREVIEW_TTL
        if status == ImportBatchStatus.PREVIEW
        else None,
        "headers": batch.headers,
        "column_mapping": mapping,
        "unmapped_columns": unmapped_columns(batch.headers, mapping),
        "fields": [
            {
                "key": f,
                "label": FIELD_LABELS[f],
                # a requirement's upload takes the role from the requirement
                "required": f in REQUIRED_FIELDS
                and not (f == "applied_role" and batch.requirement_id is not None),
            }
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
    requirement_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """An upload for a requirement (`requirement_id`, which the user must be able to see), or
    else for `job_id` / the active job."""
    if requirement_id is not None:
        if job_id is not None:
            raise unprocessable("one_target", "Upload for a job or for a requirement, not both")
        requirement, _client = await requirement_service.get_requirement(
            session, user, requirement_id
        )
        target: dict[str, uuid.UUID | None] = {"job_id": None, "requirement_id": requirement.id}
    else:
        job = await job_service.resolve(session, job_id)
        target = {"job_id": job.id, "requirement_id": None}
    try:
        parsed = await asyncio.to_thread(parse_upload, filename, content)
    except FileParseError as exc:
        raise unprocessable(exc.code, exc.message) from None

    mapping = auto_map(parsed.headers)
    batch = ImportBatch(
        uploaded_by=user.id,
        **target,
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


async def check_access(session: AsyncSession, user: User, import_id: uuid.UUID) -> None:
    """A requirement's upload is only for those who can see the requirement."""
    batch = await import_repo.get(session, import_id)
    if batch is None:
        raise not_found("import_not_found", "Import not found")
    if batch.requirement_id is not None:
        try:
            await requirement_service.get_requirement(session, user, batch.requirement_id)
        except AppError:
            raise not_found("import_not_found", "Import not found") from None
    elif await _organization(session, batch) != user.organization_id:
        raise not_found("import_not_found", "Import not found")  # another company's upload


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
    organization_id = await _organization(session, batch)
    to_insert = [
        {
            **row.values,
            "organization_id": organization_id,
            "job_id": batch.job_id,
            "requirement_id": batch.requirement_id,
            "consent_source": ConsentSource.RECRUITER_ATTESTED_IMPORT.value,
            "consent_at": now,
        }
        for row in rows
        if row.status == RowStatus.VALID
    ]
    inserted = await candidate_repo.insert_ignoring_duplicates(
        session, to_insert, batch.requirement_id
    )

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
