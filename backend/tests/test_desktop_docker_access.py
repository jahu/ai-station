"""Installer authority with simulated OS tools; never change host groups in CI."""

import importlib.util
import stat
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import build_linux_package
import desktop
import desktop_docker_access as access
import pytest
from test_desktop_reopen import shell as shell

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def helper():
    spec = importlib.util.spec_from_file_location(
        "docker_access_helper", ROOT / "packaging/linux/docker_access.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    account = SimpleNamespace(pw_uid=1000, pw_gid=1000, pw_name="stationqa")
    group = SimpleNamespace(gr_gid=998, gr_mem=[])
    info = SimpleNamespace(st_uid=0, st_gid=998, st_mode=stat.S_IFSOCK | 0o660)
    module.os = SimpleNamespace(getuid=lambda: 0, geteuid=lambda: 0, environ={"PKEXEC_UID": "1000"})
    module.sys = SimpleNamespace(argv=["docker-access"])
    module.pwd = SimpleNamespace(getpwuid=lambda uid: account, getpwnam=lambda name: account)
    module.grp = SimpleNamespace(getgrnam=lambda name: group)
    module.SOCKET = SimpleNamespace(lstat=lambda: info)
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        group.gr_mem = [account.pw_name]

    module.subprocess = SimpleNamespace(run=run, DEVNULL=subprocess.DEVNULL)
    return module, account, group, info, calls


def test_helper_changes_only_the_authenticated_invoking_account_and_is_idempotent(helper):
    module, _, group, _, calls = helper
    module.grant()
    assert calls[0][0] == ["/usr/sbin/usermod", "--append", "--groups", "docker", "--", "stationqa"]
    assert calls[0][1]["env"] == {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C", "LC_ALL": "C"}
    assert calls[0][1]["cwd"] == "/" and calls[0][1]["timeout"] == 30
    assert group.gr_mem == ["stationqa"]
    module.grant()
    assert len(calls) == 1


@pytest.mark.parametrize("uid", ["", "0", "999", "01000", "1000; id", "-1000", "4294967296", "١٠٠٠"])
def test_helper_rejects_invalid_invoking_identity_before_any_change(helper, uid):
    module, _, _, _, calls = helper
    module.os.environ["PKEXEC_UID"] = uid
    with pytest.raises(ValueError):
        module.grant()
    assert not calls


@pytest.mark.parametrize("arguments", [["--help"], ["other-user"], ["docker", "root"]])
def test_helper_accepts_no_caller_arguments(helper, arguments):
    module, _, _, _, calls = helper
    module.sys.argv += arguments
    with pytest.raises(ValueError):
        module.grant()
    assert not calls


@pytest.mark.parametrize(
    "change",
    ["not_root", "different_account", "symlink", "wrong_owner", "wrong_group", "open_socket", "root_group"],
)
def test_changed_OS_identity_or_socket_cannot_authorize_a_change(helper, change):
    module, account, group, info, calls = helper
    if change == "not_root":
        module.os.getuid = lambda: 1000
    elif change == "different_account":
        account.pw_uid = 1001
    elif change == "symlink":
        info.st_mode = stat.S_IFLNK | 0o777
    elif change == "wrong_owner":
        info.st_uid = 1000
    elif change == "wrong_group":
        info.st_gid = 1
    elif change == "open_socket":
        info.st_mode = stat.S_IFSOCK | 0o666
    else:
        group.gr_gid = 0
    with pytest.raises(ValueError):
        module.grant()
    assert not calls


@pytest.fixture
def consent(monkeypatch):
    group = SimpleNamespace(gr_gid=998, gr_mem=[])
    monkeypatch.setattr(access, "trusted", lambda _: True)
    monkeypatch.setattr(access, "needed", lambda _: True)
    monkeypatch.setattr(
        access, "pwd", SimpleNamespace(getpwuid=lambda _: SimpleNamespace(pw_gid=1000, pw_name="stationqa"))
    )
    monkeypatch.setattr(access, "grp", SimpleNamespace(getgrnam=lambda _: group))
    execute = Mock()
    monkeypatch.setattr(access.subprocess, "run", execute)
    launch = Mock(side_effect=RuntimeError("captured fixed launcher"))
    monkeypatch.setattr(access.os, "execv", launch)
    return group, execute, launch


def test_canceled_desktop_consent_never_requests_OS_authority(consent):
    _, execute, launch = consent
    assert access.continue_setup(Mock(return_value=1)) is False
    execute.assert_not_called()
    launch.assert_not_called()


@pytest.mark.parametrize("code", [126, 127, 1])
def test_canceled_or_failed_OS_authentication_never_launches_or_falls_back(consent, code):
    _, execute, launch = consent
    execute.return_value = SimpleNamespace(returncode=code)
    if code == 126:
        assert access.continue_setup(Mock(return_value=0)) is False
    else:
        with pytest.raises(RuntimeError, match="setup did not finish"):
            access.continue_setup(Mock(return_value=0))
    assert execute.call_args.args[0] == ["/usr/bin/pkexec", "--disable-internal-agent", str(access.HELPER)]
    assert execute.call_args.kwargs["stdin"] == subprocess.DEVNULL
    launch.assert_not_called()


def test_successful_OS_authentication_reopens_only_the_fixed_normal_user_launcher(consent):
    group, execute, launch = consent

    def grant(*_args, **_kwargs):
        group.gr_mem = ["stationqa"]
        return SimpleNamespace(returncode=0)

    execute.side_effect = grant
    with pytest.raises(RuntimeError, match="captured fixed launcher"):
        access.continue_setup(Mock(return_value=0), background=True)
    launch.assert_called_once_with(
        "/usr/bin/sg", ["sg", "docker", "-c", "exec /usr/lib/ai-station/station --background"]
    )


def test_already_granted_membership_requires_no_repeat_privileged_action(consent):
    group, execute, launch = consent
    group.gr_mem = ["stationqa"]
    ask = Mock()
    with pytest.raises(RuntimeError, match="captured fixed launcher"):
        access.continue_setup(ask)
    ask.assert_not_called()
    execute.assert_not_called()
    launch.assert_called_once()


def test_unsafe_package_files_block_consent_and_authentication(consent, monkeypatch):
    _, execute, launch = consent
    monkeypatch.setattr(access, "trusted", lambda _: False)
    ask = Mock()
    with pytest.raises(RuntimeError, match="reviewed OS package"):
        access.continue_setup(ask)
    ask.assert_not_called()
    execute.assert_not_called()
    launch.assert_not_called()


def test_user_owned_or_symlinked_helpers_are_never_trusted(tmp_path):
    file = tmp_path / "helper"
    file.write_text("untrusted")
    assert access.trusted(file) is False
    alias = tmp_path / "link"
    alias.symlink_to(file)
    assert access.trusted(alias) is False


def test_policy_requires_fresh_admin_authentication_and_only_the_fixed_helper():
    policy = ET.parse(ROOT / "packaging/linux/org.ai-station.docker-access.policy").getroot()
    action = policy.find("action")
    assert action.attrib["id"] == "org.ai-station.docker-access"
    assert {v.text for v in action.find("defaults")} == {"auth_admin"}
    assert [(v.attrib["key"], v.text) for v in action.findall("annotate")] == [
        ("org.freedesktop.policykit.exec.path", str(access.HELPER))
    ]


def test_first_start_consent_cancel_releases_desktop_lock_without_starting_anything(shell, monkeypatch):
    root, _, prerequisites, supervise = shell
    monkeypatch.setattr(sys, "argv", ["desktop.py"])
    monkeypatch.setattr(desktop.shutil, "which", lambda _: "/usr/bin/zenity")
    prerequisites.side_effect = access.DockerAccessNeeded()
    consent = Mock(return_value=False)
    monkeypatch.setattr(desktop, "continue_docker_setup", consent)
    desktop.main()
    consent.assert_called_once_with(desktop.dialog, background=False)
    supervise.assert_not_called()
    assert not (root / "desktop.env").exists()


@pytest.mark.parametrize(
    "endpoint", ["unix:///home/user/docker.sock", "tcp://127.0.0.1:2375", "unix:///tmp/docker.sock"]
)
def test_rootless_remote_or_caller_sockets_never_offer_system_group_setup(endpoint):
    assert not access.needed(endpoint)


@pytest.mark.parametrize(
    "change",
    ["none", "member", "root", "other_owner", "wrong_group", "regular_file", "symlink", "world_writable"],
)
def test_detection_requires_the_actual_local_root_owned_Docker_group_socket(monkeypatch, change):
    info = SimpleNamespace(st_uid=0, st_gid=998, st_mode=stat.S_IFSOCK | 0o660)
    monkeypatch.setattr(access, "SOCKET", SimpleNamespace(lstat=lambda: info))
    monkeypatch.setattr(access, "grp", SimpleNamespace(getgrnam=lambda _: SimpleNamespace(gr_gid=998)))
    monkeypatch.setattr(
        access,
        "os",
        SimpleNamespace(
            getuid=lambda: 0 if change == "root" else 1000,
            getgid=lambda: 1000,
            getgroups=lambda: [998] if change == "member" else [1000],
        ),
    )
    if change == "other_owner":
        info.st_uid = 1000
    elif change == "wrong_group":
        info.st_gid = 1
    elif change == "regular_file":
        info.st_mode = stat.S_IFREG | 0o660
    elif change == "symlink":
        info.st_mode = stat.S_IFLNK | 0o777
    elif change == "world_writable":
        info.st_mode = stat.S_IFSOCK | 0o666
    assert access.needed("unix:///var/run/docker.sock") is (change == "none")


@pytest.mark.parametrize("failed", ["compose", "info"])
def test_only_Docker_info_permission_failure_offers_account_setup(monkeypatch, failed):
    monkeypatch.setenv("DOCKER_HOST", "unix:///var/run/docker.sock")
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    monkeypatch.setattr(desktop.shutil, "which", lambda _: "/usr/bin/docker")
    monkeypatch.setattr(desktop, "docker_access_needed", lambda _: True)
    monkeypatch.setattr(
        desktop.subprocess, "run", lambda command, **_: SimpleNamespace(returncode=int(command[1] == failed))
    )
    expected = access.DockerAccessNeeded if failed == "info" else RuntimeError
    with pytest.raises(expected):
        desktop.prerequisites()


def test_OS_package_modes_do_not_inherit_group_write_or_follow_links(tmp_path):
    root = tmp_path / "package"
    root.mkdir(mode=0o700)
    folder = root / "usr/libexec/ai-station"
    folder.mkdir(parents=True)
    folder.chmod(0o775)
    helper = folder / "helper"
    helper.write_text("executable")
    helper.chmod(0o775)
    policy = root / "policy"
    policy.write_text("policy")
    policy.chmod(0o664)
    external = tmp_path / "preserve"
    external.write_text("preserve")
    external.chmod(0o600)
    (folder / "link").symlink_to(external)
    build_linux_package.package_permissions(root)
    assert stat.S_IMODE(root.stat().st_mode) == stat.S_IMODE(folder.stat().st_mode) == 0o755
    assert stat.S_IMODE(helper.stat().st_mode) == 0o755
    assert stat.S_IMODE(policy.stat().st_mode) == 0o644
    assert stat.S_IMODE(external.stat().st_mode) == 0o600


def test_newer_source_upgrades_regardless_of_hash_and_supersedes_legacy_previews():
    import shutil

    if not shutil.which("dpkg"):
        pytest.skip("Debian version comparison requires the actual package manager")
    old = build_linux_package.debian_version({"source_epoch": 1793460000, "bundle_id": "f" * 64})
    new = build_linux_package.debian_version({"source_epoch": 1793460001, "bundle_id": "a" * 64})
    subprocess.run(["dpkg", "--compare-versions", old, "lt", new], check=True)
    for previous in (
        "0.1.0~dev.e42b59894363044c",
        "0.1.0~dev.d1c765ce319bf1b8",
        "0.1.0~dev.14b5ceb52c3f0a2d",
    ):
        subprocess.run(["dpkg", "--compare-versions", previous, "lt", new], check=True)
    subprocess.run(["dpkg", "--compare-versions", new, "lt", "0.1.0"], check=True)
