"""Owned CLI actions, frozen identities and protected interactive links."""

import json
import time
from pathlib import Path
from uuid import uuid4

import pytest
from ai_station_runner import tailnet_actions as actions
from ai_station_runner.tailnet import cli_argv
from test_tailnet_service import manager as manager

CLI = """#!/usr/bin/python3
import sys,json,time
from pathlib import Path
socket=next(a.split('=',1)[1] for a in sys.argv if a.startswith('--socket='))
root=Path(socket).parent
if 'up' in sys.argv:
 print(json.dumps({'AuthURL':'https://login.tailscale.com/a/SECRET-LOGIN'}),flush=True)
 if (root/'hold').exists():time.sleep(60)
 sys.exit(1)
if 'serve' in sys.argv:
 if (root/'consent').exists():
  print('https://login.tailscale.com/f/serve?node=node123',flush=True);time.sleep(60)
 if 'off' in sys.argv:config={}
 else:config={'TCP':{'443':{'HTTPS':True}},'Web':{'ai-station.tail123.ts.net:443':{'Handlers':{'/':{'Proxy':sys.argv[-1]}}}}}
 (root/'config.json').write_text(json.dumps(config))
"""


@pytest.fixture
def runtime(manager, monkeypatch):
    (manager.binary_dir / "tailscale").write_text(CLI)
    (manager.binary_dir / "tailscale").chmod(0o700)
    monkeypatch.setattr(actions, "verified_install", lambda *a: {})
    manager.start(str(uuid4()))
    yield manager


def finished(manager, rid):
    for _ in range(50):
        result = actions.inspect(manager, rid)
        if result["phase"] != "running":
            return result
        time.sleep(0.02)
    pytest.fail("Private fixture action did not complete")


def online(manager):
    (manager.root / "node.json").write_text(
        json.dumps(
            {
                "BackendState": "Running",
                "Self": {"ID": "node123", "Online": True, "DNSName": "ai-station.tail123.ts.net."},
            }
        )
    )
    return manager.status()


def test_login_fixed_flags_never_change_host_network_preferences():
    argv = cli_argv(Path("/bin/tailscale"), Path("/private/socket"), "login")
    assert argv[2:] == [
        "up",
        "--json",
        "--timeout=5s",
        "--hostname=ai-station",
        "--accept-dns=false",
        "--accept-routes=false",
        "--ssh=false",
        "--advertise-routes=",
        "--advertise-exit-node=false",
        "--advertise-connector=false",
        "--exit-node=",
        "--exit-node-allow-lan-access=false",
        "--netfilter-mode=off",
        "--snat-subnet-routes=false",
        "--report-posture=false",
    ]


def test_login_link_is_private_and_only_latest_action_may_return_it(runtime):
    rid = str(uuid4())
    actions.begin(runtime, rid, "login")
    result = finished(runtime, rid)
    assert result["phase"] == "login_required" and "SECRET" not in json.dumps(result)
    assert actions.action_link(runtime, rid) == "https://login.tailscale.com/a/SECRET-LOGIN"
    newer = str(uuid4())
    actions.begin(runtime, newer, "login")
    finished(runtime, newer)
    assert actions.action_link(runtime, rid) is None
    assert actions.action_link(runtime, newer)
    online(runtime)
    assert actions.action_link(runtime, newer) is None


def test_idempotency_and_cancel_signal_only_the_owned_cli(runtime):
    (runtime.root / "hold").write_text("1")
    rid = str(uuid4())
    actions.begin(runtime, rid, "login")
    before = runtime._processes().inspect(rid)["pid"]
    actions.begin(runtime, rid, "login")
    assert runtime._processes().inspect(rid)["pid"] == before
    assert actions.cancel(runtime, rid)["phase"] == "canceled"
    assert actions.action_link(runtime, rid) is None
    assert runtime.status()["state"] == "NeedsLogin"


