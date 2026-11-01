"""Application overlay boundaries; normal tests execute no Mac code or builds."""

import hashlib
import json
import os
import subprocess
import zipfile

import macos_application_python as build
import pytest
from test_macos_desktop_python import macho


@pytest.fixture
def layer(tmp_path):
    root = tmp_path / "base"
    (root / "bin").mkdir(parents=True)
    (root / "bin/python3.12").write_bytes(macho())
    (root / "dependency").write_text("unchanged native dependency")
    frozen = build.recipe("arm64")
    value = {
        "schema": 1,
        "architecture": "arm64",
        "manifest_sha256": build.fingerprint(frozen),
        "python_version": "3.12.14",
        "minimum_os": frozen["minimum_os"],
        "files": build.file_manifest(root),
    }
    (root / "native-python.json").write_text(json.dumps(value))
    return root


def wheel(path, files=None, *, extra=None):
    files = files or {"__init__.py": b"# reviewed neutral fixture\n"}
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in files.items():
            archive.writestr(build.PACKAGE + name, content)
        archive.writestr(build.DIST + "WHEEL", b"Wheel-Version: 1.0\nTag: py3-none-any\n")
        if extra:
            archive.writestr(*extra)
    return {name: hashlib.sha256(content).hexdigest() for name, content in files.items()}


@pytest.mark.parametrize(
    "extra",
    ["outside.py", "ai_station_runner/../../escape", "ai_station_runner/x.pth", "ai_station_runner/a\\b"],
)
def test_wheel_rejects_code_outside_its_exact_package_and_metadata(tmp_path, extra):
    path = tmp_path / "wheel.whl"
    expected = wheel(path, extra=(extra, b"unexpected"))
    with pytest.raises(ValueError, match="unexpected paths"):
        build.verify_wheel(path, expected)


def test_wheel_must_equal_every_tracked_package_byte(tmp_path):
    path = tmp_path / "wheel.whl"
    expected = wheel(path)
    build.verify_wheel(path, expected)
    expected["__init__.py"] = "0" * 64
    with pytest.raises(ValueError, match="tracked Host Runner"):
        build.verify_wheel(path, expected)


def test_base_tampering_or_another_architecture_cannot_reach_wheel_build(layer):
    build.base_layer(layer, "arm64")
    with pytest.raises(ValueError, match="architecture/recipe"):
        build.base_layer(layer, "x86_64")
    (layer / "dependency").write_text("modified dependency")
    with pytest.raises(ValueError, match="layer changed"):
        build.base_layer(layer, "arm64")


def test_output_inside_base_cannot_recursively_copy_itself_or_change_input(layer):
    before = build.file_manifest(layer)
    with pytest.raises(ValueError, match="outside its verified base"):
        build.prepare(layer / "recursive", layer, "arm64")
    assert build.file_manifest(layer) == before


@pytest.mark.parametrize("marker", [b"*", b"unexpected"])
def test_uv_wheel_output_marker_is_recognized_without_ignoring_other_files(tmp_path, monkeypatch, marker):
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    monkeypatch.setattr(build.shutil, "which", lambda _: "/reviewed/uv")
    monkeypatch.setenv("AI_STATION_LLM_API_KEY", "PRIVATE_FIXTURE_TOKEN")

    def run(argv, *, env, **kwargs):
        assert "AI_STATION_LLM_API_KEY" not in env
        assert argv[0:3] == ["/reviewed/uv", "--no-config", "--no-python-downloads"]
        (wheels / ".gitignore").write_bytes(marker)
        wheel(wheels / "ai_station_runner-0.1.0-py3-none-any.whl")

    monkeypatch.setattr(build.subprocess, "run", run)
    if marker == b"*":
        assert build.build_wheel(tmp_path / "source", wheels, tmp_path).name.endswith("-py3-none-any.whl")
    else:
        with pytest.raises(ValueError, match="output marker"):
            build.build_wheel(tmp_path / "source", wheels, tmp_path)


@pytest.fixture
def repository(tmp_path, monkeypatch):
    root = tmp_path / "repository"
    package = root / "host-runner/ai_station_runner"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("# reviewed fixture\n")
    (root / "host-runner/pyproject.toml").write_text("[project]\nname='ai-station-runner'\nversion='0.1.0'\n")
    (root / ".gitignore").write_text("ignored-secret\n")
    env = {
        "PATH": os.defpath,
        "HOME": str(tmp_path),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
    }
    for command in (
        ["init", "-q"],
        ["add", "."],
        [
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            "Fixture",
        ],
    ):
        subprocess.run(["git", *command], cwd=root, env=env, check=True, capture_output=True)
    monkeypatch.setattr(build, "ROOT", root)
    return root, package


