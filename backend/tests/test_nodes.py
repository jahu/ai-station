from app.api import app
from app.db import session_factory
from app.models import StationNode
from fastapi.testclient import TestClient

PASSWORD = "operator-pass-ok"


def api():
    return TestClient(app)


def test_invitation_requires_operator_password_and_never_stores_the_token():
    client = api()
    denied = client.post("/api/nodes/invitations", json={"name": "Studio GPU"})
    assert denied.status_code == 403
    client.put("/api/operator-auth", json={"password": PASSWORD})
    issued = client.post("/api/nodes/invitations", json={"name": "Studio GPU"})
    assert issued.status_code == 200
    body = issued.json()
    token = body["token"]
    assert token.startswith("aisn_")
    assert body["token_once"] is True
    assert body["status"] == "pending"
    assert body["transport"] == "unpublished"
    assert body["ownership"] == "remote"
    listed = client.get("/api/nodes").json()
    assert [item["id"] for item in listed["items"]] == ["local", body["id"]]
    remote = listed["items"][1]
    assert "token" not in remote and token not in str(listed)
    assert remote["token_issued"] is True
    with session_factory()() as session:
        row = session.get(StationNode, body["id"])
        assert row is not None
        assert row.token_hash and row.token_hash != token
        assert token not in row.token_hash
    assert listed["lan_bind_allowed"] is False


def test_register_consumes_token_without_opening_lan():
    client = api()
    client.put("/api/operator-auth", json={"password": PASSWORD})
    issued = client.post("/api/nodes/invitations", json={"name": "Spare box"}).json()
    token = issued["token"]
    assert client.post("/api/nodes/register", json={"token": "aisn_not-a-real-token"}).status_code == 403
    registered = client.post("/api/nodes/register", json={"token": token, "name": "Spare workstation"})
    assert registered.status_code == 200
    body = registered.json()
    assert body["status"] == "registered"
    assert body["authenticated"] is True
    assert body["name"] == "Spare workstation"
    assert body["transport"] == "unpublished"
    assert body["token_issued"] is False
    assert "token" not in body
    replay = client.post("/api/nodes/register", json={"token": token})
    assert replay.status_code == 403
    listed = client.get("/api/nodes").json()
    assert listed["lan_bind_allowed"] is False
    assert listed["items"][1]["status"] == "registered"
    assert "token" not in listed["items"][1]
    with session_factory()() as session:
        row = session.get(StationNode, body["id"])
        assert row.token_hash == "" and row.token_salt == ""


def test_revoke_blocks_local_and_consumes_pending_invitations():
    client = api()
    client.put("/api/operator-auth", json={"password": PASSWORD})
    assert client.post("/api/nodes/local/revoke").status_code == 403
    issued = client.post("/api/nodes/invitations", json={"name": "Temp"}).json()
    revoked = client.post(f"/api/nodes/{issued['id']}/revoke")
    assert revoked.json()["status"] == "revoked"
    assert client.post("/api/nodes/register", json={"token": issued["token"]}).status_code == 403
    listed = client.get("/api/nodes").json()
    assert listed["items"][1]["status"] == "revoked"
    assert listed["lan_bind_allowed"] is False
