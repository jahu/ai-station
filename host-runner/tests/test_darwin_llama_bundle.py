"""Native byte assembly/security; never execute Mach-O, GPU or model inference."""

import hashlib
import io
import os
import shutil
import struct
import tarfile
from pathlib import Path
from uuid import uuid4

import pytest
from ai_station_runner import darwin_llama_bundle as bundle


def macho(architecture="arm64", *, executable=False, dependency=None, minimum=0x0D0300, rpath="@loader_path"):
    commands = [struct.pack("<IIIIII", 0x32, 24, 1, minimum, minimum, 0)]
    for kind, text in [(0x8000001C, rpath), *(([(0xC, dependency)]) if dependency else [])]:
        value = text.encode() + b"\0"
        prefix = 12 if kind == 0x8000001C else 24
        size = (prefix + len(value) + 7) // 8 * 8
        commands.append(
            struct.pack("<III", kind, size, prefix)
            + b"\0" * (prefix - 12)
            + value
            + b"\0" * (size - prefix - len(value))
        )
    body = b"".join(commands)
    return (
        struct.pack(
            "<IiiIIIII",
            0xFEEDFACF,
            0x100000C if architecture == "arm64" else 0x1000007,
            0,
            2 if executable else 6,
            len(commands),
            len(body),
            0,
            0,
        )
        + body
    )


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    state = {"root": tmp_path.resolve(), "operation": str(uuid4()), "progress": [], "extra": []}
    state["files"] = {
        "LICENSE": b"synthetic license\n",
        "libtest.0.1.dylib": macho(),
        "llama-server": macho(executable=True, dependency="@rpath/libtest.0.dylib"),
    }
    state["links"] = {"libtest.0.dylib": "libtest.0.1.dylib", "libtest.dylib": "libtest.0.dylib"}
    state["frozen"] = {
        "profile": "synthetic-native-bundle",
        "source_revision": bundle.SOURCE,
        "archive_root": "native",
        "platform": "darwin/arm64",
        "files": {},
        "inputs": [],
        "inference_qualified": False,
    }

    def rebuild():
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode="w:gz") as archive:
            for name, content in state["files"].items():
                item = tarfile.TarInfo("native/" + name)
                item.size = len(content)
                item.mode = 0o755
                archive.addfile(item, io.BytesIO(content))
            for name, target in state["links"].items():
                item = tarfile.TarInfo("native/" + name)
                item.type = tarfile.SYMTYPE
                item.linkname = target
                archive.addfile(item)
            for item in state["extra"]:
                archive.addfile(item)
        raw = data.getvalue()
        digest = hashlib.sha256(raw).hexdigest()
        store = tmp_path / "models/store"
        store.mkdir(parents=True, exist_ok=True)
        source = store / digest
        if not source.exists():
            source.write_bytes(raw)
            source.chmod(0o444)
        selected = {}
        for name in [*state["files"], *state["links"]]:
            target = name
            seen = set()
            while target in state["links"]:
                if target in seen:
                    break
                seen.add(target)
                target = state["links"][target]
            if target not in state["files"]:
                continue
            content = state["files"][target]
            selected[name] = {
                "source": target,
                "size_bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        state["frozen"].update(
            files=selected, inputs=[{"filename": "fixture.tgz", "size_bytes": len(raw), "sha256": digest}]
        )
        state["source"] = source

    state["rebuild"] = rebuild
    rebuild()
    monkeypatch.setattr(bundle, "recipe", lambda architecture: state["frozen"])
    return state


def prepare(state, *, check=lambda: None):
    return bundle.prepare(
        state["root"], state["operation"], "arm64", check=check, progress=state["progress"].append
    )


