"""Regenerate the import test fixtures: `python -m app.tests.fixtures.make_import_fixtures`.

Fictitious names (Test Candidate NN) and numbers in the 90000 xxxxx range. Test data only.
"""

from pathlib import Path

from openpyxl import Workbook

HERE = Path(__file__).parent / "imports"
HEADER = ["Candidate Name", "Phone Number", "Job Role", "Email", "Total Experience", "City"]


def _xlsx(path: Path, rows: list[list[object]], header: list[str] = HEADER) -> None:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(header)
    for row in rows:
        ws.append(row)
    wb.save(path)


def main() -> None:
    HERE.mkdir(exist_ok=True)

    lines = [",".join(HEADER)]
    for i in range(1, 6):
        lines.append(
            f"Test Candidate {i:02d},+91 90000 000{i:02d},Backend Developer,"
            f"test{i:02d}@example.com,{i} years,Pune"
        )
    (HERE / "valid_5.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # 10 rows -> 8 valid, 1 duplicate (in file), 1 invalid (plan.md Module A example).
    mixed: list[list[object]] = [
        [f"Test Candidate {i:02d}", f"90000001{i:02d}", "Backend Developer", None, i, "Delhi"]
        for i in range(11, 19)
    ]
    mixed.append(["Test Duplicate", "+91 90000 00111", "Backend Developer", None, 3, "Delhi"])
    mixed.append(["Test Invalid", "12345", "Backend Developer", None, 2, "Delhi"])
    _xlsx(HERE / "mixed_10.xlsx", mixed)

    # Phones stored as Excel numbers (int and float).
    _xlsx(
        HERE / "numeric_phones.xlsx",
        [
            ["Test Numeric 01", 9000000201, "QA Engineer", None, 4, "Noida"],
            ["Test Numeric 02", 9000000202.0, "QA Engineer", None, 5, "Noida"],
            ["Test Numeric 03", 919000000203, "QA Engineer", None, 6, "Noida"],
        ],
    )

    # Phone already mangled into scientific notation as text (CSV round trip through Excel).
    _xlsx(
        HERE / "scientific_phone.xlsx",
        [
            ["Test Scientific 01", "9.00000E+09", "QA Engineer", None, 4, "Noida"],
            ["Test Scientific 02", "9000000302", "QA Engineer", None, 4, "Noida"],
        ],
    )

    cp1252 = "Candidate Name,Phone,Role,City\nTest Jos\xe9 M\xfcller,9000000401,Analyst,Bengaluru\n"
    (HERE / "cp1252.csv").write_bytes(cp1252.encode("cp1252"))

    semicolon = (
        "Name;Mobile No;Designation;Email ID;Exp\n"
        "Test Semi 01;9000000501;Analyst;semi01@example.com;2.5\n"
        "Test Semi 02;9000000502;Analyst;;7 yrs\n"
    )
    (HERE / "semicolon.csv").write_text(semicolon, encoding="utf-8")

    (HERE / "wrong_type.pdf").write_bytes(b"%PDF-1.4\n% test fixture, not a real document\n")


if __name__ == "__main__":
    main()
