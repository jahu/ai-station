"""Hardware-free native-package bytes/policy controls, not Mac execution qualification."""

import hashlib
import io
import json
import struct
import sys
import tarfile
from pathlib import Path

import httpx
import macos_desktop_python as build
import pytest


def macho(architecture="arm64", minimum=(11, 0, 0), *, legacy=False):
    command = struct.pack("<IIIIII", 0x32, 24, 1, (minimum[0] << 16) | (minimum[1] << 8) | minimum[2], 0, 0)
    if legacy:
        command = struct.pack("<IIII", 0x24, 16, (minimum[0] << 16) | (minimum[1] << 8) | minimum[2], 0)
    return (
        struct.pack("<IiiIIIII", 0xFEEDFACF, build.CPU[architecture], 0, 2, 1, len(command), 0, 0) + command
    )


@pytest.mark.parametrize("architecture", ["arm64", "x86_64"])
def test_builtin_inputs_are_complete_pinned_native_wheels_with_explicit_minima(architecture):
    value = build.recipe(architecture)
    assert len(value["inputs"]) == 27 and not value["consumer_qualified"]
    assert value["minimum_os"] == ([14, 0] if architecture == "arm64" else [13, 3])
    wheels = {item["name"]: item for item in value["inputs"][1:]}
    assert {
        "fastapi",
        "uvicorn",
        "pydantic",
        "pydantic-core",
        "av",
        "numpy",
        "pillow",
        "httpx",
        "python-dotenv",
    } <= set(wheels)
    assert wheels["av"]["version"] == "19.0.1"
    assert (
        "macosx_14_0_arm64" in wheels["av"]["filename"]
        if architecture == "arm64"
        else "macosx_11_0_x86_64" in wheels["av"]["filename"]
    )
    assert sum(item["size_bytes"] for item in value["inputs"]) < 80 * 1024**2


@pytest.mark.parametrize("architecture", ["arm64", "x86_64"])
def test_native_headers_admit_only_the_requested_architecture_and_os(tmp_path, architecture):
    path = tmp_path / "native"
    path.write_bytes(macho(architecture))
    assert build.native_file(path, architecture, [13, 3]) == [11, 0, 0]
    with pytest.raises(ValueError, match="architecture"):
        build.native_file(path, "x86_64" if architecture == "arm64" else "arm64", [14, 0])
    path.write_bytes(macho(architecture, (15, 0, 0)))
    with pytest.raises(ValueError, match="minimum"):
        build.native_file(path, architecture, [14, 0])


def test_universal_header_selects_exactly_one_bounded_slice(tmp_path):
    path = tmp_path / "universal"
    arm, intel = macho(), macho("x86_64")
    table = (
        struct.pack(">II", 0xCAFEBABE, 2)
        + struct.pack(">IIIII", build.CPU["arm64"], 0, 48, len(arm), 0)
        + struct.pack(">IIIII", build.CPU["x86_64"], 0, 48 + len(arm), len(intel), 0)
    )
    path.write_bytes(table + arm + intel)
    assert (
        build.native_file(path, "arm64", [14, 0]) == build.native_file(path, "x86_64", [13, 3]) == [11, 0, 0]
    )
    path.write_bytes(table[:48] + arm)
    with pytest.raises(ValueError, match="boundary"):
        build.native_file(path, "arm64", [14, 0])


def test_older_legacy_runtime_minimum_is_valid_on_the_newer_target(tmp_path):
    # The pinned Intel NumPy wheel includes GCC's actual 10.8-minimum runtime.
    path = tmp_path / "native"
    path.write_bytes(macho("x86_64", (10, 8, 0), legacy=True))
    assert build.native_file(path, "x86_64", [13, 3]) == [10, 8, 0]


