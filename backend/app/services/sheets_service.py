"""Google Sheets client (plan.md Module H, phase-07 P7-T6 to P7-T8). docs/google-sheets.md

Official `google-api-python-client` + `google-auth` with a service account (scope
`spreadsheets` only; the account can open only the spreadsheet shared with it). The client is
blocking, so every call runs in a thread. Operations, batched so one sync of many candidates
costs a few requests (one service account gets ~60 requests a minute):

- read the header and column A (one `values.batchGet`)
- update existing rows (one `values.batchUpdate`, `A{row}:W{row}` each)
- append new rows (one `values.append`, INSERT_ROWS)
- on an empty sheet only: write the header and its one-way-sync note

All writes use valueInputOption=RAW. Rows are found by Candidate ID on every sync, so sorting or
inserting rows by hand is harmless. A header that doesn't match stops all writes (someone has
edited the sheet's layout). Credentials are read from a file path and never logged.
"""

import asyncio
import json
import socket
from dataclasses import dataclass
from typing import Any

from app.config import Settings
from app.services.sheet_mapping import HEADERS, LAST_COLUMN, Cell
from app.utils.log import get_logger

logger = get_logger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
HEADER_NOTE = "Written by the recruitment system. Manual edits will be overwritten."
TRANSIENT_HTTP = frozenset({408, 429, 500, 502, 503, 504})


