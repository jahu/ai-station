"""Fixed resource-bounded reader process. No paths, commands, credentials or network."""

import ctypes
import io
import json
import os
import resource
import signal
import sys

from app.document_schema import MAX_CAPTURE_BYTES, MAX_PDF_BYTES


def main():
    parent = os.getppid()
    if sys.platform == "linux":
        if ctypes.CDLL(None).prctl(1, signal.SIGKILL, 0, 0, 0) != 0 or os.getppid() != parent or parent == 1:
            return 2
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024**2, 512 * 1024**2))
    resource.setrlimit(resource.RLIMIT_CPU, (6, 6))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    data = sys.stdin.buffer.read(MAX_PDF_BYTES + 1)
    try:
        if not data or len(data) > MAX_PDF_BYTES:
            raise ValueError("Document exceeds the reader input limit")
        pages = 1
        if sys.argv[1:] == ["pdf"]:
            from pypdf import PdfReader

            if not data.startswith(b"%PDF"):
                raise ValueError("Invalid PDF header")
            reader = PdfReader(io.BytesIO(data), strict=False)
            if reader.is_encrypted:
                raise ValueError("Encrypted PDFs are not supported")
            pages = len(reader.pages)
            if not 1 <= pages <= 64:
                raise ValueError("Choose a PDF with 1 to 64 pages")
            parts, total = [], 0
            truncated = False
            for page in reader.pages:
                encoded = (page.extract_text() or "").encode("utf-8")
                remaining = MAX_CAPTURE_BYTES - total
                parts.append(encoded[:remaining].decode("utf-8", errors="ignore"))
                total += min(len(encoded), remaining)
                if len(encoded) > remaining:
                    truncated = True
                    break
            text = "\n".join(parts)
        elif sys.argv[1:] == ["text"]:
            text = data.decode("utf-8-sig")
            if "\0" in text:
                raise ValueError("Choose UTF-8 text without null bytes")
            truncated = len(text.encode("utf-8")) > MAX_CAPTURE_BYTES
        else:
            raise ValueError("Unknown document format")
        if not text.strip():
            raise ValueError("No extractable text; scanned PDFs require a separate OCR capability")
        encoded = text.encode("utf-8")
        text = encoded[:MAX_CAPTURE_BYTES].decode("utf-8", errors="ignore")
        result = {
            "text": text,
            "page_count": pages,
            "truncated": truncated or len(encoded) > MAX_CAPTURE_BYTES,
        }
        json.dump(result, sys.stdout, ensure_ascii=False)
        return 0
    except ValueError as exc:
        # Our static diagnostics only; parser exceptions use the fixed fallback.
        allowed = {
            "Document exceeds the reader input limit",
            "Invalid PDF header",
            "Encrypted PDFs are not supported",
            "Choose a PDF with 1 to 64 pages",
            "Choose UTF-8 text without null bytes",
            "Unknown document format",
            "No extractable text; scanned PDFs require a separate OCR capability",
        }
        message = (
            str(exc) if type(exc) is ValueError and str(exc) in allowed else "Invalid or unreadable document"
        )
        json.dump({"error": message}, sys.stdout)
        return 2
    except Exception:
        json.dump({"error": "Invalid, unreadable or resource-limited document"}, sys.stdout)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
