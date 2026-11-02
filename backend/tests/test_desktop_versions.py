"""Native version ownership is durable and cannot silently adopt other data."""

import json
import os
import shutil

import desktop_versions as versions
import pytest

PACKAGE = {
    "bundle_id": "a" * 64,
    "image_id": "sha256:" + "b" * 64,
    "version": "0.1.0",
    "source_epoch": 1790000000,
}
OWNER = "c" * 32


@pytest.fixture
def installation(tmp_path):
    root = tmp_path.resolve() / "station"
    root.mkdir(mode=0o700)
    data = root / "data"
    data.mkdir(mode=0o700)
    native = root / "native"
    native.mkdir(mode=0o700)
    config = root / "desktop.env"
    config.write_text(
        f'AI_STATION_DATA_HOST_PATH="{data}"\n'
        f'AI_STATION_RUNNER_SOCKET="{native}/runner/runner.sock"\n'
        'COMPOSE_PROJECT_NAME="ai-station-test"\nAI_STATION_ACCESS_PROFILE="accounts"\n'
    )
    config.chmod(0o600)
    previous_umask = os.umask(0o077)
    try:
        yield root, config, data
    finally:
        os.umask(previous_umask)


def test_real_receipt_start_ready_restart_and_attestation(installation):
    root, config, data = installation
    started = versions.begin(root, PACKAGE, config, OWNER)
    assert started["phase"] == "starting" and started["last_ready_at"] is None
    assert (root / versions.RECEIPT).stat().st_mode & 0o777 == 0o600
    current = versions.ready(root, PACKAGE, config, OWNER)
    assert current["last_ready_at"] > 0
    status = {"instance_id": OWNER, "ready": True, "stopping": False, "background": True}
    identity = {"instance_id": OWNER, "package": PACKAGE}
    assert versions.attest(root, config, status, identity) == PACKAGE
    # Persisted data is normal on subsequent starts of the very same package.
    (data / "db").mkdir(mode=0o700)
    (data / "db/ai-station.sqlite").write_bytes(b"neutral fixture, never opened")
    restarted = versions.begin(root, PACKAGE, config, "d" * 32)
    assert restarted["last_ready_at"] == current["last_ready_at"]
    assert restarted["phase"] == "starting"
    before = (root / versions.RECEIPT).read_bytes()
    with pytest.raises(ValueError, match="another"):
        versions.ready(root, PACKAGE, config, OWNER)
    with pytest.raises(ValueError, match="do not match"):
        versions.attest(root, config, status, identity)
    assert (root / versions.RECEIPT).read_bytes() == before


@pytest.mark.parametrize("field", list(PACKAGE))
def test_another_package_requires_explicit_upgrade(installation, field):
    root, config, _ = installation
    versions.begin(root, PACKAGE, config, OWNER)
    changed = PACKAGE | {
        field: {
            "bundle_id": "d" * 64,
            "image_id": "sha256:" + "e" * 64,
            "version": "0.2.0",
            "source_epoch": 1790000001,
        }[field]
    }
    before = (root / versions.RECEIPT).read_bytes()
    with pytest.raises(ValueError, match="explicit verified upgrade"):
        versions.begin(root, changed, config, OWNER)
    assert (root / versions.RECEIPT).read_bytes() == before


def test_reboot_runtime_recreation_and_non_coordinate_settings_do_not_relocate_installation(installation):
    root, config, _ = installation
    versions.begin(root, PACKAGE, config, OWNER)
    native = root / "native"
    (native / "runner").mkdir(mode=0o700)
    first = versions.namespace(config)
    shutil.rmtree(native)
    assert versions.namespace(config) == first
    native.mkdir(mode=0o700)
    with config.open("a") as handle:
        handle.write('AI_STATION_PORT=8766\nWORKERS=3\nLLM_ENDPOINT="http://localhost:9999"\n')
    assert versions.namespace(config) == first
    versions.ready(root, PACKAGE, config, OWNER)


