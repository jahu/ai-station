"""Every registered API operation crosses authentication before body validation."""

from types import SimpleNamespace

from app.account_http import PUBLIC_GET, PUBLIC_POST, administrator_operation
from test_account_private_api import accounts as accounts
from test_account_private_api import browser
from test_account_private_api import private_app as private_app


def operations(application):
    for path, methods in application.openapi()["paths"].items():
        if path.startswith("/api/"):
            for method in methods:
                if method.upper() in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                    yield method.upper(), path


def concrete(path):
    import re

    return re.sub(r"\{[^}]+\}", "00000000-0000-0000-0000-000000000000", path)


def test_all_api_operations_authenticate_anonymous_requests_before_dispatch(private_app):
    anonymous = browser(private_app)
    checked = 0
    for method, path in operations(private_app):
        if (method == "GET" and path in PUBLIC_GET) or (method == "POST" and path in PUBLIC_POST):
            continue
        response = anonymous.request(method, concrete(path))
        assert response.status_code == 401, (method, path, response.status_code, response.text[:120])
        assert response.headers["cache-control"] == "no-store"
        checked += 1
    assert checked >= 200


def test_members_cannot_dispatch_any_registered_administrator_operation(accounts, private_app):
    _, member, _ = accounts
    checked = 0
    for method, path in operations(private_app):
        request = SimpleNamespace(method=method, url=SimpleNamespace(path=concrete(path)))
        if not administrator_operation(request):
            continue
        response = member.request(method, concrete(path))
        assert response.status_code == 403, (method, path, response.status_code, response.text[:120])
        checked += 1
    assert checked >= 20
