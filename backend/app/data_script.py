"""Visible, fixed sandbox bindings included in the exact audited Python source."""

import ast

BINDINGS = """# AI Station sandbox bindings: approved inputs only; no extra file or network authority.
import csv
import json
import os
inputs = json.loads(os.environ["AI_STATION_INPUTS"])
output_dir = os.environ["AI_STATION_OUTPUT_DIR"]
"""


def prepare_script(source: str) -> str:
    tree = ast.parse(source, filename="analysis.py")
    headers = 1 if ast.get_docstring(tree) is not None else 0
    while headers < len(tree.body):
        node = tree.body[headers]
        if not isinstance(node, ast.ImportFrom) or node.module != "__future__":
            break
        headers += 1
    line = tree.body[headers - 1].end_lineno if headers else 0
    if headers and headers < len(tree.body) and tree.body[headers].lineno == line:
        # Separate an inline docstring/future import from subsequent statements.
        return prepare_script(ast.unparse(tree) + "\n")
    lines = source.splitlines(keepends=True)
    before = "".join(lines[:line])
    if before and not before.endswith("\n"):
        before += "\n"
    prepared = before + BINDINGS + "\n" + "".join(lines[line:])
    if len(prepared.encode()) > 32000:
        raise ValueError("Generated Python source including runtime bindings exceeds its byte limit")
    compile(prepared, "analysis.py", "exec")
    return prepared