@pytest.mark.parametrize("coordinate", ["data", "project", "socket", "access", "inode"])
def test_changed_storage_coordinates_cannot_adopt_receipt(installation, coordinate):
    root, config, data = installation
    versions.begin(root, PACKAGE, config, OWNER)
    text = config.read_text()
    if coordinate == "data":
        replacement = root / "other-data"
        replacement.mkdir(mode=0o700)
        text = text.replace(str(data), str(replacement))
    elif coordinate == "project":
        text = text.replace("ai-station-test", "another-project")
    elif coordinate == "socket":
        text = text.replace("/runner/runner.sock", "/another/runner.sock")
    elif coordinate == "access":
        text = text.replace("accounts", "legacy")
    else:
        data.rename(root / "old-data")
        data.mkdir(mode=0o700)
    config.write_text(text)
    with pytest.raises(ValueError):
        versions.begin(root, PACKAGE, config, OWNER)


def test_no_silent_adoption_of_existing_untracked_database(installation):
    root, config, data = installation
    (data / "db").mkdir(mode=0o700)
    db = data / "db/ai-station.sqlite"
    db.write_bytes(b"keep original")
    with pytest.raises(ValueError, match="verified version receipt"):
        versions.begin(root, PACKAGE, config, OWNER)
    assert db.read_bytes() == b"keep original"
    assert not (root / versions.RECEIPT).exists()


@pytest.mark.parametrize("target", ["data", "db", "config", "receipt"])
def test_symlinks_never_redirect_version_or_configuration_access(installation, target):
    root, config, data = installation
    versions.begin(root, PACKAGE, config, OWNER)
    path = {"data": data, "db": data / "db", "config": config, "receipt": root / versions.RECEIPT}[target]
    if target == "db":
        path.mkdir(mode=0o700)
    moved = root / (target + "-original")
    path.rename(moved)
    path.symlink_to(moved, target_is_directory=moved.is_dir())
    with pytest.raises(ValueError):
        versions.begin(root, PACKAGE, config, OWNER)


@pytest.mark.parametrize("target", ["config", "receipt"])
@pytest.mark.parametrize("unsafe", ["public", "hardlink", "fifo"])
def test_unsafe_files_are_refused_without_replacing_them(installation, target, unsafe):
    root, config, _ = installation
    versions.begin(root, PACKAGE, config, OWNER)
    path = config if target == "config" else root / versions.RECEIPT
    if unsafe == "public":
        path.chmod(0o644)
    elif unsafe == "hardlink":
        os.link(path, root / "extra-link")
    else:
        path.unlink()
        os.mkfifo(path, mode=0o600)
    before = path.lstat().st_ino
    with pytest.raises(ValueError):
        versions.begin(root, PACKAGE, config, OWNER)
    assert path.lstat().st_ino == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_epoch", True),
        ("source_epoch", -1),
        ("version", "v\nsecret"),
        ("version", "v" * 65),
        ("bundle_id", 1),
        ("image_id", "latest"),
    ],
)
def test_invalid_package_coordinates_fail_before_receipt_creation(installation, field, value):
    root, config, _ = installation
    with pytest.raises(ValueError):
        versions.begin(root, PACKAGE | {field: value}, config, OWNER)
    assert not (root / versions.RECEIPT).exists()


@pytest.mark.parametrize("change", ["status_owner", "identity_owner", "not_ready", "stopping", "extras"])
def test_live_attestation_refuses_mismatched_or_unready_owner(installation, change):
    root, config, _ = installation
    versions.begin(root, PACKAGE, config, OWNER)
    versions.ready(root, PACKAGE, config, OWNER)
    status = {"instance_id": OWNER, "ready": True, "stopping": False, "background": False}
    identity = {"instance_id": OWNER, "package": PACKAGE}
    if change == "status_owner":
        status["instance_id"] = "d" * 32
    elif change == "identity_owner":
        identity["instance_id"] = "d" * 32
    elif change == "not_ready":
        status["ready"] = False
    elif change == "stopping":
        status["stopping"] = True
    else:
        identity["setup_url"] = "never retained"
    with pytest.raises(ValueError, match="do not match"):
        versions.attest(root, config, status, identity)


def test_receipt_rejects_unknown_fields_and_preserves_original(installation):
    root, config, _ = installation
    versions.begin(root, PACKAGE, config, OWNER)
    receipt = root / versions.RECEIPT
    original = json.loads(receipt.read_text()) | {"setup_url": "never accepted"}
    receipt.write_text(json.dumps(original))
    before = receipt.read_bytes()
    with pytest.raises(ValueError, match="receipt is invalid"):
        versions.begin(root, PACKAGE, config, OWNER)
    assert receipt.read_bytes() == before