class SheetsError(Exception):
    """A Sheets failure. `transient` errors are retried with backoff; the others mean the
    configuration or the sheet needs fixing (integration status `error`)."""

    def __init__(self, message: str, *, transient: bool, status: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.transient = transient
        self.status = status


class HeaderMismatchError(SheetsError):
    def __init__(self, found: list[str]) -> None:
        super().__init__(
            "The sheet's header row doesn't match the expected columns, so nothing was written. "
            "Restore the header (or point GOOGLE_SHEET_TAB to an empty tab).",
            transient=False,
        )
        self.found = found


def _reason(exc: Any) -> str:
    try:
        detail = json.loads(exc.content.decode())["error"]["message"]
        return str(detail)
    except Exception:
        return str(getattr(exc, "reason", "") or exc.__class__.__name__)


def classify(exc: BaseException, *, service_email: str | None = None) -> SheetsError:
    """Map a Google client / network exception to a SheetsError with a message for recruiters."""
    from google.auth import exceptions as auth_exc
    from googleapiclient.errors import HttpError

    if isinstance(exc, SheetsError):
        return exc
    if isinstance(exc, HttpError):
        status = int(exc.resp.status)
        reason = _reason(exc)
        if status in TRANSIENT_HTTP:
            return SheetsError(
                f"Google Sheets is busy or unavailable ({status}): {reason}",
                transient=True,
                status=status,
            )
        if status == 403:
            who = f" ({service_email})" if service_email else ""
            return SheetsError(
                f"No permission to edit the spreadsheet. Share it with the service account{who} "
                f"as Editor. Google said: {reason}",
                transient=False,
                status=status,
            )
        if status == 404:
            return SheetsError(
                "Spreadsheet not found: check GOOGLE_SHEET_ID.", transient=False, status=status
            )
        return SheetsError(
            f"Google Sheets rejected the request ({status}): {reason}",
            transient=False,
            status=status,
        )
    if isinstance(exc, auth_exc.RefreshError):
        return SheetsError(f"The service account key was refused by Google: {exc}", transient=False)
    if isinstance(exc, auth_exc.TransportError | TimeoutError | socket.timeout | OSError):
        return SheetsError(f"Network error talking to Google: {exc!r}", transient=True)
    try:
        import httplib2

        if isinstance(exc, httplib2.HttpLib2Error):
            return SheetsError(f"Network error talking to Google: {exc!r}", transient=True)
    except ImportError:  # pragma: no cover
        pass
    return SheetsError(f"Unexpected Sheets error: {exc!r}", transient=True)


def _is_missing_tab(exc: BaseException) -> bool:
    from googleapiclient.errors import HttpError

    return (
        isinstance(exc, HttpError)
        and int(exc.resp.status) == 400
        and "Unable to parse range" in _reason(exc)
    )


def _normalize_header(row: list[Any]) -> list[str]:
    cells = [str(c).strip() for c in row]
    while cells and not cells[-1]:
        cells.pop()
    return cells


class SheetsClient:
    """Blocking client for one tab of one spreadsheet. Use from a thread only, one call at a
    time (httplib2 isn't thread-safe; callers hold the Sheets lock)."""

    def __init__(
        self, credentials_path: str, spreadsheet_id: str, tab: str, *, timeout_s: float = 20.0
    ) -> None:
        import google_auth_httplib2
        import httplib2
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        try:
            creds = service_account.Credentials.from_service_account_file(  # type: ignore[no-untyped-call]
                credentials_path, scopes=SCOPES
            )
        except FileNotFoundError:
            raise SheetsError(
                "Service account key file not found at GOOGLE_SERVICE_ACCOUNT_JSON.",
                transient=False,
            ) from None
        except OSError as exc:  # e.g. permissions: the container user can't read the file
            raise SheetsError(
                f"Service account key file can't be read ({type(exc).__name__}): check its "
                "permissions (the container runs as uid 1000).",
                transient=False,
            ) from None
        except (ValueError, KeyError) as exc:
            raise SheetsError(
                f"Service account key file is not valid: {type(exc).__name__}", transient=False
            ) from None
        self.service_email: str | None = getattr(creds, "service_account_email", None)
        http = google_auth_httplib2.AuthorizedHttp(creds, http=httplib2.Http(timeout=timeout_s))
        self._sheets = build(
            "sheets", "v4", http=http, cache_discovery=False, static_discovery=True
        )
        self.spreadsheet_id = spreadsheet_id
        self.tab = tab

    def _range(self, cells: str) -> str:
        escaped = self.tab.replace("'", "''")
        return f"'{escaped}'!{cells}"

    def _run(self, request: Any) -> Any:
        try:
            return request.execute(num_retries=0)
        except Exception as exc:
            raise classify(exc, service_email=self.service_email) from exc

    # --- the operations ---------------------------------------------------------------------

    def read_header_and_ids(self) -> tuple[list[str], list[str]]:
        """Header row and column A (row 2 down). A missing tab is created (empty)."""
        request = (
            self._sheets.spreadsheets()
            .values()
            .batchGet(
                spreadsheetId=self.spreadsheet_id,
                ranges=[self._range(f"A1:{LAST_COLUMN}1"), self._range("A2:A")],
                majorDimension="ROWS",
            )
        )
        try:
            body = request.execute(num_retries=0)
        except Exception as exc:
            if _is_missing_tab(exc):
                self._add_tab()
                return [], []
            raise classify(exc, service_email=self.service_email) from exc
        ranges = body.get("valueRanges", [])
        header_rows = ranges[0].get("values", []) if ranges else []
        id_rows = ranges[1].get("values", []) if len(ranges) > 1 else []
        header = _normalize_header(header_rows[0]) if header_rows else []
        ids = [str(r[0]).strip() if r else "" for r in id_rows]
        return header, ids

    def write_header(self) -> None:
        self._run(
            self._sheets.spreadsheets()
            .values()
            .update(
                spreadsheetId=self.spreadsheet_id,
                range=self._range(f"A1:{LAST_COLUMN}1"),
                valueInputOption="RAW",
                body={"values": [HEADERS]},
            )
        )
        try:
            self._add_header_note()
        except SheetsError as exc:  # the note is a courtesy; never block a sync on it
            logger.warning("sheets_header_note_failed", error=exc.message)

    def update_rows(self, rows: list[tuple[int, list[Cell]]]) -> None:
        if not rows:
            return
        data = [
            {"range": self._range(f"A{n}:{LAST_COLUMN}{n}"), "values": [row]} for n, row in rows
        ]
        self._run(
            self._sheets.spreadsheets()
            .values()
            .batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={"valueInputOption": "RAW", "data": data},
            )
        )

    def append_rows(self, rows: list[list[Cell]]) -> None:
        if not rows:
            return
        self._run(
            self._sheets.spreadsheets()
            .values()
            .append(
                spreadsheetId=self.spreadsheet_id,
                range=self._range("A1"),
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": rows},
            )
        )

    # --- setup helpers (first sync on an empty spreadsheet) ---------------------------------

    def _sheet_gid(self) -> int | None:
        meta = self._run(
            self._sheets.spreadsheets().get(
                spreadsheetId=self.spreadsheet_id, fields="sheets.properties(sheetId,title)"
            )
        )
        for sheet in meta.get("sheets", []):
            props = sheet.get("properties", {})
            if props.get("title") == self.tab:
                return int(props["sheetId"])
        return None

    def _add_tab(self) -> None:
        self._run(
            self._sheets.spreadsheets().batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={"requests": [{"addSheet": {"properties": {"title": self.tab}}}]},
            )
        )
        logger.info("sheets_tab_created", tab=self.tab)

    def _add_header_note(self) -> None:
        gid = self._sheet_gid()
        if gid is None:
            return
        self._run(
            self._sheets.spreadsheets().batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={
                    "requests": [
                        {
                            "updateCells": {
                                "range": {
                                    "sheetId": gid,
                                    "startRowIndex": 0,
                                    "endRowIndex": 1,
                                    "startColumnIndex": 0,
                                    "endColumnIndex": 1,
                                },
                                "rows": [{"values": [{"note": HEADER_NOTE}]}],
                                "fields": "note",
                            }
                        },
                        {
                            "updateSheetProperties": {
                                "properties": {
                                    "sheetId": gid,
                                    "gridProperties": {"frozenRowCount": 1},
                                },
                                "fields": "gridProperties.frozenRowCount",
                            }
                        },
                    ]
                },
            )
        )


# --- Upsert (shared by the worker and the status check) -------------------------------------


@dataclass
class UpsertResult:
    updated: list[str]
    appended: list[str]


@dataclass
class SheetCheck:
    reachable: bool
    header: str  # ok | empty | mismatch | unknown
    message: str | None = None
    service_email: str | None = None


def upsert_blocking(client: SheetsClient, rows: dict[str, list[Cell]]) -> UpsertResult:
    """Insert or update one row per candidate id. Call under the Sheets lock."""
    header, ids = client.read_header_and_ids()
    if not header:
        client.write_header()
        ids = []
    elif header != HEADERS:
        raise HeaderMismatchError(header)
    index: dict[str, int] = {}
    for offset, cid in enumerate(ids):
        if cid and cid not in index:
            index[cid] = offset + 2  # row 1 is the header
    updates = [(index[cid], row) for cid, row in rows.items() if cid in index]
    appends = [(cid, row) for cid, row in rows.items() if cid not in index]
    client.update_rows(updates)
    client.append_rows([row for _, row in appends])
    return UpsertResult(
        updated=[cid for cid in rows if cid in index], appended=[cid for cid, _ in appends]
    )


def check_blocking(client: SheetsClient) -> SheetCheck:
    try:
        header, _ = client.read_header_and_ids()
    except SheetsError as exc:
        return SheetCheck(False, "unknown", exc.message, client.service_email)
    if not header:
        return SheetCheck(True, "empty", None, client.service_email)
    if header != HEADERS:
        return SheetCheck(
            True, "mismatch", HeaderMismatchError(header).message, client.service_email
        )
    return SheetCheck(True, "ok", None, client.service_email)


class SheetsService:
    """Async wrapper: one blocking client per process, calls run in a thread."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: SheetsClient | None = None
        # One call at a time: the client (httplib2) isn't thread-safe. Two status checks in
        # parallel threads on it hung until the 20 s timeout (Settings page, 2026-11-19).
        self.lock = asyncio.Lock()

    @property
    def configured(self) -> bool:
        return self._settings.sheets_configured

    def configure(self, settings: Settings) -> "SheetsService":
        """Use these (effective) settings; the client is rebuilt when the sheet changed (an
        admin picked another sheet on the Settings page)."""
        old = self._settings
        if (old.google_sheet_id, old.google_sheet_tab, old.google_service_account_json) != (
            settings.google_sheet_id,
            settings.google_sheet_tab,
            settings.google_service_account_json,
        ):
            self._client = None
        self._settings = settings
        return self

    def _get_client(self) -> SheetsClient:
        if self._client is None:
            s = self._settings
            assert s.google_service_account_json and s.google_sheet_id
            self._client = SheetsClient(
                s.google_service_account_json,
                s.google_sheet_id,
                s.google_sheet_tab,
                timeout_s=s.google_sheets_timeout_s,
            )
        return self._client

    async def upsert(self, rows: dict[str, list[Cell]]) -> UpsertResult:
        async with self.lock:
            client = await asyncio.to_thread(self._get_client)
            return await asyncio.to_thread(upsert_blocking, client, rows)

    async def check(self) -> SheetCheck:
        async with self.lock:
            return await self.check_unlocked()

    async def check_unlocked(self) -> SheetCheck:
        """`check` for a caller that already holds `lock`."""
        try:
            client = await asyncio.to_thread(self._get_client)
        except SheetsError as exc:
            return SheetCheck(False, "unknown", exc.message)
        return await asyncio.to_thread(check_blocking, client)