@pytest.mark.parametrize(
    "data", [b"ELF" + bytes(60), b"", struct.pack(">II", 0xCAFEBABE, 999) + bytes(60), macho()[:40]]
)
def test_malformed_foreign_or_truncated_binary_cannot_publish(data, tmp_path):
    path = tmp_path / "native"
    path.write_bytes(data)
    with pytest.raises(ValueError):
        build.native_file(path, "arm64", [14, 0])


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    store = cache / "models/store"
    store.mkdir(parents=True)
    cache.chmod(0o700)
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w:gz") as tar:
        for name, data in [
            ("python/bin/python3.12", macho()),
            ("python/lib/python3.12/neutral.py", b"# fixture"),
        ]:
            item = tarfile.TarInfo(name)
            item.size = len(data)
            item.mode = 0o755 if "/bin/" in name else 0o644
            tar.addfile(item, io.BytesIO(data))
        link = tarfile.TarInfo("python/bin/python3")
        link.type = tarfile.SYMTYPE
        link.linkname = "python3.12"
        tar.addfile(link)
    items = []
    for filename, data, kind in [
        ("python.tar.gz", archive.getvalue(), "python"),
        ("fixture-1-py3-none-any.whl", b"synthetic fixed wheel", "wheel"),
    ]:
        sha = hashlib.sha256(data).hexdigest()
        path = store / sha
        path.write_bytes(data)
        path.chmod(0o444)
        items.append(
            {
                "kind": kind,
                "filename": filename,
                "sha256": sha,
                "size_bytes": len(data),
                "name": "fixture",
                "version": "1",
            }
        )
    value = {
        "profile": "synthetic-native-python",
        "architecture": "arm64",
        "minimum_os": [14, 0],
        "python_version": "3.12.14",
        "inputs": items,
    }
    monkeypatch.setattr(build, "recipe", lambda *args: value)
    state = {
        "cache": cache,
        "output": tmp_path / "new-python",
        "recipe": value,
        "installed": [],
        "failure": None,
    }

    def install(python, folder, wheels, architecture, minimum):
        assert python.read_bytes() == macho()
        assert (folder / "wheels" / items[1]["filename"]).read_bytes() == b"synthetic fixed wheel"
        state["installed"].append(architecture)
        if state["failure"] == "install":
            raise OSError("fixture installation failed")
        site = python.parent.parent / "lib/python3.12/site-packages"
        site.mkdir(parents=True)
        (site / "native.so").write_bytes(macho("x86_64" if state["failure"] == "architecture" else "arm64"))
        (site / "metadata.txt").write_text("fixture")

    monkeypatch.setattr(build, "install", install)
    state["run"] = lambda: build.prepare(state["output"], cache, "arm64")
    return state


def test_complete_offline_layer_retains_aliases_and_verifies_every_published_file(fixture):
    value = fixture["run"]()
    output = fixture["output"]
    assert (
        not value["native_mac_code_executed"]
        and not value["python_import_qualified"]
        and not value["macos_installer_qualified"]
    )
    assert len(value["native_files"]) == 2 and fixture["installed"] == ["arm64"]
    assert (output / "bin/python3").is_symlink() and (
        output / "bin/python3"
    ).resolve() == output / "bin/python3.12"
    assert json.loads((output / "native-python.json").read_text()) == value
    assert all(build.file_manifest(output)[name] == sha for name, sha in value["files"].items())
    assert not list(output.parent.glob(".mac-python-*"))


@pytest.mark.parametrize("failure", ["install", "architecture"])
def test_failed_native_assembly_never_publishes_a_complete_output(fixture, failure):
    fixture["failure"] = failure
    with pytest.raises((ValueError, OSError)):
        fixture["run"]()
    assert not fixture["output"].exists() and not list(fixture["output"].parent.glob(".mac-python-*"))


@pytest.mark.parametrize("change", ["mutable", "hash", "missing", "symlink"])
def test_invalid_cached_input_cannot_reach_dependency_install(fixture, change):
    source = fixture["cache"] / "models/store" / fixture["recipe"]["inputs"][1]["sha256"]
    if change == "mutable":
        source.chmod(0o644)
    if change == "hash":
        source.chmod(0o644)
        source.write_bytes(b"X" * source.stat().st_size)
        source.chmod(0o444)
    if change == "missing":
        source.unlink()
    if change == "symlink":
        target = source.with_name("separate")
        source.rename(target)
        source.symlink_to(target)
    with pytest.raises((ValueError, OSError)):
        fixture["run"]()
    assert not fixture["installed"] and not fixture["output"].exists()


