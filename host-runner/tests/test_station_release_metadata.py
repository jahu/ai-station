from copy import deepcopy

import pytest
from ai_station_runner.station_release_metadata import (
    API,
    WEB,
    admit_release,
    update_package,
    version_number,
)


@pytest.fixture
def release():
    version = "0.5.1"
    name = f"AI-Station-{version}-windows-x64-Setup.exe"
    return {
        "id": 123,
        "tag_name": "v" + version,
        "draft": False,
        "prerelease": False,
        "html_url": f"{WEB}/releases/tag/v{version}",
        "published_at": "2026-11-09T12:00:00Z",
        "body": "Public release notes",
        "assets": [
            {
                "id": 456,
                "name": name,
                "state": "uploaded",
                "size": 1024,
                "digest": "sha256:" + "a" * 64,
                "url": f"{API}/releases/assets/456",
                "browser_download_url": f"{WEB}/releases/download/v{version}/{name}",
            }
        ],
    }


def test_exact_official_package_is_frozen_and_numeric_ordering_is_used(release):
    snapshot = admit_release(release)
    package = update_package(snapshot, "0.4.0", "windows-x64")
    assert package["id"] == 456 and package["sha256"] == "a" * 64
    assert package["size_bytes"] == 1024 and len(snapshot["fingerprint"]) == 64
    assert version_number("0.10.0") > version_number("0.9.99")
    release["body"] = "Edited notes cannot authorize a different package"
    assert admit_release(release)["fingerprint"] == snapshot["fingerprint"]
    release["assets"][0]["digest"] = "sha256:" + "b" * 64
    assert admit_release(release)["fingerprint"] != snapshot["fingerprint"]


@pytest.mark.parametrize(
    "value", [None, True, "v1.0.0", "1.0", "01.0.0", "1.0.0-rc1", "65536.0.0", "1.0.0\n"]
)
def test_ambiguous_or_nonstable_versions_are_not_update_authority(value):
    with pytest.raises(ValueError):
        version_number(value)


@pytest.mark.parametrize(
    "field,value",
    [
        ("draft", True),
        ("prerelease", True),
        ("id", True),
        ("html_url", "https://example.org/release"),
        ("published_at", "2026-11-09"),
    ],
)
def test_nonpublic_or_unbound_release_is_rejected(release, field, value):
    release[field] = value
    with pytest.raises(ValueError):
        admit_release(release)


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", True),
        ("size", True),
        ("size", 0),
        ("size", 5 * 1024**3),
        ("digest", None),
        ("digest", "sha256:bad"),
        ("state", "new"),
        ("url", "https://api.github.com/repos/other/repo/releases/assets/456"),
        ("browser_download_url", "https://github.com.evil.example/package.exe"),
    ],
)
def test_package_cannot_override_publisher_identity_or_integrity(release, field, value):
    release["assets"][0][field] = value
    with pytest.raises(ValueError):
        admit_release(release)


def test_ambiguous_packages_and_unsupported_platforms_do_not_select_a_fallback(release):
    release["assets"].append(deepcopy(release["assets"][0]))
    with pytest.raises(ValueError, match="ambiguous"):
        admit_release(release)
    release["assets"].pop()
    snapshot = admit_release(release)
    for platform in ("linux-amd64", "darwin-arm64"):
        with pytest.raises(ValueError):
            update_package(snapshot, "0.4.0", platform)
    for version in ("0.5.1", "0.6.0"):
        with pytest.raises(ValueError, match="not newer"):
            update_package(snapshot, version, "windows-x64")
