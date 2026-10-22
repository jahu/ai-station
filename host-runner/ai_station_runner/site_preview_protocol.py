"""Internal, offline website-preview protocol. Not a public Runner capability."""

import base64
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit
from uuid import UUID

PROTOCOL_VERSION = "2"
ORIGIN = "http://preview.invalid"
MAX_RESPONSE = 8 * 1024 * 1024
MAX_FRAME = 8 * 1024 * 1024
MAX_LINE = 12 * 1024 * 1024
MAX_ACTIONS = 128
KEYS = frozenset(
    {
        "Tab",
        "Enter",
        "Escape",
        "Backspace",
        "Delete",
        "ArrowUp",
        "ArrowDown",
        "ArrowLeft",
        "ArrowRight",
        "Home",
        "End",
        "PageUp",
        "PageDown",
        "Space",
    }
)


def integer(value, minimum, maximum):
    return type(value) is int and minimum <= value <= maximum


def asset_path(value):
    if not isinstance(value, str) or not value or len(value) > 512:
        raise ValueError("Invalid preview asset path")
    path = PurePosixPath(value)
    if (
        not path.parts
        or str(path) != value
        or path.is_absolute()
        or any(part.startswith(".") for part in path.parts)
        or any(c in value for c in "\\:%?#")
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
    ):
        raise ValueError("Invalid preview asset path")
    return value


def resource_path(url):
    if not isinstance(url, str) or len(url) > 4096 or any(ord(c) < 32 or ord(c) == 127 for c in url):
        return None
    try:
        parsed = urlsplit(url)
        if parsed.scheme != "http" or parsed.netloc != "preview.invalid":
            return None
        path = unquote(parsed.path, errors="strict")
        if not path.startswith("/") or path.startswith("//"):
            return None
        return asset_path(path[1:] or "index.html")
    except (ValueError, UnicodeError):
        return None


def open_request(value):
    if (
        not isinstance(value, dict)
        or set(value) != {"kind", "entry", "width", "height", "max_seconds"}
        or value["kind"] != "open"
        or not integer(value["width"], 320, 1600)
        or not integer(value["height"], 240, 1200)
        or not integer(value["max_seconds"], 1, 900)
    ):
        raise ValueError("Invalid preview initialization")
    asset_path(value["entry"])
    return value


def action_request(value, width, height):
    if (
        not isinstance(value, dict)
        or set(value) != {"kind", "id", "expected_revision", "action"}
        or value["kind"] != "action"
        or not isinstance(value["id"], str)
        or not integer(value["expected_revision"], 0, MAX_ACTIONS)
    ):
        raise ValueError("Invalid preview action")
    try:
        if str(UUID(value["id"])) != value["id"]:
            raise ValueError("Noncanonical action identity")
    except (ValueError, AttributeError) as exc:
        raise ValueError("Invalid preview action identity") from exc
    action = value["action"]
    if not isinstance(action, dict):
        raise ValueError("Invalid preview action")
    kind = action.get("kind")
    if not isinstance(kind, str):
        raise ValueError("Invalid preview action kind")
    valid = False
    if kind == "click":
        valid = (
            set(action) == {"kind", "x", "y"}
            and integer(action["x"], 0, width - 1)
            and integer(action["y"], 0, height - 1)
        )
    elif kind == "text":
        valid = (
            set(action) == {"kind", "text"}
            and isinstance(action["text"], str)
            and 0 < len(action["text"]) <= 2000
            and "\x00" not in action["text"]
        )
    elif kind == "key":
        valid = set(action) == {"kind", "key"} and isinstance(action["key"], str) and action["key"] in KEYS
    elif kind == "scroll":
        valid = (
            set(action) == {"kind", "delta_x", "delta_y"}
            and integer(action["delta_x"], -1500, 1500)
            and integer(action["delta_y"], -1500, 1500)
        )
    elif kind in {"reset", "snapshot"}:
        valid = set(action) == {"kind"}
    if not valid:
        raise ValueError("Unsupported or invalid preview action")
    return value


def resource_response(value, request_id):
    if (
        not isinstance(value, dict)
        or set(value) != {"kind", "id", "status", "content_type", "body"}
        or value["kind"] != "resource"
        or not integer(value["id"], 1, 2048)
        or value["id"] != request_id
        or type(value["status"]) is not int
        or value["status"] not in {200, 403, 404}
        or not isinstance(value["content_type"], str)
        or not 0 < len(value["content_type"]) <= 100
        or any(ord(c) < 32 or ord(c) == 127 for c in value["content_type"])
        or not isinstance(value["body"], str)
        or len(value["body"]) > (MAX_RESPONSE + 2) // 3 * 4
    ):
        raise ValueError("Invalid preview resource response")
    try:
        body = base64.b64decode(value["body"], validate=True)
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Invalid preview resource encoding") from exc
    if len(body) > MAX_RESPONSE:
        raise ValueError("Preview resource exceeded its limit")
    return body
