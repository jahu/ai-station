"""Mac package assembly uses neutral Mach-O/CLI fixtures, never native execution."""

import hashlib
import json
import plistlib
import shutil
from pathlib import Path
from types import SimpleNamespace

import build_linux_package
import build_macos_package as build
import desktop
import macos_application_probe as application
import pytest
from test_macos_desktop_python import macho


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    source, layer, native = (tmp_path / name for name in ("repository", "python", "native"))
    original = build.ROOT
    source.mkdir()
    for name in build_linux_package.SOURCE:
        if name == "host-runner/ai_station_runner":
            continue
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("neutral package fixture\n")
    package = source / "host-runner/ai_station_runner"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("# neutral Runner, never executed\n")
    for name in ("packaging/macos/arm64.json", "Dockerfile"):
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original / name, target)
    (source / "packaging/macos/native.m").write_text("// neutral native source fixture\n")
    (layer / application.SITE).mkdir(parents=True)
    shutil.copy2(package / "__init__.py", layer / application.SITE / "__init__.py")
    (layer / "bin").mkdir()
    (layer / "bin/python3.12").write_bytes(macho())
    (layer / "bin/python3.12").chmod(0o755)
    (layer / "bin/python3").symlink_to("python3.12")
    frozen = json.loads((source / "packaging/macos/arm64.json").read_text())
    manifest_hash = build.fingerprint(frozen)
    base = {
        "schema": 1,
        "architecture": "arm64",
        "manifest_sha256": manifest_hash,
        "python_version": "3.12.14",
        "files": {name: build.digest(layer / name) for name in ("bin/python3", "bin/python3.12")},
    }
    (layer / "native-python.json").write_text(json.dumps(base))
    value = {
        "schema": 1,
        "profile": "application-python312-darwin-arm64-v1",
        "architecture": "arm64",
        "source_head": "a" * 40,
        "source_dirty": False,
        "native_application_executed": False,
        "macos_installer_qualified": False,
        "base_inventory_unchanged": True,
        "base_manifest_sha256": manifest_hash,
        "base_receipt_sha256": build.digest(layer / "native-python.json"),
        "runner_source_files": {"__init__.py": build.digest(package / "__init__.py")},
        "files": application.inventory(layer),
    }
    (layer / "application-python.json").write_text(json.dumps(value))
    native.mkdir()
    binary = native / "ai-station-native"
    binary.write_bytes(macho())
    binary.chmod(0o755)
    (native / "native-interface.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "architecture": "arm64",
                "minimum_os": [14, 0],
                "source_sha256": build.digest(source / "packaging/macos/native.m"),
                "binary_sha256": build.digest(binary),
                "macos_installer_qualified": False,
            }
        )
    )
    image_id = "sha256:" + "b" * 64
    image = {"Id": image_id, "Os": "linux", "Architecture": "arm64", "Config": {"User": "1000:1000"}}
    image_build = tmp_path / "build.json"
    dockerfile = (source / "Dockerfile").read_bytes()
    image_build.write_text(
        json.dumps(
            {
                "status": "built_image_only",
                "source_head": "a" * 40,
                "platform": "linux/arm64",
                "image_tag": "ai-station:qa-test",
                "image_id": image_id,
                "canonical_dockerfile_sha256": hashlib.sha256(dockerfile).hexdigest(),
                "generated_dockerfile_sha256": hashlib.sha256(build.image_recipe(dockerfile)).hexdigest(),
            }
        )
    )

    def git(argv, *, cwd, text=False):
        assert cwd == source
        command = argv[1:]
        if command == ["rev-parse", "HEAD"]:
            value = "a" * 40
        elif command == ["status", "--porcelain"]:
            value = ""
        elif command[0] == "ls-files":
            value = "host-runner/ai_station_runner/__init__.py\0"
        elif command == ["show", "-s", "--format=%ct", "HEAD"]:
            value = "1793570000"
        else:
            pytest.fail("Unexpected developer command")
        return value if text else value.encode()

    commands = []

    def docker(*args):
        commands.append(args)
        result = SimpleNamespace(returncode=0, stdout="", stderr="")
        if args[:2] == ("context", "inspect"):
            result.stdout = "unix:///private/neutral/docker.sock"
        elif args[:2] == ("image", "inspect"):
            if args[2] == "ai-station:qa-test":
                result.stdout = json.dumps([image])
            else:
                result.returncode, result.stderr = 1, "No such image"
        elif args[:2] == ("image", "save"):
            Path(args[3]).write_bytes(b"neutral export fixture, never loaded")
        elif args[:2] != ("image", "tag"):
            pytest.fail("Unexpected Docker operation")
        return result

    monkeypatch.setattr(build, "ROOT", source)
    monkeypatch.setattr(build_linux_package, "ROOT", source)
    monkeypatch.setattr(application.subprocess, "check_output", git)
    monkeypatch.setattr(build, "docker", docker)
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    return SimpleNamespace(
        source=source,
        layer=layer,
        native=native,
        image=image,
        image_build=image_build,
        commands=commands,
        output=tmp_path / "AI Station.app",
    )


