"""Cookie authentication and durable attempt budgets for the account cutover."""

from __future__ import annotations

import hashlib
import math
from datetime import timedelta

from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.accounts import COOKIE, LEGACY_COOKIE, authenticate_cookies
from app.db import control_session_factory, utcnow
from app.models import Setting, UserSession
from app.operator_auth import cookie_max_age, parse_time
from app.private_access import secure_cookie

PUBLIC_GET = {"/api/health", "/api/auth"}
PUBLIC_POST = {"/api/auth/login", "/api/auth/logout", "/api/auth/setup"}


def account_error(_request: Request, error) -> JSONResponse:
    response = JSONResponse({"detail": str(error)}, status_code=error.status)
    response.headers["Cache-Control"] = "no-store"
    return response


def _denied(status: int, message: str) -> JSONResponse:
    response = JSONResponse({"detail": message}, status_code=status)
    response.headers["Cache-Control"] = "no-store"
    return response


def administrator_operation(request: Request) -> bool:
    path, method = request.url.path.rstrip("/"), request.method
    if path.startswith(
        ("/api/admin/", "/api/maintenance", "/api/nodes", "/api/private-access", "/api/runtimes")
    ):
        return True
    if path in {"/api/system/status", "/api/system/diagnostics", "/api/system/gpu-processes"}:
        return True
    if method in {"GET", "HEAD", "OPTIONS"}:
        return False
    if path in {
        "/api/projects",
        "/api/coding/cursor",
        "/api/coding/codex",
        "/api/models/discover",
        "/api/memory/embeddings/prepare",
        "/api/memory/embeddings/setup",
    }:
        return True
    if path.startswith("/api/models/definitions") and not path.endswith("/load"):
        return True
    if path.startswith("/api/llama/") and path.endswith(("/stop", "/restart")):
        return True
    if path.startswith("/api/coding/runs/") and ("/publication" in path or path.endswith("/reconcile")):
        return True
    return False


def inspection_requested(request: Request) -> bool:
    value = request.headers.get("x-ai-station-inspect-all", "false")
    if value not in {"true", "false"}:
        raise HTTPException(400, "Choose an explicit account inspection option")
    if value == "true":
        principal = getattr(request.state, "account_principal", None)
        if principal is None or not principal.is_admin or request.method not in {"GET", "HEAD"}:
            raise HTTPException(403, "Account inspection requires a read-only administrator request")
        return True
    return False


def install_account_access(app) -> None:
    """Enable only once the complete account/private-data cutover is qualified."""
    from app.account_inspection import router as inspection_router
    from app.accounts import AccountError
    from app.accounts_api import router
    from app.data_access import DataAccessError

    if getattr(app.state, "account_access_enabled", False):
        return
    # The built frontend is a catch-all root Mount. Account APIs must retain
    # priority even when this staged profile is installed after app creation.
    from starlette.routing import Mount

    previous = list(app.router.routes)
    app.include_router(router)
    app.include_router(inspection_router)
    added = app.router.routes[len(previous) :]
    index = next(
        (
            index
            for index, route in enumerate(previous)
            if isinstance(route, Mount) and route.path in {"", "/"}
        ),
        len(previous),
    )
    app.router.routes[:] = previous[:index] + added + previous[index:]
    app.add_exception_handler(AccountError, account_error)
    app.add_exception_handler(DataAccessError, lambda _request, error: _denied(403, str(error)))
    app.state.account_access_enabled = True
    app.openapi_schema = None


