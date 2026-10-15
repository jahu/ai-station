"""Bounded read-only CSV/XLSX observations. Never evaluates formulas or macros."""

import csv
import io
import re
import struct
import xml.etree.ElementTree as ET
import zipfile
from pathlib import PurePosixPath

MAX_ROWS = 100_000
MAX_COLUMNS = 128
MAX_CELLS = 1_000_000
PREVIEW_ROWS = 20
PREVIEW_COLUMNS = 20
MAX_XML = 8 * 1024 * 1024
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
RID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


def inspect_csv(data, check):
    text = data.decode("utf-8-sig")
    if "\0" in text:
        raise ValueError("CSV must contain UTF-8 text without null bytes")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows, columns, preview, cells = 0, 0, [], 0

    def lines():
        for line in io.StringIO(text, newline=""):
            if len(line) > 65536:
                raise ValueError("CSV physical lines must be at most 65,536 characters")
            yield line

    for row in csv.reader(lines(), dialect, strict=True):
        check()
        if not row:
            continue
        rows += 1
        columns = max(columns, len(row))
        cells += len(row)
        if rows > MAX_ROWS or columns > MAX_COLUMNS or cells > MAX_CELLS:
            raise ValueError("Data exceeds 100,000 rows, 128 columns or 1,000,000 cells")
        if len(preview) < PREVIEW_ROWS:
            preview.append([cell[:200] for cell in row[:PREVIEW_COLUMNS]])
    return {
        "format": "csv",
        "sheets": [
            {
                "name": "CSV",
                "row_count": rows,
                "column_count": columns,
                "preview": preview,
                "formula_count": 0,
            }
        ],
        "preview_limits": {"rows": PREVIEW_ROWS, "columns": PREVIEW_COLUMNS, "cell_characters": 200},
    }


def xml_bytes(archive, name, *, limit=MAX_XML):
    data = archive.read(name) if archive.getinfo(name).file_size <= limit else None
    if (
        data is None
        or len(data) > limit
        or b"\0" in data
        or b"<!DOCTYPE" in data.upper()
        or b"<!ENTITY" in data.upper()
    ):
        raise ValueError("Oversized XML, entities or unsupported XML encoding in spreadsheet")
    return data


def bounded_archive(data):
    # Bound central-directory allocation before ZipFile builds its entry objects.
    end = data.rfind(b"PK\x05\x06", max(0, len(data) - 65557))
    if end < 0 or len(data) - end < 22:
        raise ValueError("Use an ordinary unencrypted XLSX workbook")
    _, disk, directory_disk, disk_count, count, size, offset, comment = struct.unpack(
        "<4s4H2LH", data[end : end + 22]
    )
    if (
        disk
        or directory_disk
        or disk_count != count
        or not 0 < count <= 128
        or size > 65536
        or offset + size != end
        or end + 22 + comment != len(data)
    ):
        raise ValueError("Spreadsheet archive exceeds the supported directory limits")
    archive = zipfile.ZipFile(io.BytesIO(data))
    try:
        entries = archive.infolist()
        if len(entries) != count or len({entry.filename for entry in entries}) != len(entries):
            raise ValueError("Duplicate or inconsistent spreadsheet archive entries")
        total = 0
        for entry in entries:
            parts = PurePosixPath(entry.filename).parts
            if (
                not parts
                or entry.filename.startswith("/")
                or ".." in parts
                or "\\" in entry.filename
                or len(entry.filename) > 240
                or entry.flag_bits & 1
                or entry.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
                or entry.file_size > MAX_XML
                or "vbaproject" in entry.filename.lower()
            ):
                raise ValueError("Unsafe, encrypted, macro-bearing or oversized spreadsheet member")
            total += entry.file_size
        if total > 32 * 1024 * 1024:
            raise ValueError("Expanded spreadsheet exceeds 32 MiB")
    except Exception:
        archive.close()
        raise
    return archive


def events(data, check, expected_root):
    for index, (event, element) in enumerate(ET.iterparse(io.BytesIO(data), events=("start", "end"))):
        if index == 0 and element.tag != expected_root:
            raise ValueError("Unsupported spreadsheet XML root")
        if index > 1_000_000:
            raise ValueError("Spreadsheet XML contains too many elements")
        if index % 128 == 0:
            check()
        if event == "end":
            yield element


