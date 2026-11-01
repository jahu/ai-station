"""Developer image-build boundaries. No Docker, network or target code in normal tests."""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import build_control_plane_image as build
import pytest

SOURCE = b"FROM node:22-alpine AS frontend\nRUN npm ci\nFROM python:3.12-slim\nUSER 1000:1000\n"
IMAGE = "sha256:" + "a" * 64


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    (tmp_path / "Dockerfile").write_bytes(SOURCE)
    state = {
        "calls": [],
        "built": False,
        "existing": False,
        "dirty": False,
        "failure": None,
        "platform": "linux/arm64",
        "image": {"Id": IMAGE, "Os": "linux", "Architecture": "arm64", "Config": {"User": "1000:1000"}},
    }
    monkeypatch.setattr(build, "ROOT", tmp_path)

    def git(argv, **kwargs):
        return ("dirty" if state["dirty"] else "") if "status" in argv else "1" * 40

    def docker(*args):
        if state["failure"] == "connection":
            return SimpleNamespace(returncode=1, stderr="Docker context not found")
        present = state["existing"] or state["built"]
        return SimpleNamespace(
            returncode=0 if present else 1,
            stderr="" if present else "Error response from daemon: No such image: ai-station:fixture",
            stdout=json.dumps([state["image"]]),
        )

    def run(argv, **kwargs):
        state["calls"].append((argv, kwargs))
        if state["failure"] == "build":
            raise subprocess.CalledProcessError(1, argv)
        state["built"] = True
        Path(argv[argv.index("--metadata-file") + 1]).write_text(
            json.dumps({"containerimage.config.digest": IMAGE})
        )

    monkeypatch.setattr(build, "docker", docker)
    monkeypatch.setattr(
        build, "subprocess", SimpleNamespace(check_output=git, run=run, STDOUT=subprocess.STDOUT)
    )
    state["output"] = tmp_path / "proof"
    state["run"] = lambda: build.build(
        state["output"],
        platform=state["platform"],
        builder="ai-station-qa",
        tag="ai-station:fixture",
        buildx=tmp_path / "verified-buildx",
    )
    return state


def test_generated_frontend_is_native_and_all_other_canonical_bytes_are_retained():
    assert build.recipe(SOURCE) == SOURCE.replace(b"FROM node:", b"FROM --platform=$BUILDPLATFORM node:", 1)
    with pytest.raises(ValueError, match="Review"):
        build.recipe(SOURCE.replace(b"node:22", b"node:24"))


@pytest.mark.parametrize("architecture", ["amd64", "arm64"])
def test_only_new_local_image_is_built_and_verified(fixture, architecture):
    fixture["platform"] = "linux/" + architecture
    fixture["image"]["Architecture"] = architecture
    result = fixture["run"]()
    argv, kwargs = fixture["calls"][0]
    assert "--load" in argv and "--push" not in argv
    assert argv[argv.index("--platform") + 1] == fixture["platform"]
    assert kwargs["input"] == build.recipe(SOURCE)
    assert (fixture["output"].parent / "Dockerfile").read_bytes() == SOURCE
    assert result["image_id"] == IMAGE and result["status"] == "built_image_only"
    assert not result["runtime_qualified"] and not result["consumer_installer_qualified"]


@pytest.mark.parametrize("condition", ["existing", "dirty", "connection"])
def test_existing_tags_dirty_source_or_uncertain_engine_do_not_start_a_build(fixture, condition):
    if condition == "connection":
        fixture["failure"] = condition
    else:
        fixture[condition] = True
    with pytest.raises((ValueError, RuntimeError)):
        fixture["run"]()
    assert not fixture["calls"] and not fixture["output"].exists()


@pytest.mark.parametrize("change", ["architecture", "root", "missing_identity"])
def test_mismatched_image_keeps_inspection_proof_instead_of_qualification(fixture, change):
    if change == "architecture":
        fixture["image"]["Architecture"] = "amd64"
    elif change == "root":
        fixture["image"]["Config"]["User"] = "0"
    else:
        fixture["image"]["Id"] = None
    with pytest.raises(ValueError):
        fixture["run"]()
    assert json.loads((fixture["output"] / "build.json").read_text())["status"] == "inspection_required"


def test_failed_build_cannot_implicitly_replay_a_retained_proof(fixture):
    fixture["failure"] = "build"
    with pytest.raises(subprocess.CalledProcessError):
        fixture["run"]()
    assert json.loads((fixture["output"] / "build.json").read_text())["status"] == "inspection_required"
    with pytest.raises(FileExistsError):
        fixture["run"]()
    assert len(fixture["calls"]) == 1