def attempt_budget(session, *, purpose: str, identity: str) -> None:
    """Commit before verification so failed attempts cannot roll back the budget.

    No caller IP or forwarded header is trusted. A global limit bounds identity
    spraying and a per-identity limit bounds password/TOTP guessing.
    """
    if purpose not in {"login", "security", "admin"}:
        raise ValueError("Unknown account verification purpose")
    now = utcnow()
    key = "account_attempts:" + purpose
    row = session.scalar(select(Setting).where(Setting.key == key).with_for_update())
    value = dict(row.value) if row and isinstance(row.value, dict) else {}
    start = parse_time(value.get("start"))
    if start is None or start + timedelta(seconds=60) <= now:
        start = now
        value = {"start": now.isoformat(), "total": 0, "identities": {}}
    digest = hashlib.sha256(identity.encode()).hexdigest()
    identities = dict(value["identities"])
    if value["total"] >= 100 or identities.get(digest, 0) >= 10:
        raise HTTPException(
            429,
            "Too many verification attempts. Try again shortly.",
            headers={
                "Retry-After": str(max(1, math.ceil((start + timedelta(seconds=60) - now).total_seconds())))
            },
        )
    identities[digest] = identities.get(digest, 0) + 1
    value.update(total=value["total"] + 1, identities=identities)
    if row is None:
        session.add(Setting(key=key, value=value))
    else:
        row.value = value
    session.commit()


def attach_cookie(response: Response, token: str, max_age: int, *, secure: bool) -> None:
    response.delete_cookie(LEGACY_COOKIE, path="/")
    response.set_cookie(
        COOKIE, token, httponly=True, samesite="strict", secure=secure, path="/", max_age=max_age
    )


def clear_cookies(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")
    response.delete_cookie(LEGACY_COOKIE, path="/")


def require_account_session(request: Request) -> JSONResponse | None:
    """Resolve a device; setting a data scope belongs to the request dispatcher."""
    request.state.account_principal = None
    path = request.url.path.rstrip("/") or "/"
    if not path.startswith("/api") or request.method == "OPTIONS":
        return None
    public = (request.method in {"GET", "HEAD"} and path in PUBLIC_GET) or (
        request.method == "POST" and path in PUBLIC_POST
    )
    with control_session_factory()() as session:
        principal = authenticate_cookies(session, dict(request.cookies))
        if principal is not None:
            row = session.get(UserSession, principal.session_id)
            # The original legacy session has no lookup digest. Rotate only its
            # cookie name; retain the original token, issued time and expiry.
            token = (
                request.cookies.get(COOKIE)
                if COOKIE in request.cookies
                else request.cookies.get(LEGACY_COOKIE)
            )
            if token:
                if row.lookup_hash is None:
                    row.lookup_hash = hashlib.sha256(token.encode()).hexdigest()
                request.state.account_cookie_refresh = {
                    "token": token,
                    "max_age": cookie_max_age(row.token_record),
                    "secure": secure_cookie(request.headers.get("host", ""), session),
                }
            request.state.account_principal = principal
        session.commit()
    if principal is None and (COOKIE in request.cookies or LEGACY_COOKIE in request.cookies):
        request.state.account_cookie_invalid = True
    if principal is not None:
        expected = request.headers.get("x-ai-station-account")
        if (
            expected
            and expected != principal.user_id
            and path not in (PUBLIC_GET | PUBLIC_POST) - {"/api/auth/logout"}
        ):
            response = _denied(409, "Account changed. Refresh before continuing.")
            response.headers["X-AI-Station-Account-Changed"] = "true"
            return response
        if path.startswith("/api/operator-auth"):
            return _denied(410, "Use account sign-in and account security settings")
        if administrator_operation(request) and not principal.is_admin:
            return _denied(403, "Administrator access required")
        return None
    if public:
        return None
    response = JSONResponse({"detail": "Account login required"}, status_code=401)
    clear_cookies(response)
    response.headers["Cache-Control"] = "no-store"
    return response


def refresh_account_cookie(request: Request, response: Response) -> None:
    if request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-store"
    if any(
        value.startswith((COOKIE + "=", LEGACY_COOKIE + "="))
        for value in response.headers.getlist("set-cookie")
    ):
        return
    if getattr(request.state, "account_cookie_invalid", False):
        clear_cookies(response)
        return
    refresh = getattr(request.state, "account_cookie_refresh", None)
    if refresh and refresh["max_age"] > 0:
        attach_cookie(response, refresh["token"], refresh["max_age"], secure=refresh["secure"])
