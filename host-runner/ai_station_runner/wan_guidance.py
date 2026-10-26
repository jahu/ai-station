"""Fixed built-in guidance recipes; never a caller-supplied node graph."""

import ast
import hashlib
from pathlib import Path

STANDARD = "standard"
APG = "apg_v1"


def apg_observation(paths):
    """Check the installed method without importing Torch into the Runner API."""
    path = Path(paths["comfy_dir"]) / "comfy_extras" / "nodes_apg.py"
    try:
        with path.open("rb") as handle:
            data = handle.read(65537)
        if len(data) > 65536:
            return None
        tree = ast.parse(data)
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "APG")
        execute = next(
            node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "execute"
        )
        if [arg.arg for arg in execute.args.args] != ["cls", "model", "eta", "norm_threshold", "momentum"]:
            return None
        if not any(
            isinstance(node, ast.Name) and node.id == "classmethod" for node in execute.decorator_list
        ):
            return None
        return {"size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    except (OSError, SyntaxError, ValueError, StopIteration):
        return None


def apply_guidance(model, method=STANDARD):
    if method == STANDARD:
        return model
    if method != APG:
        raise ValueError("Unsupported fixed Wan guidance recipe")
    from comfy_extras.nodes_apg import APG as AdaptiveProjectedGuidance

    return AdaptiveProjectedGuidance.execute(model, 0.0, 5.0, 0.0)[0]