def inspect_xlsx(data, check):
    with bounded_archive(data) as archive:
        workbook = ET.fromstring(xml_bytes(archive, "xl/workbook.xml", limit=512 * 1024))
        relations = ET.fromstring(xml_bytes(archive, "xl/_rels/workbook.xml.rels", limit=512 * 1024))
        if workbook.tag != NS + "workbook":
            raise ValueError("Unsupported spreadsheet workbook XML root")
        targets = {r.attrib.get("Id"): r for r in relations}
        sheets = workbook.findall(f"{NS}sheets/{NS}sheet")
        if not 1 <= len(sheets) <= 8:
            raise ValueError("Choose a workbook with 1 to 8 sheets")
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            for element in events(xml_bytes(archive, "xl/sharedStrings.xml"), check, NS + "sst"):
                if element.tag == NS + "si":
                    if len(strings) >= 100_000:
                        raise ValueError("Spreadsheet contains too many shared strings")
                    strings.append("".join(node.text or "" for node in element.iter(NS + "t"))[:200])
                    element.clear()
        result, cells = [], 0
        for sheet in sheets:
            relation = targets.get(sheet.attrib.get(RID))
            if relation is None or relation.attrib.get("TargetMode") == "External":
                raise ValueError("Spreadsheet sheet references must be internal")
            target = relation.attrib.get("Target", "")
            path = target.lstrip("/") if target.startswith("/xl/") else "xl/" + target
            if not path.startswith("xl/worksheets/") or ".." in PurePosixPath(path).parts or "\\" in path:
                raise ValueError("Unsupported spreadsheet sheet path")
            preview, rows, columns, formulas = [], 0, 0, 0
            row_numbers = []
            for element in events(xml_bytes(archive, path), check, NS + "worksheet"):
                if element.tag != NS + "row":
                    continue
                number = int(element.attrib.get("r", rows + 1))
                if not rows < number <= MAX_ROWS:
                    raise ValueError("Spreadsheet exceeds row limits or has unordered rows")
                rows = number
                values = []
                for cell in element.findall(NS + "c"):
                    cells += 1
                    reference = re.fullmatch(r"([A-Z]{1,3})([1-9][0-9]*)", cell.attrib.get("r", ""))
                    if reference is None or int(reference[2]) != number:
                        raise ValueError("Invalid spreadsheet cell reference")
                    col = 0
                    for letter in reference[1]:
                        col = col * 26 + ord(letter) - 64
                    if not 1 <= col <= MAX_COLUMNS or cells > MAX_CELLS:
                        raise ValueError("Spreadsheet exceeds column or cell limits")
                    columns = max(columns, col)
                    formula = cell.find(NS + "f") is not None
                    formulas += int(formula)
                    if len(preview) < PREVIEW_ROWS and col <= PREVIEW_COLUMNS:
                        if len(values) >= col:
                            raise ValueError("Spreadsheet cells must be ordered and unique")
                        values += [""] * (col - len(values))
                        value = cell.findtext(NS + "v", default="")
                        if formula:
                            value = "[Formula — not evaluated]"
                        elif cell.attrib.get("t") == "s":
                            idx = int(value)
                            if not 0 <= idx < len(strings):
                                raise ValueError("Invalid spreadsheet shared string")
                            value = strings[idx]
                        elif cell.attrib.get("t") == "inlineStr":
                            inline = cell.find(NS + "is")
                            value = (
                                "".join(node.text or "" for node in inline.iter(NS + "t"))
                                if inline is not None
                                else ""
                            )
                        elif cell.attrib.get("t") == "b":
                            value = "true" if value == "1" else "false"
                        values[col - 1] = value[:200]
                if len(preview) < PREVIEW_ROWS:
                    preview.append(values)
                    row_numbers.append(number)
                element.clear()
            result.append(
                {
                    "name": sheet.attrib.get("name", "Sheet")[:200],
                    "row_count": rows,
                    "column_count": columns,
                    "formula_count": formulas,
                    "preview": preview,
                    "preview_row_numbers": row_numbers,
                }
            )
        return {
            "format": "xlsx",
            "sheets": result,
            "preview_limits": {"rows": PREVIEW_ROWS, "columns": PREVIEW_COLUMNS, "cell_characters": 200},
            "note": "Formulas are not evaluated. Dates retain their stored numeric values.",
        }
