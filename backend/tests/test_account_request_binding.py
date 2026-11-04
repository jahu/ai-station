"""A stale tab cannot read/write as the newly signed-in browser account."""

from app.account_http import install_account_access
from app.api import app
from fastapi.testclient import TestClient
from starlette.staticfiles import StaticFiles


def test_expected_account_binding_rejects_stale_requests_without_revoking_the_new_device(
    tmp_path, monkeypatch
):
    from app.config import clear_settings_cache

    monkeypatch.setenv("AI_STATION_ACCESS_PROFILE", "accounts")
    clear_settings_cache()
    routes, handlers = list(app.router.routes), dict(app.exception_handlers)
    previous = getattr(app.state, "account_access_enabled", False)
    app.middleware_stack = None
    app.mount("/", StaticFiles(directory=tmp_path, html=True), name="synthetic-built-frontend")
    install_account_access(app)
    try:
        browser = TestClient(app, base_url="http://127.0.0.1:8765", client=("127.0.0.1", 50000))
        owner = browser.post(
            "/api/auth/setup", json={"username": "Owner", "password": "synthetic owner password"}
        ).json()["user"]
        browser.post("/api/admin/users", json={"username": "Member", "password": "synthetic user password"})
        member = browser.post(
            "/api/auth/login", json={"username": "Member", "password": "synthetic user password"}
        ).json()["user"]
        stale = {"X-AI-Station-Account": owner["id"]}
        for method, path, body in [
            ("GET", "/api/runs", None),
            ("POST", "/api/testing/runs", {"title": "Wrong account"}),
            ("POST", "/api/auth/logout", None),
        ]:
            result = browser.request(method, path, headers=stale, json=body)
            assert result.status_code == 409 and result.headers["X-AI-Station-Account-Changed"] == "true"
        status = browser.get("/api/auth").json()
        assert status["authenticated"] and status["user"]["id"] == member["id"]
        assert browser.get("/api/runs").json() == []
        assert browser.get("/api/runs", headers={"X-AI-Station-Account": member["id"]}).status_code == 200
    finally:
        app.router.routes, app.exception_handlers = routes, handlers
        app.state.account_access_enabled = previous
        app.middleware_stack, app.openapi_schema = None, None
