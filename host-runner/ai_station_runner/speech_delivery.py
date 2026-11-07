"""Read the configured CLI's explicit contract without executing its code."""

import ast
import hashlib
from pathlib import Path


def inspect_delivery(script):
    try:
        path = Path(script).expanduser()
        with path.open("rb") as source:
            content = source.read(512 * 1024 + 1)
        if len(content) > 512 * 1024:
            return None
        tree = ast.parse(content)
    except (OSError, SyntaxError, ValueError, TypeError):
        return None
    flags = {
        argument.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "add_argument"
        for argument in node.args
        if isinstance(argument, ast.Constant) and isinstance(argument.value, str)
    }
    if not {"--ref", "--text", "--out", "--cfg", "--exaggeration", "--temperature"} <= flags:
        return None
    return {"version": "chatterbox-controls-v1", "source_sha256": hashlib.sha256(content).hexdigest()}


def inspect_language(script):
    """Advertise only an explicit CLI choice wired to multilingual generation."""
    try:
        with Path(script).expanduser().open("rb") as source:
            content = source.read(512 * 1024 + 1)
        if len(content) > 512 * 1024:
            return None
        tree = ast.parse(content)
    except (OSError, SyntaxError, ValueError, TypeError):
        return None
    declared = False
    used = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr == "add_argument" and any(
            isinstance(arg, ast.Constant) and arg.value == "--language" for arg in node.args
        ):
            options = {kw.arg: kw.value for kw in node.keywords}
            choices, default = options.get("choices"), options.get("default")
            declared = declared or (
                isinstance(choices, (ast.List, ast.Tuple))
                and all(isinstance(item, ast.Constant) for item in choices.elts)
                and {item.value for item in choices.elts} == {"pl", "en"}
                and isinstance(default, ast.Constant)
                and default.value == "pl"
            )
        if node.func.attr == "generate":
            used = used or any(
                kw.arg == "language_id"
                and isinstance(kw.value, ast.Attribute)
                and isinstance(kw.value.value, ast.Name)
                and kw.value.value.id == "args"
                and kw.value.attr == "language"
                for kw in node.keywords
            )
    if not declared or not used:
        return None
    return {
        "version": "chatterbox-language-v1",
        "languages": ["pl", "en"],
        "source_sha256": hashlib.sha256(content).hexdigest(),
    }
