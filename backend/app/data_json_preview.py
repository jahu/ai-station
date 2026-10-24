"""Bounded JSON data inspection; complete original bytes remain the Python input."""

import json
import math

from app.data_preview import PREVIEW_COLUMNS, PREVIEW_ROWS

MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_JSON_DEPTH = 32
MAX_JSON_NODES = 100_000


def inspect_json(data, check):
    if not 0 < len(data) <= MAX_JSON_BYTES:
        raise ValueError("JSON inputs must contain 1 byte to 4 MiB")
    pairs_seen = objects_seen = 0

    def pairs(items):
        nonlocal pairs_seen, objects_seen
        check()
        pairs_seen += len(items)
        objects_seen += 1
        if max(pairs_seen, objects_seen) > MAX_JSON_NODES:
            raise ValueError("JSON contains too many values")
        result = {}
        for key, value in items:
            key.encode("utf-8")
            if key in result:
                raise ValueError("JSON object keys must be unique")
            result[key] = value
        return result

    def number(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("JSON numbers must be finite")
        return result

    def constant(value):
        raise ValueError("JSON numbers must be finite")

    check()
    try:
        value = json.loads(
            data.decode("utf-8-sig"),
            object_pairs_hook=pairs,
            parse_float=number,
            parse_constant=constant,
        )
    except RecursionError as exc:
        raise ValueError("JSON nesting exceeds 32 levels") from exc
    if not isinstance(value, (dict, list)):
        raise ValueError("Choose a JSON object or array for data analysis")
    pending, nodes = [(value, 0)], 0
    while pending:
        item, depth = pending.pop()
        check()
        nodes += 1
        if nodes > MAX_JSON_NODES:
            raise ValueError("JSON contains too many values")
        if depth > MAX_JSON_DEPTH:
            raise ValueError("JSON nesting exceeds 32 levels")
        if isinstance(item, str):
            item.encode("utf-8")
        children = item.values() if isinstance(item, dict) else item if isinstance(item, list) else ()
        if nodes + len(pending) + len(children) > MAX_JSON_NODES:
            raise ValueError("JSON contains too many values")
        pending.extend((child, depth + 1) for child in children)

    def cell(item):
        # Streaming encoding avoids serializing a large nested object just to
        # display its beginning. JSON strings/keys remain ordinary escaped text.
        chunks, length = [], 0
        for chunk in json.JSONEncoder(ensure_ascii=True, allow_nan=False).iterencode(item):
            chunks.append(chunk[: max(0, 200 - length)])
            length += len(chunk)
            if length >= 200:
                break
        return "".join(chunks)

    if isinstance(value, dict):
        columns = ["Key", "Value"]
        rows = [[key[:200], cell(item)] for key, item in list(value.items())[:PREVIEW_ROWS]]
    elif value and all(isinstance(row, dict) for row in value):
        columns = list(dict.fromkeys(key for row in value for key in row))
        rows = [
            [cell(row[key]) if key in row else "" for key in columns[:PREVIEW_COLUMNS]]
            for row in value[:PREVIEW_ROWS]
        ]
    else:
        columns = ["Index", "Value"]
        rows = [[str(index), cell(item)] for index, item in enumerate(value[:PREVIEW_ROWS])]
    return {
        "format": "json",
        "root_type": "object" if isinstance(value, dict) else "array",
        "sheets": [
            {
                "name": "JSON",
                "row_count": len(value),
                "column_count": len(columns),
                "column_names": [key[:200] for key in columns[:PREVIEW_COLUMNS]],
                "preview": rows,
                "formula_count": 0,
            }
        ],
        "preview_limits": {"rows": PREVIEW_ROWS, "columns": PREVIEW_COLUMNS, "cell_characters": 200},
        "note": "Object keys or array elements form the preview. Nested values remain abbreviated JSON. Analysis reads the complete original file; this preview is not a flattened dataset.",
    }
