from test_account_private_api import accounts as accounts
from test_account_private_api import private_app as private_app
from test_voice_level import enqueue, upload


def test_members_cannot_level_or_enumerate_another_users_voice(accounts):
    admin, alice, bob = accounts
    source = upload(alice)
    assert enqueue(bob, source).status_code == 422
    assert enqueue(admin, source).status_code == 422
    result = enqueue(alice, source)
    assert result.status_code == 202, result.text
    identity = result.json()["id"]
    assert bob.get(f"/api/runs/{identity}").status_code == 404
    assert admin.get(f"/api/runs/{identity}").status_code == 404