def assemble(inputs, **kwargs):
    return build.bundle(
        inputs.output,
        inputs.layer,
        inputs.native,
        "arm64",
        "ai-station:qa-test",
        inputs.image_build,
        **kwargs,
    )


def test_application_layout_preserves_inputs_and_records_unsigned_component_scope(inputs):
    before = application.inventory(inputs.layer)
    value = assemble(inputs)
    contents = inputs.output / "Contents"
    resources = contents / "Resources"
    info = plistlib.loads((contents / "Info.plist").read_bytes())
    assert info["CFBundleExecutable"] == "AI Station" and info["LSMinimumSystemVersion"] == "14.0"
    assert info["LSArchitecturePriority"] == ["arm64"]
    assert build.digest(contents / "MacOS/AI Station") == value["native_interface_sha256"]
    assert desktop.manifest(resources) == value
    desktop.verify(resources, value)
    assert application.inventory(inputs.layer) == before
    assert not value["signed"] and not value["notarized"] and not value["macos_installer_qualified"]
    assert (resources / "python/bin/python3").is_symlink()
    assert not (resources / "data").exists()
    assert ("image", "tag", value["image_id"], value["image_tag"]) in inputs.commands


@pytest.mark.parametrize("change", ["architecture", "image_id", "source_head"])
def test_another_image_architecture_or_source_cannot_publish_an_application(inputs, change):
    if change == "architecture":
        inputs.image["Architecture"] = "amd64"
    elif change == "image_id":
        inputs.image["Id"] = "sha256:" + "c" * 64
    else:
        value = json.loads(inputs.image_build.read_text())
        value["source_head"] = "c" * 40
        inputs.image_build.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="image"):
        assemble(inputs)
    assert not inputs.output.exists() and not any(
        command[:2] == ("image", "tag") for command in inputs.commands
    )


def test_remote_docker_is_rejected_before_image_or_output_changes(inputs, monkeypatch):
    monkeypatch.setenv("DOCKER_HOST", "tcp://example.invalid:2375")
    with pytest.raises(ValueError, match="local Unix"):
        assemble(inputs)
    assert not inputs.commands and not inputs.output.exists()


@pytest.mark.parametrize("target", ["python", "interface"])
def test_tampered_python_or_native_bytes_fail_before_any_docker_operation(inputs, target):
    path = inputs.layer / "bin/python3.12" if target == "python" else inputs.native / "ai-station-native"
    path.write_bytes(b"changed fixture")
    with pytest.raises(ValueError):
        assemble(inputs)
    assert not inputs.commands and not inputs.output.exists()


def test_existing_application_is_never_replaced(inputs):
    inputs.output.mkdir()
    (inputs.output / "keep").write_text("existing application")
    with pytest.raises(ValueError, match="new canonical"):
        assemble(inputs)
    assert (inputs.output / "keep").read_text() == "existing application"
    assert not inputs.commands


def test_recursive_output_inside_python_is_refused_before_copy_or_docker(inputs):
    inputs.output = inputs.layer / "recursive.app"
    with pytest.raises(ValueError, match="outside its verified inputs"):
        assemble(inputs)
    assert not inputs.output.exists() and not inputs.commands


def test_uncertain_desktop_tag_is_not_overwritten_or_exported(inputs, monkeypatch):
    original = build.docker

    def docker(*args):
        if args[:2] == ("image", "inspect") and args[2].startswith("ai-station:desktop-"):
            return SimpleNamespace(returncode=1, stdout="", stderr="daemon unavailable")
        return original(*args)

    monkeypatch.setattr(build, "docker", docker)
    with pytest.raises(ValueError, match="absence is uncertain"):
        assemble(inputs)
    assert not inputs.output.exists()
    assert not any(command[:2] in {("image", "tag"), ("image", "save")} for command in inputs.commands)
