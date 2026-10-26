"""Bounded text chunks for an installed speech model's per-call audio token limit."""

import re

MAX_CHARS = 220


def text_chunks(text: str) -> list[str]:
    if not text.strip() or len(text) > 1000:
        raise ValueError("Speech text must contain 1–1000 characters")
    remaining = text.strip()
    chunks = []
    while len(remaining) > MAX_CHARS:
        window = remaining[: MAX_CHARS + 1]
        sentences = list(re.finditer(r"[.!?…][\"'”’)]*\s+", window))
        end = sentences[-1].end() if sentences else window.rfind(" ")
        if end <= 0:
            end = MAX_CHARS
        chunks.append(remaining[:end].strip())
        remaining = remaining[end:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks
