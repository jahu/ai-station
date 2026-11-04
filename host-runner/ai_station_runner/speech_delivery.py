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
