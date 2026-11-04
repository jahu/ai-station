"""Native consent, CPU fallback and fixed-helper recovery; never privileged."""

import fcntl
import json
import os
from types import SimpleNamespace

import desktop_gpu as gpu
import pytest


@pytest.fixture
def setup(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    state = SimpleNamespace(
        uuids=["observed"],
        healthy=False,
        present=True,
        choices=[],
        root_result=0,
        calls=[],
        dialogs_closed=0,
        stopped=False,
    )
    monkeypatch.setattr(gpu, "native_linux", lambda: True)
    monkeypatch.setattr(gpu, "gpu_uuids", lambda: state.uuids)
    monkeypatch.setattr(gpu, "nvidia_present", lambda: state.present)
    monkeypatch.setattr(gpu, "probe", lambda *a: state.healthy)
    monkeypatch.setattr(gpu, "system_engine", lambda *a: True)
    monkeypatch.setattr(gpu, "trusted", lambda p: True)
    monkeypatch.setattr(
        gpu.platform, "freedesktop_os_release", lambda: {"ID": "ubuntu", "VERSION_ID": "24.04"}
    )

    def run(argv, **kwargs):
        state.calls.append(argv)
        if argv[0] == "zenity":
            assert state.choices, "Unexpected native dialog"
            result = state.choices.pop(0)
            return SimpleNamespace(returncode=result[0], stdout=result[1])
        assert argv == ["/usr/bin/pkexec", "--disable-internal-agent", str(gpu.HELPER)]
        assert kwargs.get("stdin") is gpu.subprocess.DEVNULL
        return SimpleNamespace(
            returncode=state.root_result,
            stdout=json.dumps({"status": "prepared", "restart_required": True, "gpu_ready": False}),
        )

    monkeypatch.setattr(gpu.subprocess, "run", run)
    state.root = tmp_path
    state.value = {"linux_gpu_recipe": gpu.RECIPE, "image_id": "sha256:" + "a" * 64}
    state.prepare = lambda **kwargs: gpu.prepare(tmp_path, state.value, None, **kwargs)
    return state


def test_healthy_graphics_never_prompt_reinstall_or_keep_a_stale_cpu_choice(setup):
    gpu.save(setup.root, "cpu")
    setup.healthy = True
    assert setup.prepare() == "ready"
    assert not setup.calls and gpu.preference(setup.root) is None


def test_cpu_machine_and_legacy_windows_bundles_keep_their_existing_path(setup):
    setup.uuids, setup.present = [], False
    assert setup.prepare() == "not_applicable"
    setup.value = {}
    assert setup.prepare() == "not_applicable"
    assert not setup.calls


def test_cpu_choice_is_explicit_remembered_and_can_be_reopened(setup):
    setup.choices = [(1, "Use CPU for now")]
    assert setup.prepare() == "cpu"
    assert gpu.preference(setup.root) == "cpu"
    assert setup.prepare() == "cpu"
    setup.choices = [(1, "")]
    assert setup.prepare(force=True) == "canceled"
    assert len(setup.calls) == 2


@pytest.mark.parametrize("prior", [None, "cpu", "pending"])
def test_os_authentication_cancel_restores_the_previous_choice(setup, prior):
    if prior:
        gpu.save(setup.root, prior)
    setup.choices, setup.root_result = [(0, "")], 126
    assert setup.prepare(force=True) == "canceled"
    assert gpu.preference(setup.root) == prior
    assert len(setup.calls) == 2


def test_success_means_restart_required_never_ready_or_automatic_service_restart(setup):
    setup.choices = [(0, ""), (0, "")]
    assert setup.prepare() == "cpu"
    assert gpu.preference(setup.root) == "restart"
    assert [a[0] for a in setup.calls] == ["zenity", "/usr/bin/pkexec", "zenity"]
    setup.calls.clear()
    setup.choices = [(1, "")]
    assert setup.prepare() == "canceled"
    assert [a[0] for a in setup.calls] == ["zenity"]
    setup.healthy = True
    assert setup.prepare() == "ready"
    assert gpu.preference(setup.root) is None


def test_failed_root_action_keeps_pending_inspection_and_does_not_start_cpu_silently(setup):
    setup.choices, setup.root_result = [(0, "")], 1
    with pytest.raises(RuntimeError, match="inspection receipt"):
        setup.prepare()
    assert gpu.preference(setup.root) == "pending"


@pytest.mark.parametrize("reason", ["driver", "engine", "policy", "os"])
def test_unknown_prerequisites_only_offer_cpu_or_close_without_authentication(setup, monkeypatch, reason):
    if reason == "driver":
        setup.uuids = []
    elif reason == "engine":
        monkeypatch.setattr(gpu, "system_engine", lambda *a: False)
    elif reason == "policy":
        monkeypatch.setattr(gpu, "trusted", lambda p: False)
    else:
        monkeypatch.setattr(gpu.platform, "freedesktop_os_release", lambda: {"ID": "debian"})
    setup.choices = [(0, "")]
    assert setup.prepare() == "cpu"
    assert len(setup.calls) == 1 and setup.calls[0][0] == "zenity"


def test_graphics_setup_has_its_own_cross_click_lock(setup):
    path = setup.root / "graphics-setup.lock"
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(RuntimeError, match="already open"):
            setup.prepare()
    finally:
        os.close(descriptor)
    assert not setup.calls


def test_stop_before_preparation_never_prompts_or_authenticates(setup):
    assert setup.prepare(stop_requested=lambda: True) == "canceled"
    assert not setup.calls
