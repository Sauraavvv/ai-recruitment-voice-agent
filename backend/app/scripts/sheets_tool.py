"""Google Sheets operator tool (phase-07). Runs in the backend container:

  python -m app.scripts.sheets_tool check      service account, reachability, header
  python -m app.scripts.sheets_tool sync       drain the outbox now (what the worker does)
  python -m app.scripts.sheets_tool backfill   queue every candidate (first fill of a new sheet)
  python -m app.scripts.sheets_tool compare    P7-AC4: every sheet row vs the database

Never prints credentials.
"""

import argparse
import asyncio
import sys
from typing import Any

from sqlalchemy import select

from app.config import Settings, get_settings
from app.database.connection import dispose_engine, get_sessionmaker, init_engine
from app.database.models import Candidate
from app.services import settings_service, sync_service
from app.services.sheet_mapping import HEADERS, LAST_COLUMN
from app.services.sheets_service import SheetsService
from app.utils.redis import close_redis, get_redis, init_redis


def _cell(value: Any) -> str:
    """Compare as text: the sheet returns 12 for 12.0 and '' for a missing value."""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return "" if value is None else str(value)


async def _compare(service: SheetsService, settings: Settings) -> int:
    client = await asyncio.to_thread(service._get_client)
    body = await asyncio.to_thread(
        client._sheets.spreadsheets()
        .values()
        .get(
            spreadsheetId=client.spreadsheet_id,
            range=client._range(f"A1:{LAST_COLUMN}"),
            valueRenderOption="UNFORMATTED_VALUE",
        )
        .execute
    )
    values = body.get("values", [])
    if not values or [str(c) for c in values[0]] != HEADERS:
        print("Header row missing or different")
        return 1
    sheet_rows = {str(r[0]): r for r in values[1:] if r}
    async with get_sessionmaker()() as session:
        # Active candidates must all be there; a soft-deleted one keeps its row if it had one
        # (backfill never adds it)
        rows = (await session.execute(select(Candidate.id, Candidate.deleted_at))).all()
        ids = [cid for cid, deleted in rows if deleted is None or str(cid) in sheet_rows]
        expected = await sync_service.build_rows(session, ids, settings)
        deleted = {str(cid) for cid, d in rows if d is not None}
    problems = 0
    for cid, row in expected.items():
        got = sheet_rows.get(cid)
        if got is None:
            print(f"MISSING  {cid}")
            problems += 1
            continue
        got = list(got) + [""] * (len(HEADERS) - len(got))
        diffs = [
            f"{HEADERS[i]}: sheet={_cell(got[i])!r} db={_cell(row[i])!r}"
            for i in range(len(HEADERS))
            if _cell(got[i]) != _cell(row[i])
        ]
        if diffs:
            problems += 1
            print(f"DIFFERS  {cid}\n    " + "\n    ".join(diffs))
    extra = set(sheet_rows) - set(expected) - deleted
    for cid in extra:
        print(f"EXTRA    {cid} (in the sheet, not in the database)")
    duplicates = len(values) - 1 - len(sheet_rows)
    print(
        f"{len(expected)} candidates, {len(sheet_rows)} sheet rows, {problems} problems, "
        f"{len(extra)} extra, {duplicates} duplicate or blank rows"
    )
    return 1 if problems or extra or duplicates else 0


async def main(command: str) -> int:
    settings = get_settings()
    init_engine(settings.database_url.get_secret_value())
    init_redis(settings.redis_url.get_secret_value())
    # the sheet chosen on the Settings page, else GOOGLE_SHEET_ID
    settings = await settings_service.effective_new_session(settings)
    if not settings.sheets_configured:
        print(
            "Set GOOGLE_SERVICE_ACCOUNT_JSON (path) and a sheet (Settings page or GOOGLE_SHEET_ID)"
        )
        await close_redis()
        await dispose_engine()
        return 2
    service = SheetsService(settings)
    try:
        if command == "check":
            result = await service.check()
            print(f"service account: {result.service_email}")
            print(f"spreadsheet:     {settings.google_sheet_id} (tab {settings.google_sheet_tab})")
            print(f"reachable:       {result.reachable}")
            print(f"header:          {result.header}")
            if result.message:
                print(f"message:         {result.message}")
            return 0 if result.reachable and result.header != "mismatch" else 1
        if command == "sync":
            outcome = await sync_service.drain(get_sessionmaker(), service, get_redis(), settings)
            print(f"{outcome.outcome}: {outcome.synced} synced, {outcome.failed} failed")
            return 0 if outcome.outcome in ("done", "idle", "more") else 1
        if command == "backfill":
            async with get_sessionmaker()() as session:
                queued = await sync_service.backfill(session)
            print(f"queued {queued} candidates; running the sync")
            outcome = await sync_service.drain(get_sessionmaker(), service, get_redis(), settings)
            print(f"{outcome.outcome}: {outcome.synced} synced, {outcome.failed} failed")
            return 0
        if command == "compare":
            return await _compare(service, settings)
        return 2
    finally:
        await close_redis()
        await dispose_engine()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("command", choices=["check", "sync", "backfill", "compare"])
    sys.exit(asyncio.run(main(parser.parse_args().command)))