def test_offline_preparation_verifies_macho_and_materializes_only_regular_files(fixture):
    result = prepare(fixture)
    folder = fixture["root"] / result["relative_path"]
    assert result["inference_qualified"] is False and not Path(result["relative_path"]).is_absolute()
    assert bundle.inspect(fixture["root"], fixture["operation"], "arm64") == result
    engine = folder / "engine"
    assert (engine / "libtest.dylib").read_bytes() == fixture["files"]["libtest.0.1.dylib"]
    for file in engine.iterdir():
        assert not file.is_symlink() and file.stat().st_nlink == 1 and not file.stat().st_mode & 0o222
    assert os.access(engine / "llama-server", os.X_OK)
    assert fixture["progress"][-1]["completed_files"] == len(fixture["frozen"]["files"])
    with pytest.raises(ValueError, match="existing native preparation"):
        prepare(fixture)


@pytest.mark.parametrize("problem", ["size", "hash", "writable", "symlink", "hardlink"])
def test_input_must_be_an_exact_immutable_owned_store_object(fixture, problem):
    path = fixture["source"]
    if problem == "size":
        fixture["frozen"]["inputs"][0]["size_bytes"] += 1
    if problem == "hash":
        path.chmod(0o644)
        raw = bytearray(path.read_bytes())
        raw[-1] ^= 1
        path.write_bytes(raw)
        path.chmod(0o444)
    if problem == "writable":
        path.chmod(0o644)
    if problem == "symlink":
        other = path.with_suffix(".moved")
        path.rename(other)
        path.symlink_to(other.name)
    if problem == "hardlink":
        os.link(path, path.with_suffix(".linked"))
    with pytest.raises((ValueError, OSError)):
        prepare(fixture)
    assert not (fixture["root"] / "runtime").exists()


@pytest.mark.parametrize(
    "problem", ["absolute", "parent", "duplicate", "fifo", "hardlink", "setuid", "external_link", "cycle"]
)
def test_archive_paths_types_and_links_cannot_escape_the_new_bundle(fixture, problem):
    name = "native/extra"
    if problem == "absolute":
        name = "/outside"
    if problem == "parent":
        name = "native/../outside"
    if problem == "duplicate":
        name = "native/LICENSE"
    item = tarfile.TarInfo(name)
    if problem == "fifo":
        item.type = tarfile.FIFOTYPE
    if problem == "hardlink":
        item.type = tarfile.LNKTYPE
        item.linkname = "native/LICENSE"
    if problem == "setuid":
        item.mode = 0o4755
    if problem == "external_link":
        fixture["links"]["libtest.dylib"] = "../../outside"
    elif problem == "cycle":
        fixture["links"]["libtest.0.1.dylib"] = "libtest.dylib"
    else:
        fixture["extra"].append(item)
    fixture["rebuild"]()
    if problem == "cycle":
        fixture["frozen"]["files"]["libtest.dylib"] = {
            "source": "libtest.0.1.dylib",
            "size_bytes": 1,
            "sha256": "0" * 64,
        }
    with pytest.raises(ValueError):
        prepare(fixture)
    assert not list((fixture["root"] / "runtime").rglob("bundle.json"))
    assert not (fixture["root"] / "outside").exists()


@pytest.mark.parametrize(
    "change",
    ["architecture", "minimum", "external_library", "external_rpath", "missing_library", "truncated"],
)
def test_bad_native_abi_or_external_dependencies_are_not_published(fixture, change):
    kwargs = {"executable": True, "dependency": "@rpath/libtest.0.dylib"}
    if change == "architecture":
        kwargs["architecture"] = "x86_64"
    if change == "minimum":
        kwargs["minimum"] = 0x0E0000
    if change == "external_library":
        kwargs["dependency"] = "/opt/homebrew/lib/unreviewed.dylib"
    if change == "external_rpath":
        kwargs["rpath"] = "/tmp/unreviewed"
    if change == "missing_library":
        kwargs["dependency"] = "@rpath/missing.dylib"
    body = macho(**kwargs)
    if change == "truncated":
        body = body[:-1]
    fixture["files"]["llama-server"] = body
    fixture["rebuild"]()
    with pytest.raises(ValueError):
        prepare(fixture)
    assert not list((fixture["root"] / "runtime").rglob("bundle.json"))


