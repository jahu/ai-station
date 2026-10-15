"""Fetch bounded, pinned public npm metadata; never follow dependency URLs."""

import hashlib
import json
from urllib.parse import quote

import httpx

from ai_station_runner.gitops import GitError
from ai_station_runner.node_dependencies import declarations, package_name, verify_package
from ai_station_runner.public_http import pinned_request, public_addresses

MAX_METADATA = 8 * 1024 * 1024
MAX_VERSIONS = 10000
REGISTRY = "https://registry.npmjs.org"


def metadata_url(name):
    return REGISTRY + "/" + quote(package_name(name), safe="@").replace("%2F", "%2f")


def checked_metadata(name, document):
    if (
        not isinstance(document, dict)
        or document.get("name") != name
        or not isinstance(document.get("versions"), dict)
        or len(document["versions"]) > MAX_VERSIONS
        or not isinstance(document.get("dist-tags", {}), dict)
    ):
        raise GitError("Invalid public npm package metadata")
    versions = {}
    for version, record in document["versions"].items():
        if not isinstance(record, dict) or record.get("name", name) != name:
            continue
        dist = record.get("dist")
        if not isinstance(dist, dict):
            continue
        try:
            # Published packages' development dependencies are not installed.
            # Do not make those sources available to the offline resolver.
            declarations({key: value for key, value in record.items() if key != "devDependencies"})
            # Reuse exactly the installation lock's source/integrity contract.
            verify_package(
                name,
                {"version": version, "resolved": dist.get("tarball"), "integrity": dist.get("integrity")},
            )
        except GitError:
            continue
        keep = (
            "name",
            "version",
            "dependencies",
            "optionalDependencies",
            "peerDependencies",
            "peerDependenciesMeta",
            "engines",
            "os",
            "cpu",
            "bin",
            "deprecated",
            "license",
            "hasInstallScript",
            "hasShrinkwrap",
        )
        versions[version] = {key: value for key, value in record.items() if key in keep}
        versions[version].update(
            name=name,
            version=version,
            dist={
                "tarball": dist["tarball"],
                "integrity": dist["integrity"],
            },
        )
    if not versions:
        raise GitError("No npm versions satisfy the public source and integrity policy")
    tags = {
        tag: version
        for tag, version in document.get("dist-tags", {}).items()
        if isinstance(version, str) and version in versions
    }
    return {"name": name, "versions": versions, "dist-tags": tags}


def fetch_metadata(name, *, timeout=20):
    name = package_name(name)
    url = metadata_url(name)
    addresses = public_addresses("registry.npmjs.org")
    target, headers, extensions = pinned_request(url, addresses[0])
    headers["Accept"] = "application/vnd.npm.install-v1+json"
    with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False) as client:
        with client.stream("GET", target, headers=headers, extensions=extensions) as response:
            if response.status_code != 200:
                raise GitError(f"Public npm metadata request failed ({response.status_code})")
            payload = bytearray()
            for chunk in response.iter_bytes():
                payload.extend(chunk)
                if len(payload) > MAX_METADATA:
                    raise GitError("Public npm metadata exceeds its size limit")
    try:
        document = json.loads(payload)
    except (ValueError, UnicodeError) as exc:
        raise GitError("Public npm metadata is not valid JSON") from exc
    checked = checked_metadata(name, document)
    return checked, {
        "name": name,
        "metadata_sha256": hashlib.sha256(payload).hexdigest(),
        "metadata_bytes": len(payload),
        "accepted_versions": len(checked["versions"]),
        "excluded_versions": len(document["versions"]) - len(checked["versions"]),
    }
