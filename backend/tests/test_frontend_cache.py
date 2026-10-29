import pytest
from app.api import local_requests
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient


@pytest.mark.parametrize("path", ["/", "/index.html"])
def test_navigation_html_is_not_reused_after_an_update_but_versioned_assets_can_be_cached(tmp_path, path):
    (tmp_path / "index.html").write_text('<html><script src="/app-qa123.js"></script></html>')
    (tmp_path / "app-qa123.js").write_text('console.log("fixture");')
    frontend = FastAPI()
    frontend.middleware("http")(local_requests)
    frontend.mount("/", StaticFiles(directory=tmp_path, html=True))
    with TestClient(frontend) as client:
        first = client.get(path)
        assert first.status_code == 200
        assert first.headers["cache-control"] == "no-store"
        unchanged = client.get(path, headers={"If-None-Match": first.headers["etag"]})
        assert unchanged.status_code == 304
        assert unchanged.headers["cache-control"] == "no-store"
        assert client.head(path).headers["cache-control"] == "no-store"
        asset = client.get("/app-qa123.js")
        assert asset.status_code == 200
        assert "no-store" not in asset.headers.get("cache-control", "")
