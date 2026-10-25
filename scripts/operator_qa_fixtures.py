"""Small synthetic QA inputs, built offline without private data or model execution."""

from __future__ import annotations

import csv
import io
import struct
import zlib
from pathlib import Path

FIXTURE_INSTRUCTIONS = (
    "W folderze Dane-QA masz gotowe, fikcyjne dane. qa-sprzedaz.csv i "
    "qa-sprzedaz.xlsx zawierają te same 6 pozycji: suma kwota_pln = 150, "
    "kategoria A = 65, B = 85. XLSX ma arkusze Sprzedaż QA (dane) i Kontrola QA "
    "(wartości kontrolne, nie kolejne transakcje). W analizie poproś o sumę wszystkich wierszy "
    "i sumy kategorii, potem o wykres i pełny eksport. qa-notatka.txt opisuje "
    "fikcyjne spotkanie: 18 listopada 2026, 42 uczestników. qa-ksztalty.png "
    "ma czerwony kwadrat po lewej i niebieskie koło po prawej na białym tle; "
    "użyj go do Vision, uploadu, Upscale i jednorazowych testów Library. "
    "qa-uszkodzony.xlsx celowo nie jest arkuszem: oczekuj jawnego błędu, "
    "nie obliczeń. To dane wejściowe, nie dowody zaliczenia testów. "
    "Do jakości Edit/Recompose użyj neutralnego zdjęcia wygenerowanego "
    "w IMAGE-001/002; do awatara własnego portretu i mowy z AUDIO-001. "
    "Obraz kształtów nie zastępuje testu twarzy, tożsamości ani synchronizacji ust."
)


def fixture_bytes() -> dict[Path, bytes]:
    """Return app-independent files; importing this module creates nothing."""
    from openpyxl import Workbook

    values = [
        ["id", "produkt", "kategoria", "kwota_pln"],
        [1, "Notes", "A", 10],
        [2, "Kubek", "B", 20],
        [3, "Zeszyt", "A", 30],
        [4, "Torba", "B", 40],
        [5, "Długopis", "A", 25],
        [6, "Podkładka", "B", 25],
    ]
    table = io.StringIO(newline="")
    csv.writer(table).writerows(values)
    workbook = Workbook()
    page = workbook.active
    page.title = "Sprzedaż QA"
    for row in values:
        page.append(row)
    page.freeze_panes = "A2"
    page.auto_filter.ref = page.dimensions
    for name, width in (("A", 8), ("B", 22), ("C", 14), ("D", 16)):
        page.column_dimensions[name].width = width
    control = workbook.create_sheet("Kontrola QA")
    for row in (("miara", "wartość"), ("wiersze", 6), ("suma", 150), ("A", 65), ("B", 85)):
        control.append(row)
    control.column_dimensions["A"].width = 20
    control.column_dimensions["B"].width = 16
    stream = io.BytesIO()
    workbook.save(stream)
    return {
        Path("Dane-QA/qa-sprzedaz.csv"): table.getvalue().encode("utf-8-sig"),
        Path("Dane-QA/qa-sprzedaz.xlsx"): stream.getvalue(),
        Path("Dane-QA/qa-notatka.txt"): (
            "Fikcyjne dane do testów AI Station.\n"
            "Spotkanie projektu Latarnia odbędzie się 18 listopada 2026.\n"
            "Na spotkanie zapisano 42 uczestników.\n"
        ).encode(),
        Path("Dane-QA/qa-ksztalty.png"): shapes_png(),
        Path("Dane-QA/qa-uszkodzony.xlsx"): (
            "CELOWO USZKODZONY PLIK QA. To tekst, a nie arkusz XLSX.\n"
        ).encode(),
    }


def shapes_png() -> bytes:
    """A neutral 384x256 RGB fixture with unambiguous shapes and no text."""
    width, height = 384, 256
    scanlines = bytearray()
    for y in range(height):
        scanlines.append(0)  # PNG filter: None.
        for x in range(width):
            color = (255, 255, 255)
            if 40 <= x < 152 and 72 <= y < 184:
                color = (220, 30, 30)
            elif (x - 272) ** 2 + (y - 128) ** 2 <= 56**2:
                color = (30, 70, 220)
            scanlines.extend(color)

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(scanlines))
        + chunk(b"IEND", b"")
    )
