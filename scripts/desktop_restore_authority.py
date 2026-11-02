"""Private native recovery input; reuse the application's pure credential rules."""

import importlib.util
import json
from pathlib import Path
from uuid import UUID

import desktop_snapshot_files as files
import desktop_versions as versions
from desktop_bridge import private_directory


def validate(value):
    if (
        not isinstance(value, dict)
        or set(value) != {"username", "password", "reset_mfa"}
        or value["reset_mfa"] is not True
        or not isinstance(value["username"], str)
        or not isinstance(value["password"], str)
    ):
        raise ValueError("Administrator recovery requires a username, new password and explicit MFA reset")
    # A fixed verified package file, never an import path selected by a request.
    path = Path(__file__).resolve().parent.parent / "backend/app/account_credentials.py"
    spec = importlib.util.spec_from_file_location("desktop_credentials", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    username, _ = module.username_identity(value["username"])
    if not module.MIN_PASSWORD <= len(value["password"]) <= module.MAX_PASSWORD:
        raise ValueError("Use a recovery password of 12 to 200 characters")
    return {"username": username, "password": value["password"], "reset_mfa": True}


def save(root, operation, value):
    if not isinstance(operation, str) or str(UUID(operation)) != operation:
        raise ValueError("Use a canonical restore UUID")
    value = validate(value)
    authority = versions.canonical(root)
    private_directory(authority)
    for name in ("restores", operation, "authority"):
        authority /= name
        authority.mkdir(mode=0o700, exist_ok=True)
        private_directory(authority)
    credential = authority / "administrator.json"
    if credential.exists() or credential.is_symlink():
        if json.loads(versions.read_private(credential, 4096)) != value:
            raise ValueError("The saved private recovery request differs; it was not overwritten")
    else:
        files.write_json(credential, value)
    return credential
