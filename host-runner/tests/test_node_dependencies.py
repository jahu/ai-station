import base64
import json

import pytest
from ai_station_runner.gitops import GitError
from ai_station_runner.node_dependencies import package_manifest, verify_lock


def files(tmp_path):
    package = {"name": "fixture", "private": True, "dependencies": {"@scope/example": "^1.2.3"}}
    lock = {
        "lockfileVersion": 3,
        "packages": {
            "": package,
            "node_modules/@scope/example": {
                "version": "1.2.3",
                "resolved": "https://registry.npmjs.org/@scope/example/-/example-1.2.3.tgz",
                "integrity": "sha512-" + base64.b64encode(b"x" * 64).decode(),
            },
        },
    }
    (tmp_path / "package.json").write_text(json.dumps(package))
    (tmp_path / "package-lock.json").write_text(json.dumps(lock))
    return package, lock


def test_scoped_public_lock_pins_and_hashes_the_complete_inventory(tmp_path):
    files(tmp_path)
    manifest = package_manifest(tmp_path)
    result = verify_lock(tmp_path, manifest)
    assert manifest["specifiers"] == ["@scope/example@^1.2.3"]
    assert result["package_count"] == 1 and len(result["lock_sha256"]) == 64


def test_python_dependencies_keep_precedence_but_tooling_toml_does_not_hide_node(tmp_path):
    from ai_station_runner.dependency_job import node_project

    files(tmp_path)
    assert node_project(tmp_path)
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\nline-length = 100\n")
    assert node_project(tmp_path)
    (tmp_path / "pyproject.toml").write_text('[project]\ndependencies = ["httpx==0.28.1"]\n')
    assert not node_project(tmp_path)
    (tmp_path / "requirements.txt").write_text("httpx==0.28.1\n")
    assert not node_project(tmp_path)


@pytest.mark.parametrize(
    "specifier",
    [
        "file:../other",
        "../escape",
        "https://evil.example/a.tgz",
        "git+https://github.com/a/b",
        "npm:other@1",
        "--registry=evil",
        "workspace:*",
    ],
)
def test_declared_nonregistry_sources_are_refused_before_any_install(tmp_path, specifier):
    package, _ = files(tmp_path)
    package["dependencies"]["@scope/example"] = specifier
    (tmp_path / "package.json").write_text(json.dumps(package))
    with pytest.raises(GitError):
        package_manifest(tmp_path)


@pytest.mark.parametrize(
    "change", ["host", "credentials", "query", "fragment", "path", "digest", "link", "legacy", "mismatch"]
)
def test_lock_downloads_cannot_override_registry_scope_or_integrity(tmp_path, change):
    _, lock = files(tmp_path)
    item = lock["packages"]["node_modules/@scope/example"]
    if change == "host":
        item["resolved"] = item["resolved"].replace("registry.npmjs.org", "127.0.0.1")
    elif change == "credentials":
        item["resolved"] = item["resolved"].replace("https://", "https://secret@")
    elif change == "query":
        item["resolved"] += "?token=secret"
    elif change == "fragment":
        item["resolved"] += "#fragment"
    elif change == "path":
        item["resolved"] = "https://registry.npmjs.org/../../private"
    elif change == "digest":
        item["integrity"] = "sha1-AAAA"
    elif change == "link":
        item["link"] = True
    elif change == "legacy":
        lock["lockfileVersion"] = 2
    else:
        lock["packages"][""]["dependencies"] = {"other": "1.0.0"}
    (tmp_path / "package-lock.json").write_text(json.dumps(lock))
    with pytest.raises(GitError):
        verify_lock(tmp_path, package_manifest(tmp_path))


@pytest.mark.parametrize(
    "unsafe", ["manifest_symlink", "lock_symlink", "modules_symlink", "npmrc", "shrinkwrap"]
)
def test_filesystem_and_configuration_overrides_stay_outside_the_install(tmp_path, unsafe):
    files(tmp_path)
    outside = tmp_path.parent / (tmp_path.name + "-outside")
    outside.write_text("{}")
    if unsafe in {"manifest_symlink", "lock_symlink"}:
        name = "package.json" if unsafe == "manifest_symlink" else "package-lock.json"
        (tmp_path / name).unlink()
        (tmp_path / name).symlink_to(outside)
    elif unsafe == "modules_symlink":
        (tmp_path / "node_modules").symlink_to(tmp_path.parent)
    elif unsafe == "npmrc":
        (tmp_path / ".npmrc").write_text("@scope:registry=http://localhost")
    else:
        (tmp_path / "npm-shrinkwrap.json").write_text("{}")
    with pytest.raises(GitError):
        verify_lock(tmp_path, package_manifest(tmp_path))


@pytest.mark.parametrize("group", ["dependencies", "optionalDependencies", "peerDependencies"])
def test_transitive_source_cannot_bypass_the_registry_lock(tmp_path, group):
    _, lock = files(tmp_path)
    lock["packages"]["node_modules/@scope/example"][group] = {"nested": "git+https://example.com/private.git"}
    (tmp_path / "package-lock.json").write_text(json.dumps(lock))
    with pytest.raises(GitError, match="URLs, VCS"):
        verify_lock(tmp_path, package_manifest(tmp_path))


@pytest.mark.parametrize(
    "version", ["^1.0.0-beta.52", "1.0.0+build.4", ">=1.0.0-alpha <2.0.0 || ^3.0.0", "next"]
)
def test_public_prerelease_ranges_remain_version_specs(tmp_path, version):
    package, _ = files(tmp_path)
    package["dependencies"]["@scope/example"] = version
    (tmp_path / "package.json").write_text(json.dumps(package))
    assert package_manifest(tmp_path)["groups"]["dependencies"]["@scope/example"] == version
