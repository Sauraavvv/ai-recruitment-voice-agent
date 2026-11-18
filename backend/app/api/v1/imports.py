import uuid
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, UploadFile, status

from app.api.deps import CurrentUser, SessionDep
from app.api.responses import ok
from app.schemas.common import DataResponse
from app.schemas.imports import ImportConfirm, ImportOut, MappingUpdate
from app.services import import_service
from app.services.errors import unprocessable
from app.utils.file_parsing import MAX_FILE_BYTES

router = APIRouter(prefix="/candidates/import", tags=["imports"])


@router.post("", response_model=DataResponse[ImportOut], status_code=status.HTTP_201_CREATED)
async def upload_import(
    user: CurrentUser,
    session: SessionDep,
    file: Annotated[UploadFile, File(description=".csv or .xlsx, up to 5 MB")],
    job_id: Annotated[uuid.UUID | None, Form()] = None,
) -> dict[str, Any]:
    content = await file.read(MAX_FILE_BYTES + 1)
    if len(content) > MAX_FILE_BYTES:
        raise unprocessable("file_too_large", "The file is larger than 5 MB")
    preview = await import_service.upload(session, user, job_id, file.filename or "", content)
    return ok(preview)


@router.get("/{import_id}", response_model=DataResponse[ImportOut])
async def get_import(import_id: uuid.UUID, session: SessionDep) -> dict[str, Any]:
    return ok(await import_service.get(session, import_id))


@router.put("/{import_id}/mapping", response_model=DataResponse[ImportOut])
async def update_mapping(
    import_id: uuid.UUID, body: MappingUpdate, session: SessionDep
) -> dict[str, Any]:
    return ok(await import_service.remap(session, import_id, body.column_mapping))


@router.post("/{import_id}/confirm", response_model=DataResponse[ImportOut])
async def confirm_import(
    import_id: uuid.UUID, body: ImportConfirm, session: SessionDep
) -> dict[str, Any]:
    return ok(await import_service.confirm(session, import_id, body.consent_attested))
