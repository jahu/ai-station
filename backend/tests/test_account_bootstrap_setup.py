"""First-admin proof crosses the Docker bridge without trusting private peers."""

import os
import subprocess
import sys
from urllib.parse import parse_qs, urlsplit

import pytest
from app.bootstrap_setup import RELATIVE_PATH, ensure_setup_proof, setup_url, valid_setup_proof
from app.config import get_settings
from app.db import control_session_factory
from fastapi.testclient import TestClient
from test_accounts_api import PASSWORD
from test_accounts_api import account_app as account_app


def local_proof():
    with control_session_factory()() as session:
        ensure_setup_proof(session)
        url = setup_url(session, "http://127.0.0.1:8765")
    assert not urlsplit(url).query
    return parse_qs(urlsplit(url).fragment.split("?", 1)[1])["setup_token"][0]


def bridge_browser(app, host="127.0.0.1"):
    return TestClient(app, base_url=f"http://{host}:8765", client=("172.18.0.1", 50000))


def test_bridge_setup_needs_private_proof_and_consumes_it_once(account_app):
    proof = local_proof()
    path = get_settings().data_dir / RELATIVE_PATH
    assert path.stat().st_mode & 0o077 == 0
    browser = bridge_browser(account_app)
    body = {"username": "Owner", "password": PASSWORD}
    assert browser.post("/api/auth/setup", json=body).status_code == 403
    assert browser.post("/api/auth/setup", json={**body, "local_setup_token": "x" * 43}).status_code == 403
    status = browser.get("/api/auth")
    assert status.json()["setup_link_required"] is True
    assert proof not in status.text
    created = browser.post("/api/auth/setup", json={**body, "local_setup_token": proof})
    assert created.status_code == 201, created.text
    assert created.json()["user"]["is_admin"] and not created.json()["setup_required"]
    assert proof not in created.text and not path.exists()
    assert browser.get("/api/admin/users").status_code == 200
    assert browser.get("/api/auth").json()["setup_link_required"] is False
    assert browser.post("/api/auth/setup", json={**body, "local_setup_token": proof}).status_code != 201
    with control_session_factory()() as session:
        ensure_setup_proof(session)
        assert not path.exists() and not valid_setup_proof(session, proof)
        assert setup_url(session, "http://127.0.0.1:8765") == "http://127.0.0.1:8765"


@pytest.mark.parametrize("case", ["public_host", "private_proxy"])
def test_proof_does_not_authorize_setup_on_public_host_or_configured_proxy(account_app, monkeypatch, case):
    proof = local_proof()
    if case == "private_proxy":
        monkeypatch.setattr("app.accounts_api.private_access_enabled", lambda _: True)
    browser = bridge_browser(account_app, "untrusted.example" if case == "public_host" else "127.0.0.1")
    response = browser.post(
        "/api/auth/setup", json={"username": "Owner", "password": PASSWORD, "local_setup_token": proof}
    )
    assert response.status_code in {400, 403}
    assert proof not in response.text


@pytest.mark.parametrize("case", ["readable_by_others", "symlink"])
def test_unsafe_setup_file_is_rejected_without_replacement_or_external_file_changes(
    account_app, tmp_path, case
):
    proof = local_proof()
    path = get_settings().data_dir / RELATIVE_PATH
    external = tmp_path / "unrelated-private-file"
    external.write_text("Unrelated host data")
    if case == "readable_by_others":
        path.chmod(0o644)
    else:
        path.unlink()
        path.symlink_to(external)
    with control_session_factory()() as session:
        assert not valid_setup_proof(session, proof)
        with pytest.raises(ValueError):
            ensure_setup_proof(session)
    assert external.read_text() == "Unrelated host data"
    assert path.is_symlink() if case == "symlink" else path.read_text() == proof


def test_local_console_exports_only_a_fragment_link_and_rejects_external_destinations():
    proof = local_proof()
    result = subprocess.run(
        [sys.executable, "-m", "app.bootstrap_setup", "--url", "http://127.0.0.1:8765"],
        capture_output=True,
        text=True,
        env=dict(os.environ),
        check=True,
    )
    assert urlsplit(result.stdout.strip()).query == ""
    assert result.stdout.strip().endswith("/#/?setup_token=" + proof)
    assert proof not in result.stderr
    with control_session_factory()() as session:
        with pytest.raises(ValueError, match="local"):
            setup_url(session, "https://untrusted.example")
