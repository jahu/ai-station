"""Private native credential input, no SQL, Docker, models or actual credentials."""

import json
import stat
from uuid import uuid4

import desktop_restore_authority as authority
import pytest

SECRET = {"username": "Owner", "password": "synthetic private recovery password", "reset_mfa": True}


def test_shared_username_rules_and_private_frozen_request(tmp_path):
    root = tmp_path / "desktop"
    root.mkdir(mode=0o700)
    operation = str(uuid4())
    path = authority.save(root, operation, SECRET | {"username": " Ｏｗｎｅｒ "})
    assert json.loads(path.read_text()) == SECRET
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    for parent in (path.parent, path.parent.parent, path.parent.parent.parent):
        assert stat.S_IMODE(parent.stat().st_mode) == 0o700
    assert authority.save(root, operation, SECRET) == path
    with pytest.raises(ValueError, match="not overwritten"):
        authority.save(root, operation, SECRET | {"password": "different private recovery password"})
    assert json.loads(path.read_text()) == SECRET


@pytest.mark.parametrize(
    "value",
    [
        SECRET | {"reset_mfa": False},
        SECRET | {"username": "Owner/escape"},
        SECRET | {"password": "short"},
        SECRET | {"password": "x" * 201},
        SECRET | {"username": 42},
        SECRET | {"extra": True},
    ],
)
def test_invalid_inputs_never_create_files_or_disclose_password(tmp_path, value):
    root = tmp_path / "desktop"
    root.mkdir(mode=0o700)
    with pytest.raises(ValueError) as error:
        authority.save(root, str(uuid4()), value)
    assert SECRET["password"] not in str(error.value)
    assert list(root.iterdir()) == []


def test_symlinked_authority_never_overwrites_external_credentials(tmp_path):
    root, external = tmp_path / "desktop", tmp_path / "external"
    root.mkdir(mode=0o700)
    external.mkdir(mode=0o700)
    keep = external / "administrator.json"
    keep.write_text("external bytes to preserve")
    operation = str(uuid4())
    parent = root / "restores" / operation
    parent.mkdir(mode=0o700, parents=True)
    (root / "restores").chmod(0o700)
    (parent / "authority").symlink_to(external, target_is_directory=True)
    with pytest.raises(ValueError):
        authority.save(root, operation, SECRET)
    assert keep.read_text() == "external bytes to preserve"
