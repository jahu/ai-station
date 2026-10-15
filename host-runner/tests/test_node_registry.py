import base64
import json

import pytest
from ai_station_runner.gitops import GitError
from ai_station_runner.node_registry import checked_metadata, fetch_metadata, metadata_url


def document(name="demo"):
    return {
        "name": name,
        "dist-tags": {"latest": "1.0.0"},
        "versions": {
            "1.0.0": {
                "name": name,
                "version": "1.0.0",
                "dependencies": {"nested": "^2.0.0"},
                "dist": {
                    "tarball": f"https://registry.npmjs.org/{name}/-/{name.split('/')[-1]}-1.0.0.tgz",
                    "integrity": "sha512-" + base64.b64encode(b"x" * 64).decode(),
                },
                "scripts": {"prepare": "must never execute"},
            }
        },
    }


@pytest.mark.parametrize("unsafe", ["git", "url", "local", "digest", "tarball", "name", "link"])
def test_only_checked_registry_versions_enter_offline_cache(unsafe):
    data = document()
    bad = json.loads(json.dumps(data["versions"]["1.0.0"]))
    bad["version"] = "2.0.0"
    bad["dist"]["tarball"] = "https://registry.npmjs.org/demo/-/demo-2.0.0.tgz"
    if unsafe in {"git", "url", "local"}:
        bad["dependencies"] = {
            "nested": {
                "git": "git+https://example.com/repo",
                "url": "http://127.0.0.1/secret",
                "local": "file:../other",
            }[unsafe]
        }
    elif unsafe == "digest":
        bad["dist"]["integrity"] = "sha1-AAAA"
    elif unsafe == "tarball":
        bad["dist"]["tarball"] = "https://example.com/a.tgz"
    elif unsafe == "name":
        bad["name"] = "other"
    else:
        bad["workspaces"] = ["../other"]
    data["versions"]["2.0.0"] = bad
    data["dist-tags"]["latest"] = "2.0.0"
    checked = checked_metadata("demo", data)
    assert list(checked["versions"]) == ["1.0.0"]
    assert "scripts" not in checked["versions"]["1.0.0"]
    assert "latest" not in checked["dist-tags"]
    del data["versions"]["1.0.0"]
    with pytest.raises(GitError, match="No npm versions"):
        checked_metadata("demo", data)


@pytest.mark.parametrize(
    "bad", [None, [], {"name": "other", "versions": {}}, {"name": "demo", "versions": []}]
)
def test_invalid_metadata_is_not_cached(bad):
    with pytest.raises(GitError):
        checked_metadata("demo", bad)


def test_scoped_urls_are_canonical_and_cannot_inject_a_path():
    assert metadata_url("@scope/demo") == "https://registry.npmjs.org/@scope%2fdemo"
    for name in ["../secret", "demo?token=x", "demo/-/payload.tgz", "demo%2fother"]:
        with pytest.raises(GitError):
            metadata_url(name)


@pytest.mark.parametrize("status,oversized", [(200, False), (302, False), (200, True)])
def test_registry_fetch_pins_public_ip_and_tls_authority_without_redirects(monkeypatch, status, oversized):
    from ai_station_runner import node_registry

    payload = json.dumps(document()).encode()
    requests = []
    monkeypatch.setattr(node_registry, "public_addresses", lambda host: ["93.184.216.34"])
    if oversized:
        monkeypatch.setattr(node_registry, "MAX_METADATA", 3)

    class Response:
        status_code = status

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def iter_bytes(self):
            yield payload

    class Client:
        def __init__(self, **kwargs):
            assert kwargs == {"timeout": 20, "follow_redirects": False, "trust_env": False}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def stream(self, method, url, **kwargs):
            requests.append((method, str(url), kwargs))
            return Response()

    monkeypatch.setattr(node_registry.httpx, "Client", Client)
    if status != 200 or oversized:
        with pytest.raises(GitError):
            fetch_metadata("demo")
    else:
        data, provenance = fetch_metadata("demo")
        assert data["name"] == "demo" and provenance["accepted_versions"] == 1
        assert len(provenance["metadata_sha256"]) == 64
    method, url, kwargs = requests[0]
    assert method == "GET" and url == "https://93.184.216.34/demo"
    assert kwargs["headers"]["Host"] == "registry.npmjs.org"
    assert kwargs["extensions"] == {"sni_hostname": "registry.npmjs.org"}


def test_published_development_dependencies_are_not_installed_or_cached():
    data = document()
    data["versions"]["1.0.0"]["devDependencies"] = {"unpublished-tool": "file:../tool"}
    assert "devDependencies" not in checked_metadata("demo", data)["versions"]["1.0.0"]