def test_tracked_copy_excludes_ignored_files_and_its_own_build_stage(repository):
    root, package = repository
    (package / "ignored-secret").write_text("PRIVATE_FIXTURE_TOKEN")
    destination = root / ".mac-stage/runner-source"
    destination.mkdir(parents=True)
    head, dirty, files = build.tracked_source(destination)
    assert len(head) == 40 and not dirty
    assert set(files) == {"__init__.py"}
    assert not (destination / "ai_station_runner/ignored-secret").exists()


def test_dirty_sources_require_explicit_private_build_and_are_marked(repository, tmp_path):
    _, package = repository
    (package / "__init__.py").write_text("# private unreviewed fixture\n")
    destination = tmp_path / "private-source"
    with pytest.raises(ValueError, match="Commit reviewed source"):
        build.tracked_source(destination)
    _, dirty, files = build.tracked_source(destination, allow_dirty=True)
    assert dirty and files["__init__.py"] == build.digest(package / "__init__.py")


def test_source_link_cannot_import_external_files_even_in_private_build(repository, tmp_path):
    _, package = repository
    external = tmp_path / "outside-private"
    external.write_text("PRIVATE_FIXTURE_TOKEN")
    (package / "__init__.py").unlink()
    (package / "__init__.py").symlink_to(external)
    with pytest.raises(ValueError, match="canonical regular"):
        build.tracked_source(tmp_path / "source-copy", allow_dirty=True)


@pytest.fixture
def producer(layer, monkeypatch):
    expected = {"__init__.py": hashlib.sha256(b"# reviewed neutral fixture\n").hexdigest()}
    monkeypatch.setattr(build, "tracked_source", lambda *a, **k: ("a" * 40, False, expected))

    def assemble(source, wheels, work):
        path = wheels / "ai_station_runner-0.1.0-py3-none-any.whl"
        wheel(path)
        return path

    def install(python, work, wheels, architecture, minimum):
        assert architecture == "arm64" and minimum == [14, 0]
        assert wheels[0]["name"] == "ai-station-runner" and len(wheels[0]["sha256"]) == 64
        root = python.parent.parent / build.SITE
        package = root / build.PACKAGE
        package.mkdir(parents=True)
        (package / "__init__.py").write_bytes(b"# reviewed neutral fixture\n")
        (root / build.DIST).mkdir()
        (root / build.DIST / "WHEEL").write_text("neutral package metadata")

    monkeypatch.setattr(build, "build_wheel", assemble)
    monkeypatch.setattr(build, "install", install)
    return layer, install


def test_application_copy_installs_runner_without_touching_base_or_claiming_execution(producer, tmp_path):
    layer, _ = producer
    before = build.file_manifest(layer)
    target = tmp_path / "app-python"
    result = build.prepare(target, layer, "arm64")
    assert result["base_inventory_unchanged"] and not result["native_application_executed"]
    assert not result["macos_installer_qualified"] and result["source_head"] == "a" * 40
    assert build.file_manifest(layer) == before
    assert all(build.digest(target / name) == digest for name, digest in before.items())
    assert json.loads((target / "application-python.json").read_text()) == result
    with pytest.raises(ValueError, match="new canonical"):
        build.prepare(target, layer, "arm64")


@pytest.mark.parametrize(
    "modified",
    [
        "dependency",
        "lib/python3.12/site-packages/foreign.py",
        "lib/python3.12/site-packages/ai_station_runner/__init__.py",
    ],
)
def test_install_cannot_replace_dependencies_inject_other_packages_or_change_source(
    producer, tmp_path, monkeypatch, modified
):
    layer, install = producer

    def corrupt(python, *args):
        install(python, *args)
        path = python.parent.parent / modified
        path.write_text("unexpected bytes")

    monkeypatch.setattr(build, "install", corrupt)
    with pytest.raises(ValueError, match="modified|unexpected|differ"):
        build.prepare(tmp_path / "bad", layer, "arm64")
    assert not (tmp_path / "bad").exists()
