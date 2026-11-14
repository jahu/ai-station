"""Repeated account fixtures must not accumulate FastAPI lifespan wrappers."""

from contextlib import contextmanager

import pytest
from app.api import app
from app.config import clear_settings_cache
from fastapi.testclient import TestClient
from test_account_private_api import private_app


def test_repeated_account_fixture_restoration_preserves_later_application_startup():
    # Reproduce the long-suite consumer without thousands of unrelated API tests.
    # Enter the real fixture: include_router merges lifespans as well as routes.
    activate = contextmanager(private_app.__wrapped__)
    for _ in range(256):
        with pytest.MonkeyPatch.context() as patch, activate(patch):
            assert app.state.account_access_enabled is True
    clear_settings_cache()
    with TestClient(app) as client:
        response = client.get("/api/health")
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
