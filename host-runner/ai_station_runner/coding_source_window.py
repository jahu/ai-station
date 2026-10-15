"""Bound line-window observations independently of full local edit snapshots."""

MAX_WINDOW_BYTES = 16000


def source_window(item, *, start_line=1, max_lines=100):
    if (
        type(start_line) is not int
        or start_line < 1
        or type(max_lines) is not int
        or not 1 <= max_lines <= 200
    ):
        raise ValueError("Source windows require positive start_line and 1..200 max_lines")
    content = item["content"]
    if content is None:
        return {"path": item["path"], "content": None}
    lines = content.splitlines(keepends=True)
    available = lines[start_line - 1 : start_line - 1 + max_lines]
    chunks, size, clipped = [], 0, False
    for line in available:
        data = line.encode()
        remaining = MAX_WINDOW_BYTES - size
        if remaining == 0:
            break
        if len(data) > remaining:
            chunks.append(data[:remaining].decode("utf-8", errors="ignore"))
            clipped = True
            break
        chunks.append(line)
        size += len(data)
    end = min(len(lines), start_line - 1 + len(chunks))
    return {
        "path": item["path"],
        "content": "".join(chunks),
        "start_line": start_line,
        "next_line": end + 1 if end < len(lines) else None,
        "total_lines": len(lines),
        "total_bytes": len(content.encode()),
        "truncated": start_line > 1 or end < len(lines) or clipped,
        "last_line_truncated": clipped,
    }
