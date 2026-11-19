"""In-memory stand-in for one Google Sheets tab (test-only). Implements the SheetsClient
operations used by `upsert_blocking`, plus helpers to sort rows or fail like the real API."""

from typing import Any

from app.services.sheet_mapping import Cell
from app.services.sheets_service import SheetsError, UpsertResult, upsert_blocking


class FakeSheetClient:
    def __init__(self, rows: list[list[Any]] | None = None) -> None:
        self.rows: list[list[Any]] = [list(r) for r in rows or []]  # row 1 = rows[0]
        self.service_email = "sync@test-project.iam.gserviceaccount.com"
        self.fail_with: SheetsError | None = None
        self.calls: list[str] = []
        self.header_writes = 0

    def _check(self, name: str) -> None:
        self.calls.append(name)
        if self.fail_with is not None:
            raise self.fail_with

    def read_header_and_ids(self) -> tuple[list[str], list[str]]:
        self._check("read")
        header = [str(c) for c in self.rows[0]] if self.rows else []
        while header and not header[-1]:
            header.pop()
        return header, [str(r[0]) if r else "" for r in self.rows[1:]]

    def write_header(self) -> None:
        from app.services.sheet_mapping import HEADERS

        self._check("write_header")
        self.header_writes += 1
        if self.rows:
            self.rows[0] = list(HEADERS)
        else:
            self.rows.append(list(HEADERS))

    def update_rows(self, rows: list[tuple[int, list[Cell]]]) -> None:
        if not rows:
            return
        self._check("update")
        for number, row in rows:
            self.rows[number - 1] = list(row)

    def append_rows(self, rows: list[list[Cell]]) -> None:
        if not rows:
            return
        self._check("append")
        self.rows.extend(list(r) for r in rows)

    # --- test helpers -------------------------------------------------------------------------

    def data(self) -> list[list[Any]]:
        return self.rows[1:]

    def row_for(self, candidate_id: str) -> list[Any]:
        matches = [r for r in self.data() if r and r[0] == candidate_id]
        assert len(matches) == 1, f"{len(matches)} rows for {candidate_id}"
        return matches[0]

    def sort_by(self, column: int, *, reverse: bool = False) -> None:
        self.rows[1:] = sorted(self.data(), key=lambda r: str(r[column]), reverse=reverse)


class FakeSheetWriter:
    """The async writer the drain uses, over a FakeSheetClient."""

    def __init__(self, client: FakeSheetClient | None = None) -> None:
        self.client = client or FakeSheetClient()

    async def upsert(self, rows: dict[str, list[Cell]]) -> UpsertResult:
        return upsert_blocking(self.client, rows)  # type: ignore[arg-type]