def test_cancellation_preserves_partial_operation_without_a_ready_receipt(fixture):
    def check():
        if fixture["progress"]:
            raise InterruptedError("cooperative cancellation")

    with pytest.raises(InterruptedError):
        prepare(fixture, check=check)
    assert not list((fixture["root"] / "runtime").rglob("bundle.json"))
    assert len(list((fixture["root"] / "runtime").rglob("preparing.json"))) == 1
    with pytest.raises(ValueError, match="existing native preparation"):
        prepare(fixture)


@pytest.mark.parametrize(
    "change", ["file", "extra", "receipt", "engine_link", "runtime_link", "non_executable"]
)
def test_inspection_rejects_changed_files_receipts_or_directory_links(fixture, change):
    result = prepare(fixture)
    folder = fixture["root"] / result["relative_path"]
    if change == "file":
        path = folder / "engine/LICENSE"
        path.chmod(0o644)
        path.write_bytes(b"wrong")
    if change == "extra":
        (folder / "engine/injected").write_bytes(b"extra")
    if change == "receipt":
        path = folder / "bundle.json"
        path.chmod(0o644)
        path.write_text("{}")
    if change == "non_executable":
        (folder / "engine/llama-server").chmod(0o444)
    if change == "engine_link":
        other = fixture["root"] / "moved-engine"
        (folder / "engine").rename(other)
        (folder / "engine").symlink_to(other, target_is_directory=True)
    if change == "runtime_link":
        runtime = fixture["root"] / "runtime"
        other = fixture["root"] / "moved-runtime"
        runtime.rename(other)
        runtime.symlink_to(other, target_is_directory=True)
    with pytest.raises((ValueError, OSError)):
        bundle.inspect(fixture["root"], fixture["operation"], "arm64")


@pytest.mark.parametrize("architecture,metal", [("arm64", True), ("x86_64", False)])
def test_fixed_recipes_distinguish_native_architecture_and_do_not_claim_inference(architecture, metal):
    value = bundle.recipe(architecture)
    assert value["platform"] == "darwin/" + architecture and value["inference_qualified"] is False
    assert ("metal" in value["compiled_backends"]) is metal
    assert value["inputs"][0]["url"].startswith(
        "https://github.com/ggml-org/llama.cpp/releases/download/b12032/"
    )
    assert value["minimum_os"] == [13, 3, 0]
    assert "LICENSE" in value["files"] and "llama-server" in value["files"]


def test_unknown_native_architecture_is_not_a_recipe():
    with pytest.raises(ValueError):
        bundle.recipe("../../unreviewed")


@pytest.mark.parametrize("architecture", ["arm64", "x86_64"])
def test_byte_preparation_does_not_enable_an_unqualified_runner_profile(architecture):
    from ai_station_runner.runtime_setup import RuntimeSelection
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        RuntimeSelection(profile=bundle.recipe(architecture)["profile"])


@pytest.mark.skipif(
    os.getenv("AI_STATION_REAL_MAC_BUNDLE_TESTS") != "1",
    reason="Opt-in verified public archive assembly, not native Mac execution",
)
@pytest.mark.parametrize("architecture", ["arm64", "x86_64"])
def test_actual_verified_archive_assembly(tmp_path, architecture):
    folder = os.getenv("AI_STATION_MAC_BUNDLE_CACHE")
    assert folder, "Set the explicit already verified native archive cache"
    value = bundle.recipe(architecture)
    item = value["inputs"][0]
    store = tmp_path / "models/store"
    store.mkdir(parents=True)
    target = store / item["sha256"]
    shutil.copyfile(Path(folder) / item["filename"], target)
    target.chmod(0o444)
    operation = str(uuid4())
    result = bundle.prepare(tmp_path, operation, architecture)
    assert bundle.inspect(tmp_path, operation, architecture) == result
    assert result["inference_qualified"] is False
