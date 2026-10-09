from pathlib import Path

from app.api import app
from app.config import clear_settings_cache
from app.db import session_factory
from app.models import Setting
from app.operator_auth import ALGORITHM, SETUP_KEY, lan_bind_decision, refuse_non_loopback_bind
from fastapi.testclient import TestClient

PASSWORD = "operator-pass-ok"


def api():
    return TestClient(app)


def test_operator_password_is_stored_hashed_and_never_returned():
    client = api()
    status = client.get("/api/operator-auth").json()
    assert status["configured"] is False
    assert status["lan_bind_allowed"] is False
    assert status["lan_exposure"] == "disabled"
    assert "hash" not in status and "salt" not in status
    assert "password" not in status

    too_short = client.put("/api/operator-auth", json={"password": "short-pass"})
    assert too_short.status_code == 422

    saved = client.put("/api/operator-auth", json={"password": PASSWORD})
    assert saved.status_code == 200
    body = saved.json()
    assert body["configured"] is True
    assert body["lan_bind_allowed"] is False
    assert PASSWORD not in saved.text
    assert "hash" not in body and "salt" not in body

    listed = client.get("/api/operator-auth").json()
    assert listed["configured"] is True
    assert PASSWORD not in str(listed)

    with session_factory()() as session:
        record = session.get(Setting, SETUP_KEY)
        assert record is not None
        assert record.value["algorithm"] == ALGORITHM
        assert record.value["hash"] != PASSWORD
        assert record.value["salt"]
        assert PASSWORD not in str(record.value)

    denied = client.put("/api/operator-auth", json={"password": "replacement-ok"})
    assert denied.status_code == 403
    wrong = client.put(
        "/api/operator-auth",
        json={"password": "replacement-ok", "current_password": "wrong-password"},
    )
    assert wrong.status_code == 403
    rotated = client.put(
        "/api/operator-auth",
        json={"password": "replacement-ok", "current_password": PASSWORD},
    )
    assert rotated.json()["configured"] is True

    assert client.post("/api/operator-auth/clear", json={"current_password": PASSWORD}).status_code == 403
    cleared = client.post("/api/operator-auth/clear", json={"current_password": "replacement-ok"})
    assert cleared.json()["configured"] is False
    with session_factory()() as session:
        assert session.get(Setting, SETUP_KEY) is None


def test_non_loopback_bind_is_refused_even_with_operator_password(monkeypatch):
    unbound = lan_bind_decision("0.0.0.0", auth_configured=False)
    assert unbound["allowed"] is False and unbound["lan_exposure"] == "forbidden"
    configured = lan_bind_decision("10.0.0.8", auth_configured=True)
    assert configured["allowed"] is False and configured["lan_exposure"] == "unpublished"
    loopback = lan_bind_decision("127.0.0.1", auth_configured=False)
    assert loopback["allowed"] is True and loopback["lan_exposure"] == "disabled"

    api().put("/api/operator-auth", json={"password": PASSWORD})
    monkeypatch.setenv("AI_STATION_BIND_HOST", "0.0.0.0")
    clear_settings_cache()
    try:
        try:
            refuse_non_loopback_bind(None)
        except RuntimeError as exc:
            assert "operator authentication" in str(exc)
        else:
            raise AssertionError("non-loopback bind must fail closed")
        with session_factory()() as session:
            try:
                refuse_non_loopback_bind(session)
            except RuntimeError as exc:
                assert "not enabled" in str(exc)
            else:
                raise AssertionError("configured auth must not open LAN")
    finally:
        monkeypatch.delenv("AI_STATION_BIND_HOST", raising=False)
        clear_settings_cache()


def test_nodes_list_is_local_host_runner_only():
    client = api()
    payload = client.get("/api/nodes").json()
    assert [item["id"] for item in payload["items"]] == ["local"]
    assert payload["items"][0]["transport"] == "unix-socket"
    assert payload["remote_registration"] == "loopback-token"
    assert payload["lan_bind_allowed"] is False
    assert payload["lan_exposure"] == "disabled"
    assert "unpublished" in payload["summary"].lower()


def test_loopback_session_gates_api_after_password_without_opening_lan():
    client = api()
    guest = api()
    assert client.get("/api/nodes").status_code == 200
    saved = client.put("/api/operator-auth", json={"password": PASSWORD})
    assert saved.status_code == 200
    body = saved.json()
    assert body["session_required"] is True
    assert body["authenticated"] is True
    assert body["session_scope"] == "loopback"
    assert body["lan_bind_allowed"] is False
    assert body["lan_exposure"] == "disabled"
    assert "ais_operator" in saved.cookies
    assert client.get("/api/nodes").status_code == 200
    denied = guest.get("/api/nodes")
    assert denied.status_code == 401
    assert denied.json()["detail"] == "Operator login required"
    assert guest.post("/api/nodes/register", json={"token": "aisn_x"}).status_code == 401
    public = guest.get("/api/operator-auth").json()
    assert public["session_required"] is True
    assert public["authenticated"] is False
    assert guest.get("/api/health").status_code == 200
    assert guest.post("/api/operator-auth/login", json={"password": "wrong-password"}).status_code == 403
    login = guest.post("/api/operator-auth/login", json={"password": PASSWORD})
    assert login.status_code == 200
    assert login.json()["authenticated"] is True
    assert login.json()["lan_bind_allowed"] is False
    assert guest.get("/api/nodes").status_code == 200
    assert guest.post("/api/operator-auth/logout").status_code == 200
    assert guest.get("/api/nodes").status_code == 401
    assert guest.get("/api/health").status_code == 200


def test_compose_publish_addresses_stay_on_loopback():
    root = Path(__file__).resolve().parents[2]
    compose = (root / "compose.yaml").read_text()
    dev = (root / "compose.dev.yaml").read_text()
    assert '"127.0.0.1:${AI_STATION_PORT:-8765}:8765"' in compose
    assert "0.0.0.0:" not in compose and "0.0.0.0:" not in dev
    assert "127.0.0.1:5173:5173" in dev
