from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app
from test_runtime_setup_api import body
from test_runtime_setup_api import runtime_catalog as runtime_catalog


def test_shared_runtime_facts_do_not_share_private_preparation_history(accounts, runtime_catalog):
    admin, alice, bob = accounts
    assert alice.get("/api/setup/runtimes").json()["can_prepare"] is False
    assert alice.post("/api/setup/runtimes", json=body(runtime_catalog)).status_code == 403
    created = admin.post("/api/setup/runtimes", json=body(runtime_catalog))
    assert created.status_code == 202, created.text
    identity = created.json()["id"]
    path = "/api/setup/runtimes/preparations/" + identity
    assert alice.get("/api/setup/runtimes/preparations").json() == []
    assert bob.get(path).status_code == 404
    assert bob.post(path + "/cancel").status_code == 403
    assert bob.get("/api/runs/" + created.json()["run"]["id"]).status_code == 404
    assert admin.get(path).status_code == 200
