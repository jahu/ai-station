"""Lost acknowledgements cannot create or signal unrelated preparation work."""

import copy
from urllib.parse import unquote

import httpx
import pytest
from ai_station_runner.motion_prepare_owner import OwnershipUncertain, create, filename, stop_and_remove
from ai_station_runner.motion_prepare_plan import stage_spec
from test_motion_prepare_plan import owned as owned


class Docker:
    def __init__(self, owned, folder, *, lose_ack=False):
        self.owned, self.folder = owned, folder
        self.value = None
        self.daemon, self.lose_ack = "daemon-1", lose_ack
        self.calls = []

    def response(self, code, data=None):
        return httpx.Response(code, json=data or {}, request=httpx.Request("GET", "http://docker"))

    def get(self, path):
        if path == "/info":
            return self.response(200, {"ID": self.daemon})
        if path.startswith("/images/"):
            return self.response(200, copy.deepcopy(self.owned[1]))
        coordinate = unquote(path).removeprefix("/containers/").removesuffix("/json")
        if self.value and coordinate in {self.value["Id"], self.value["Name"].lstrip("/")}:
            return self.response(200, copy.deepcopy(self.value))
        return self.response(404)

    def post(self, path, *, params=None, json=None):
        self.calls.append(("POST", path))
        if path == "/containers/create":
            assert (self.folder / filename(self.owned[2])).exists(), "Intent must precede creation"
            self.value = copy.deepcopy(self.owned[0])
            self.value.update(Name="/" + params["name"], State={"Running": True})
            assert json == stage_spec(*self.owned[2:])
            if self.lose_ack:
                self.lose_ack = False
                raise httpx.ReadTimeout("Synthetic lost create acknowledgement")
            return self.response(201, {"Id": self.value["Id"]})
        assert path == "/containers/" + self.value["Id"] + "/stop"
        self.value["State"]["Running"] = False
        return self.response(204)

    def delete(self, path, *, params):
        self.calls.append(("DELETE", path))
        assert path == "/containers/" + self.value["Id"]
        assert not self.value["State"]["Running"]
        assert params == {"force": "false", "v": "false"}
        self.value = None
        return self.response(204)


def arguments(owned, tmp_path):
    return (tmp_path, *owned[2:], "daemon-1")


def test_create_and_cleanup_are_idempotent_and_exactly_owned(owned, tmp_path):
    api = Docker(owned, tmp_path)
    first = create(api, *arguments(owned, tmp_path))
    assert create(api, *arguments(owned, tmp_path)) == first
    assert api.calls == [("POST", "/containers/create")]
    assert stop_and_remove(api, *arguments(owned, tmp_path))
    assert stop_and_remove(api, *arguments(owned, tmp_path))
    assert api.value is None
    with pytest.raises(OwnershipUncertain):
        create(api, *arguments(owned, tmp_path))
    assert sum(path == "/containers/create" for _, path in api.calls) == 1


def test_lost_ack_adopts_original_without_another_create(owned, tmp_path):
    api = Docker(owned, tmp_path, lose_ack=True)
    with pytest.raises(httpx.ReadTimeout):
        create(api, *arguments(owned, tmp_path))
    original = api.value["Id"]
    saved = create(api, *arguments(owned, tmp_path))
    assert saved["container_id"] == original
    assert api.calls == [("POST", "/containers/create")]


def test_lost_ack_absence_is_not_permission_to_recreate(owned, tmp_path):
    api = Docker(owned, tmp_path, lose_ack=True)
    with pytest.raises(httpx.ReadTimeout):
        create(api, *arguments(owned, tmp_path))
    api.value = None
    with pytest.raises(OwnershipUncertain):
        create(api, *arguments(owned, tmp_path))
    assert api.calls == [("POST", "/containers/create")]


def test_stop_after_lost_ack_freezes_original_id_before_signaling(owned, tmp_path):
    api = Docker(owned, tmp_path, lose_ack=True)
    with pytest.raises(httpx.ReadTimeout):
        create(api, *arguments(owned, tmp_path))
    assert stop_and_remove(api, *arguments(owned, tmp_path))
    assert api.value is None
    assert sum(path == "/containers/create" for _, path in api.calls) == 1


@pytest.mark.parametrize("change", ["daemon", "privileges", "base"])
def test_changed_ownership_never_receives_a_stop_or_remove(owned, tmp_path, change):
    api = Docker(owned, tmp_path)
    create(api, *arguments(owned, tmp_path))
    if change == "daemon":
        api.daemon = "another-daemon"
    elif change == "privileges":
        api.value["HostConfig"]["Privileged"] = True
    else:
        owned[1]["Id"] = "sha256:" + "d" * 64
    with pytest.raises(ValueError):
        stop_and_remove(api, *arguments(owned, tmp_path))
    assert api.calls == [("POST", "/containers/create")]