def test_serve_checks_current_node_and_only_fixed_loopback_target(runtime):
    state = online(runtime)
    rid = str(uuid4())
    with pytest.raises(ValueError):
        actions.begin(runtime, rid, "serve_on", node_id="other", origin=state["origin"])
    actions.begin(runtime, rid, "serve_on", node_id=state["node_id"], origin=state["origin"])
    assert finished(runtime, rid)["phase"] == "succeeded"
    with pytest.raises(ValueError):
        actions.begin(runtime, rid, "serve_off", node_id=state["node_id"], origin=state["origin"])
    stop = str(uuid4())
    actions.begin(runtime, stop, "serve_off", node_id=state["node_id"], origin=state["origin"])
    assert finished(runtime, stop)["phase"] == "succeeded" and not runtime.status()["serving"]


def test_unexpected_funnel_config_is_not_overwritten(runtime):
    state = online(runtime)
    raw = {"AllowFunnel": {"ai-station.tail123.ts.net:443": True}}
    (runtime.root / "config.json").write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="configuration"):
        actions.begin(runtime, str(uuid4()), "serve_on", node_id=state["node_id"], origin=state["origin"])
    assert json.loads((runtime.root / "config.json").read_text()) == raw


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.invalid/a/SECRET",
        "http://login.tailscale.com/a/SECRET",
        "https://login.tailscale.com@evil.invalid/a/SECRET",
        "https://login.tailscale.com:443/a/SECRET",
        "https://login.tailscale.com/a/SECRET\n",
        "https://login.tailscale.com/a/SECRET#fragment",
    ],
)
def test_untrusted_interactive_links_are_rejected(url):
    assert actions.login_url(url, operation="login") is None


def test_cancel_before_login_dispatch_prevents_late_start(runtime):
    rid = str(uuid4())
    runtime.request_cancel(rid, "login")
    result = actions.begin(runtime, rid, "login")
    assert result["phase"] == "canceled"
    assert not (runtime.root / "operations" / (rid + ".json")).exists()
    assert runtime.status()["state"] == "NeedsLogin"


def test_disabling_drains_only_owned_private_cli(runtime):
    (runtime.root / "hold").write_text("hold")
    rid = str(uuid4())
    actions.begin(runtime, rid, "login")
    actions.drain(runtime)
    assert actions.inspect(runtime, rid)["phase"] == "canceled"
    assert runtime.status()["state"] == "NeedsLogin"


def test_enabled_endpoint_restarts_owned_daemon_without_login_or_serve(runtime):
    online(runtime)
    rid = str(uuid4())
    actions.begin(runtime, rid, "serve_on", node_id="node123", origin="https://ai-station.tail123.ts.net")
    assert finished(runtime, rid)["phase"] == "succeeded"
    desired = runtime.root / "desired.json"
    assert desired.stat().st_mode & 0o777 == 0o600
    daemon = runtime.status()["daemon_id"]
    runtime.stop()
    assert runtime.status()["state"] == "stopped"
    runtime.restore()
    state = runtime.status()
    assert state["daemon_id"] != daemon and state["serving"]
    assert len(list((runtime.root / "operations").glob("*.json"))) == 1
    runtime.forget_endpoint()
    runtime.stop()
    runtime.restore()
    assert runtime.status()["state"] == "stopped"


def test_https_consent_link_survives_owned_observation_deadline(runtime):
    online(runtime)
    (runtime.root / "consent").write_text("required")
    rid = str(uuid4())
    actions.begin(runtime, rid, "serve_on", node_id="node123", origin="https://ai-station.tail123.ts.net")
    for _ in range(50):
        process = runtime._processes().inspect(rid)
        if "https://login.tailscale.com/f/serve" in process.get("stdout", ""):
            break
        time.sleep(0.02)
    assert "https://login.tailscale.com/f/serve" in process["stdout"]
    runtime._processes()._expire(rid, process["deadline_at"])
    result = finished(runtime, rid)
    assert result["phase"] == "https_consent_required" and result["process_confirmed_gone"]
    assert actions.action_link(runtime, rid) == "https://login.tailscale.com/f/serve?node=node123"
    actions.cancel(runtime, rid)
    assert actions.action_link(runtime, rid) is None
