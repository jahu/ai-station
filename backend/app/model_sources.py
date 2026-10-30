"""Portable model source coordinates; old host payloads keep their identities."""

from pathlib import PurePosixPath


def path_of(model):
    return model.relative_path or model.host_path


def source_of(model):
    result = {"model_path": path_of(model), "size_bytes": model.size_bytes, "mtime": model.mtime}
    if model.relative_path:
        result.update(app_owned=True, model_sha256=model.sha256)
    return result


def verify_source(source):
    return {
        "host_path": source["model_path"],
        "size_bytes": source["size_bytes"],
        "mtime": source["mtime"],
        **({"app_owned": True, "model_sha256": source["model_sha256"]} if source.get("app_owned") else {}),
    }


def label_of(model):
    prefix = "AI Station" if model.relative_path else PurePosixPath(model.host_path).parent.name
    return f"{prefix} · {model.filename}"
