"""Bounded public-registry Node manifests; npm lifecycle scripts stay disabled."""

import base64
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

from ai_station_runner.dependency_manifest import _regular_file
from ai_station_runner.gitops import GitError
from ai_station_runner.public_http import public_addresses

REGISTRY = "https://registry.npmjs.org"
PACKAGE = re.compile(r"^(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*$")
# Permit normal prerelease/build identifiers without admitting URL, Git, local
# path, alias or workspace source syntax. npm validates the range semantics.
VERSION = re.compile(r"^[0-9vVxX*^~<>=][A-Za-z0-9.*^~<>=|+ -]*$")
GROUPS = ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies")
UNSUPPORTED = ("workspaces", "overrides", "resolutions", "bundledDependencies", "bundleDependencies")


def _json(workspace, filename, limit):
    path = _regular_file(workspace, workspace / filename)
    if path.stat().st_size > limit:
        raise GitError(f"{filename} exceeds the dependency size limit")
    payload = path.read_bytes()
    try:
        value = json.loads(payload)
    except (ValueError, UnicodeError) as exc:
        raise GitError(f"{filename} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise GitError(f"{filename} must be a JSON object")
    return value, hashlib.sha256(payload).hexdigest()


def package_name(value):
    if not isinstance(value, str) or len(value) > 214 or not PACKAGE.fullmatch(value):
        raise GitError("Use ordinary public npm package names")
    return value


def declarations(document):
    if any(document.get(key) for key in UNSUPPORTED):
        raise GitError("Node workspaces, overrides and bundled dependencies are not supported")
    groups = {}
    for key in GROUPS:
        values = document.get(key, {})
        if not isinstance(values, dict):
            raise GitError("Node dependencies must be package/version objects")
        for name, version in values.items():
            package_name(name)
            if (
                not isinstance(version, str)
                or not version.strip()
                or len(version) > 200
                or not (
                    VERSION.fullmatch(version)
                    or version in {"latest", "next", "beta", "alpha", "canary", "stable"}
                )
            ):
                raise GitError(
                    "Use npm version ranges or standard tags; URLs, VCS, aliases and local paths are refused"
                )
        groups[key] = values
    if sum(len(values) for values in groups.values()) > 200:
        raise GitError("At most 200 declared npm dependencies are allowed")
    return groups


def package_manifest(workspace: Path):
    workspace = workspace.resolve(strict=True)
    if (workspace / ".npmrc").exists() or (workspace / ".npmrc").is_symlink():
        raise GitError("Project .npmrc overrides are not supported for managed installs")
    if (workspace / "npm-shrinkwrap.json").exists() or (workspace / "npm-shrinkwrap.json").is_symlink():
        raise GitError("npm-shrinkwrap.json overrides are not supported; use a checked package-lock.json")
    modules = workspace / "node_modules"
    if modules.is_symlink() or modules.exists() and not modules.is_dir():
        raise GitError("node_modules must be a directory inside the owned worktree")
    document, digest = _json(workspace, "package.json", 256000)
    groups = declarations(document)
    return {
        "groups": groups,
        "specifiers": [f"{name}@{version}" for values in groups.values() for name, version in values.items()],
        "package_sha256": digest,
    }


def _installed_name(path):
    parts = path.split("/")
    result = None
    while parts:
        if parts.pop(0) != "node_modules" or not parts:
            raise GitError("Lockfile package paths must stay inside node_modules")
        result = parts.pop(0)
        if result.startswith("@"):
            if not parts:
                raise GitError("Incomplete scoped npm package path")
            result += "/" + parts.pop(0)
        package_name(result)
    return result


def verify_lock(workspace: Path, manifest):
    workspace = workspace.resolve(strict=True)
    document, digest = _json(workspace, "package-lock.json", 5 * 1024 * 1024)
    packages = document.get("packages")
    if document.get("lockfileVersion") != 3 or not isinstance(packages, dict) or "" not in packages:
        raise GitError("Managed npm installs require a version 3 package-lock.json")
    if len(packages) > 5001 or not isinstance(packages[""], dict):
        raise GitError("Npm lockfile package inventory is invalid or too large")
    if declarations(packages[""]) != manifest["groups"]:
        raise GitError("package-lock.json does not match the reviewed package.json")
    for path, metadata in packages.items():
        if path == "":
            continue
        name = _installed_name(path)
        if not isinstance(metadata, dict) or metadata.get("link") or metadata.get("inBundle"):
            raise GitError("Npm workspace links and bundled packages are not supported")
        # npm may resolve missing edges even during ci; validate transitive
        # declarations before it can contact a VCS, URL or local source.
        declarations(metadata)
        verify_package(name, metadata)
    return {"lock_sha256": digest, "package_count": len(packages) - 1}


def verify_package(name, metadata):
    version = metadata.get("version")
    resolved = metadata.get("resolved")
    if (
        not isinstance(version, str)
        or not re.fullmatch(r"[0-9][A-Za-z0-9.+-]{0,199}", version)
        or not isinstance(resolved, str)
    ):
        raise GitError("Each npm package needs a pinned version and registry tarball")
    parsed = urlsplit(resolved)
    expected = f"/{name}/-/{name.split('/')[-1]}-{version}.tgz"
    if (
        len(resolved) > 2048
        or parsed.scheme != "https"
        or parsed.netloc != "registry.npmjs.org"
        or parsed.query
        or parsed.fragment
        or unquote(parsed.path) != expected
    ):
        raise GitError("Every npm tarball must come from its canonical public registry URL")
    integrity = metadata.get("integrity", "")
    try:
        valid = (
            isinstance(integrity, str)
            and integrity.startswith("sha512-")
            and len(base64.b64decode(integrity[7:], validate=True)) == 64
        )
    except ValueError:
        valid = False
    if not valid:
        raise GitError("Every npm tarball needs a SHA-512 integrity digest")


def confirm_registry():
    public_addresses("registry.npmjs.org")
