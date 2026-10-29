"""Bounded, inert exports from an existing offline Python data execution."""

import io
import posixpath
import re
import time
import xml.etree.ElementTree as ET
from typing import Literal

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.data_preview import bounded_archive, inspect_xlsx, xml_bytes

ExportName = Literal["chart.png", "result.xlsx", "report.txt"]
FORMATS = {
    "chart.png": ("image", "image/png", "Chart"),
    "result.xlsx": (
        "document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "Excel workbook",
    ),
    "report.txt": ("text", "text/plain", "Text report"),
}


class OutputFiles(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outputs: list[ExportName] = Field(default_factory=list, max_length=3)

    @field_validator("outputs")
    @classmethod
    def unique(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("Generated output filenames must be unique")
        return value


def required_exports(goal):
    """Require current, direct output requests without trusting a model manifest."""
    from app.chat_pages import _instruction_text

    text = re.sub(r"\s+", " ", _instruction_text(goal)).casefold().strip()
    writer = r"(?:create|make|generate|prepare|save|export|write|return|draw|plot|stw[oó]rz|utw[oó]rz|wygeneruj|przygotuj|zapisz|wyeksportuj|eksportuj|narysuj|daj|zwr[oó][ćc])"
    if re.search(r"^(?:do not|don't|nie)\s+" + writer + r"\b", text):
        return []
    modifiers = r"(?:(?:a|an|the|new|real|actual|downloadable|mi|nowy|nową|nowe|prawdziwy|gotowy|plik|file|result|wynik|results|dane|do|to|as|jako|and|oraz|i|w|formacie|format|bar|line)\s+){0,6}"
    has_writer = bool(re.search(r"\b" + writer + r"\b", text))
    result = []
    for name, target in [
        ("chart.png", r"(?:charts?|plots?|wykres\w*)"),
        ("result.xlsx", r"(?:excel\w*|xlsx|workbooks?|spreadsheets?|arkusz\w*(?:\s+excel)?)"),
        ("report.txt", r"(?:text (?:reports?|files?)|raport\w* tekstow\w*|plik(?:u)? tekstow\w*)"),
    ]:
        negative = (
            r"\b(?:without|no|do not|don't|nie|bez)\s+(?:(?:"
            + writer
            + r"|tw[oó]rz|rysuj)\s+)?"
            + target
            + r"\b"
        )
        if re.search(negative, text):
            continue
        if (
            re.search(r"\b" + writer + r"\s+" + modifiers + target + r"\b", text)
            or has_writer
            and re.search(r"\b(?:and|oraz|i)\s+" + modifiers + target + r"\b", text)
            or has_writer
            and re.search(r"(?<![\w/])" + re.escape(name) + r"\b", text)
        ):
            result.append(name)
    return result


def png(data):
    with Image.open(io.BytesIO(data)) as image:
        if (
            image.format != "PNG"
            or getattr(image, "n_frames", 1) != 1
            or not 1 <= image.width <= 4096
            or not 1 <= image.height <= 4096
            or image.width * image.height > 8_000_000
        ):
            raise ValueError("Use a single PNG chart up to 4096 pixels per side and 8 million pixels")
        image.load()
        result = io.BytesIO()
        clean = image.convert("RGBA" if "A" in image.getbands() else "RGB")
        clean.info.clear()
        clean.save(result, format="PNG")
        return result.getvalue()


def xlsx(data, check):
    # A data export is an inert workbook, not an arbitrary Office package.
    allowed = re.compile(
        r"(?:\[Content_Types\]\.xml|_rels/\.rels|docProps/(?:app|core)\.xml|"
        r"xl/(?:workbook|styles|sharedStrings)\.xml|xl/theme/theme\d+\.xml|"
        r"xl/_rels/workbook\.xml\.rels|xl/worksheets/sheet\d+\.xml)"
    )
    types = {
        "application/xml",
        "application/vnd.openxmlformats-package.relationships+xml",
        "application/vnd.openxmlformats-package.core-properties+xml",
        "application/vnd.openxmlformats-officedocument.extended-properties+xml",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml",
        "application/vnd.openxmlformats-officedocument.theme+xml",
    }
    with bounded_archive(data) as archive:
        names = set(archive.namelist())
        if (
            not {"[Content_Types].xml", "_rels/.rels", "xl/workbook.xml", "xl/_rels/workbook.xml.rels"}
            <= names
        ):
            raise ValueError("Use a complete ordinary XLSX workbook package")
        for name in names:
            check()
            if not allowed.fullmatch(name):
                raise ValueError("Workbook exports cannot contain embedded or executable content")
            nodes = ET.iterparse(io.BytesIO(xml_bytes(archive, name)), events=("end",))
            for index, (_, node) in enumerate(nodes):
                if index > 1_000_000:
                    raise ValueError("Workbook export XML contains too many elements")
                if index % 128 == 0:
                    check()
                local = node.tag.rsplit("}", 1)[-1]
                formula_attribute = any(
                    (key.rsplit("}", 1)[-1] in {"type", "t"} and value.strip().casefold() == "formula")
                    or key.rsplit("}", 1)[-1].casefold() in {"formula", "formula1", "formula2"}
                    for key, value in node.attrib.items()
                )
                if (
                    formula_attribute
                    or "formula" in local.casefold()
                    or local
                    in {
                        "f",
                        "definedName",
                        "externalReference",
                        "hyperlink",
                        "oleObject",
                    }
                ):
                    raise ValueError("Workbook exports cannot contain formulas, links or named expressions")
                if local in {"Default", "Override"} and node.get("ContentType") not in types:
                    raise ValueError("Unsupported workbook content type")
                if local == "Relationship":
                    target = node.get("Target", "")
                    base = "xl" if name == "xl/_rels/workbook.xml.rels" else ""
                    resolved = posixpath.normpath(posixpath.join(base, target)).lstrip("/")
                    if node.get("TargetMode", "Internal") != "Internal" or resolved not in names:
                        raise ValueError("Workbook exports require internal package relationships")
                node.clear()
        preview = inspect_xlsx(data, check)
        if any(sheet["formula_count"] for sheet in preview["sheets"]):
            raise ValueError("Workbook exports cannot contain formulas")
    return data


def validate(name, data):
    if name not in FORMATS or not 0 < len(data) <= 4 * 1024 * 1024:
        raise ValueError("Generated exports must be supported, nonempty and at most 4 MiB")
    deadline = time.monotonic() + 5

    def check():
        if time.monotonic() > deadline:
            raise ValueError("Workbook export verification exceeded its time limit")

    if name == "chart.png":
        data = png(data)
    elif name == "result.xlsx":
        data = xlsx(data, check)
    else:
        text = data.decode("utf-8")
        if len(data) > 128 * 1024 or any((ord(c) < 32 and c not in "\n\r\t") or ord(c) == 127 for c in text):
            raise ValueError("Text reports require bounded UTF-8 without control characters")
    if len(data) > 4 * 1024 * 1024:
        raise ValueError("Normalized export exceeds its size limit")
    return data