def test_existing_output_is_never_overwritten(fixture):
    fixture["output"].mkdir()
    marker = fixture["output"] / "keep"
    marker.write_text("existing")
    with pytest.raises(ValueError):
        fixture["run"]()
    assert marker.read_text() == "existing" and not fixture["installed"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("sha256", "../private"),
        ("filename", "../escape.whl"),
        ("url", "http://127.0.0.1/credentials"),
        ("size_bytes", True),
        ("name", "package\n--extra-index-url private"),
    ],
)
def test_changed_input_coordinates_cannot_reach_builder_network_or_files(tmp_path, monkeypatch, field, value):
    recipe = build.recipe("arm64")
    recipe["inputs"][1][field] = value
    (tmp_path / "arm64.json").write_text(json.dumps(recipe))
    monkeypatch.setattr(build, "RECIPES", tmp_path)
    with pytest.raises(ValueError):
        build.recipe("arm64")


def test_cross_install_is_offline_hash_pinned_and_never_executes_target_python(tmp_path, monkeypatch):
    python = tmp_path / "python/bin/python3.12"
    python.parent.mkdir(parents=True)
    python.write_bytes(macho())
    seen = []
    monkeypatch.setattr(build.shutil, "which", lambda name: "/builder/uv" if name == "uv" else None)
    monkeypatch.setenv("PRIVATE_BUILD_TOKEN", "must-not-propagate")

    def run(argv, **kwargs):
        seen.append((argv, kwargs))
        site = Path(argv[argv.index("--target") + 1])
        (site / "bin").mkdir(parents=True)
        (site / "bin/console-script").write_text("#!/build-only/python")

    monkeypatch.setattr(build.subprocess, "run", run)
    wheel = {"name": "fixture", "version": "1", "sha256": "a" * 64}
    build.install(python, tmp_path, [wheel], "arm64", [14, 0])
    argv, kwargs = seen[0]
    assert argv[0] == "/builder/uv" and argv[argv.index("--python") + 1] == sys.executable
    assert str(python) not in argv
    assert all(
        flag in argv
        for flag in [
            "--offline",
            "--no-python-downloads",
            "--no-index",
            "--no-deps",
            "--require-hashes",
            "--only-binary",
        ]
    )
    assert "PRIVATE_BUILD_TOKEN" not in kwargs["env"] and kwargs["env"]["MACOSX_DEPLOYMENT_TARGET"] == "14.0"
    assert not (python.parent.parent / "lib/python3.12/site-packages/bin").exists()


@pytest.mark.parametrize("failure", [None, "hash", "length", "http"])
def test_fixed_input_download_is_verified_before_exclusive_publication(tmp_path, monkeypatch, failure):
    cache = tmp_path / "cache"
    cache.mkdir(mode=0o700)
    data = b"fixed public fixture"
    item = {
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
        "url": "https://files.pythonhosted.org/packages/fixture",
    }
    client = build.httpx.Client

    def response(request):
        if failure == "http":
            return httpx.Response(503)
        return httpx.Response(
            200,
            content=(b"X" * len(data) if failure == "hash" else data + b"X" if failure == "length" else data),
        )

    monkeypatch.setattr(
        build.httpx, "Client", lambda **kw: client(transport=httpx.MockTransport(response), **kw)
    )
    target = cache / "models/store" / item["sha256"]
    if failure:
        with pytest.raises((ValueError, httpx.HTTPError)):
            build.fetch(cache, {"inputs": [item]}, lambda: None)
        assert not target.exists()
    else:
        build.fetch(cache, {"inputs": [item]}, lambda: None)
        assert (
            target.read_bytes() == data
            and target.stat().st_mode & 0o777 == 0o444
            and target.stat().st_nlink == 1
        )
        build.fetch(cache, {"inputs": [item]}, lambda: None)
    assert not list((cache / "models/store").glob(".download-*"))
