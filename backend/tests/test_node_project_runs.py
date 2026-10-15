# Imported fixtures intentionally share their pytest parameter names.
# ruff: noqa: F811
import json
import sys

import pytest
from ai_station_runner.config import clear_settings_cache
from app.api import app
from app.db import session_factory
from app.engine import tick
from fastapi.testclient import TestClient
from test_projects import (  # noqa: F401
    enqueue_dependencies,
    enqueue_validation,
    owned_runner,
    prepared_validation,
    repository,
    validation_sandbox,
)


@pytest.fixture
def fake_node(tmp_path, monkeypatch, owned_runner):
    root = tmp_path / "node-runtime"
    (root / "bin").mkdir(parents=True)
    npm = root / "lib/node_modules/npm"
    (npm / "bin").mkdir(parents=True)
    (npm / "package.json").write_text(json.dumps({"name": "npm", "version": "10.9.8"}))
    (npm / "bin/npm-cli.js").write_text("// fixture; execution belongs to fake node")
    node = root / "bin/node"
    node.write_text("""#!/usr/bin/python3
import sys,os,json,time,stat
from pathlib import Path
if sys.argv[1:]==['--version']:
 print('v22.0.0');raise SystemExit()
assert stat.S_ISFIFO(os.fstat(0).st_mode), 'sandboxed commands require an EOF pipe'
assert os.read(0,1)==b'', 'commands must not await interactive input'
assert not {'NPM_TOKEN','NODE_AUTH_TOKEN','NODE_OPTIONS','AI_STATION_TEST_SECRET'}.intersection(os.environ)
if sys.argv[1]=='-e':
 data=json.loads(Path(sys.argv[-1]).read_text())
 Path('metadata-proof.json').write_text(json.dumps(data))
 raise SystemExit()
assert sys.argv[1].endswith('npm-cli.js')
if sys.argv[2]=='install':
 assert '--offline' in sys.argv and '--package-lock-only' in sys.argv and '--ignore-scripts=true' in sys.argv
 package=json.loads(Path('package.json').read_text())
 if package.get('fixture_lock_wait'):
  Path('npm-started.txt').write_text('owned offline resolver reached lock generation')
  time.sleep(30)
 if package.get('fixture_lock_error'):
  print(json.dumps({'error':{'code':'ERESOLVE'}}));raise SystemExit(1)
 names=list(package.get('dependencies',{}))
 if names and not Path('metadata-proof.json').exists():
  print(json.dumps({'error':{'code':'ENOTCACHED','summary':'request to https://registry.npmjs.org/'+names[0]+' failed: cache mode is only-if-cached'}}));raise SystemExit(1)
 entries={'':package}
 for name in names:
  import base64
  entries['node_modules/'+name]={'version':'1.0.0','resolved':'https://registry.npmjs.org/'+name+'/-/'+name.split('/')[-1]+'-1.0.0.tgz','integrity':'sha512-'+base64.b64encode(b'x'*64).decode()}
 prefix=Path(next(a.split('=',1)[1] for a in sys.argv if a.startswith('--prefix=')))
 (prefix/'package-lock.json').write_text(json.dumps({'lockfileVersion':3,'packages':entries}))
 print('{}');raise SystemExit()
if sys.argv[2]=='ci':
 assert '--ignore-scripts=true' in sys.argv
 assert '--registry=https://registry.npmjs.org' in sys.argv
 assert Path(os.environ['HOME']).is_relative_to(Path.cwd())
 assert any(a.startswith('--userconfig=') for a in sys.argv)
 assert any(a.startswith('--globalconfig=') for a in sys.argv)
 package=json.loads(Path('package.json').read_text())
 if package.get('fixture_wait'):
  Path('npm-started.txt').write_text('owned npm child reached installation')
  time.sleep(30)
 Path('node_modules').mkdir(exist_ok=True)
 Path('install-proof.json').write_text(json.dumps({'argv':sys.argv[2:],'home':os.environ['HOME']}))
 raise SystemExit(package.get('fixture_exit',0))
assert sys.argv[2:]==['run','build']
assert Path('node_modules').is_dir()
Path('build-proof.txt').write_text('sandboxed configured Node build')
""")
    node.chmod(0o700)
    monkeypatch.setenv("AI_STATION_NODE_PREFIX", str(root))
    monkeypatch.setenv("NPM_TOKEN", "disposable-fixture-secret")
    monkeypatch.setenv("NODE_AUTH_TOKEN", "disposable-fixture-secret")
    monkeypatch.setenv("NODE_OPTIONS", "--require=private-file")
    clear_settings_cache()
    original = owned_runner.start

    def start(**kwargs):
        if kwargs["executor"] == "project_dependencies":
            run_id = kwargs["run_id"]
            kwargs["argv"] = [
                sys.executable,
                "-c",
                "from ai_station_runner import node_dependencies as dep; dep.confirm_registry=lambda:None; "
                "from ai_station_runner import node_lock; "
                "node_lock.fetch_metadata=lambda name, **kwargs: ({'name':name}, {'name':name,'metadata_sha256':'f'*64}); "
                f"from ai_station_runner.dependency_job import install; install({run_id!r})",
            ]
        return original(**kwargs)

    monkeypatch.setattr(owned_runner, "start", start)
    yield root
    clear_settings_cache()


def node_manifest(workspace, **extra):
    package = {
        "name": "fixture",
        "version": "1.0.0",
        "private": True,
        "scripts": {"preinstall": "touch forbidden-lifecycle.txt", "build": "node build.js"},
        **extra,
    }
    (workspace / "package.json").write_text(json.dumps(package))
    (workspace / "package-lock.json").write_text(
        json.dumps({"lockfileVersion": 3, "packages": {"": package}})
    )


@pytest.mark.parametrize("exit_code", [0, 2])
def test_owned_npm_report_and_configured_node_validation_preserve_checkout(
    repository, owned_runner, validation_sandbox, fake_node, exit_code
):
    index = (repository / ".git/index").read_bytes()
    with TestClient(app) as client:
        project, worktree = prepared_validation(client, repository, [["npm", "run", "build"]])
        workspace = owned_runner.data_dir / worktree["relative_path"]
        node_manifest(workspace, fixture_exit=exit_code)
        response = enqueue_dependencies(client, project, worktree)
        assert response.status_code == 202, response.text
        with session_factory()() as session:
            tick(session, "node-install")
        result = client.get("/api/runs/" + response.json()["id"]).json()
        assert result["status"] == ("succeeded" if exit_code == 0 else "failed"), result
        report = result["metadata"]["dependencies"]
        assert report["ecosystem"] == "node" and report["lifecycle_scripts"] is False
        assert report["exit_code"] == exit_code and report["node_version"] == "v22.0.0"
        assert report["environment"].endswith("/node_modules")
        assert len(report["lock_sha256"]) == 64 and len(report["package_sha256"]) == 64
        assert (workspace / "install-proof.json").is_file()
        assert not (workspace / "forbidden-lifecycle.txt").exists()
        assert not (workspace / ".venv").exists()
        if exit_code == 0:
            validation = enqueue_validation(client, project, worktree)
            assert validation.status_code == 202, validation.text
            with session_factory()() as session:
                tick(session, "node-build")
            built = client.get("/api/runs/" + validation.json()["id"]).json()
            assert built["status"] == "succeeded", built
            assert (workspace / "build-proof.txt").is_file()
        assert (repository / ".git/index").read_bytes() == index
        assert not (repository / "node_modules").exists()


@pytest.mark.parametrize("unsafe", ["npmrc", "shrinkwrap", "url_peer", "symlink_modules"])
def test_npm_refuses_scope_overrides_before_runtime_install(
    repository, owned_runner, validation_sandbox, fake_node, unsafe
):
    with TestClient(app) as client:
        project, worktree = prepared_validation(client, repository, [])
        workspace = owned_runner.data_dir / worktree["relative_path"]
        node_manifest(workspace)
        if unsafe == "npmrc":
            (workspace / ".npmrc").write_text("registry=http://127.0.0.1")
        elif unsafe == "shrinkwrap":
            (workspace / "npm-shrinkwrap.json").write_text("{}")
        elif unsafe == "url_peer":
            node_manifest(workspace, peerDependencies={"evil": "https://127.0.0.1/private.tgz"})
        else:
            (workspace / "node_modules").symlink_to(repository)
        response = enqueue_dependencies(client, project, worktree)
        assert response.status_code == 202, response.text
        with session_factory()() as session:
            tick(session, "node-refused")
        result = client.get("/api/runs/" + response.json()["id"]).json()
        assert result["status"] == "failed", result
        assert "dependencies" not in result["metadata"]
        assert not (workspace / "install-proof.json").exists()


@pytest.mark.parametrize("during", ["install", "lock"])
def test_stop_terminates_the_owned_npm_child_without_publishing_success(
    repository, owned_runner, validation_sandbox, fake_node, monkeypatch, during
):
    import time

    from app.models import Run
    from app.runner_client import RunnerClient
    from app.runs import request_cancel

    with TestClient(app) as client:
        project, worktree = prepared_validation(client, repository, [])
        workspace = owned_runner.data_dir / worktree["relative_path"]
        node_manifest(
            workspace, **({"fixture_wait": True} if during == "install" else {"fixture_lock_wait": True})
        )
        if during == "lock":
            (workspace / "package-lock.json").unlink()
        queued = enqueue_dependencies(client, project, worktree)
        assert queued.status_code == 202, queued.text
        run_id = queued.json()["id"]
        original = RunnerClient.request

        def stop_after_npm_started(self, method, path, payload=None):
            result = original(self, method, path, payload)
            if method == "POST" and path == "/v1/runs/dependencies":
                deadline = time.monotonic() + 10
                while not (workspace / "npm-started.txt").exists():
                    assert time.monotonic() < deadline, "Owned npm child did not start"
                    time.sleep(0.02)
                assert owned_runner.inspect(run_id)["alive"]
                with session_factory()() as session:
                    request_cancel(session, session.get(Run, run_id))
                    session.commit()
            return result

        monkeypatch.setattr(RunnerClient, "request", stop_after_npm_started)
        with session_factory()() as session:
            tick(session, "cancel-npm-child")
        run = client.get("/api/runs/" + run_id).json()
        assert run["status"] == "canceled", run
        assert "dependencies" not in run["metadata"]
        assert not owned_runner.inspect(run_id)["alive"]
        assert not (workspace / "install-proof.json").exists()


@pytest.mark.parametrize("with_dependency", [False, True])
def test_missing_lock_is_created_offline_with_metadata_provenance_before_install(
    repository, owned_runner, validation_sandbox, fake_node, with_dependency
):
    index = (repository / ".git/index").read_bytes()
    with TestClient(app) as client:
        project, worktree = prepared_validation(client, repository, [])
        workspace = owned_runner.data_dir / worktree["relative_path"]
        node_manifest(workspace, dependencies={"demo": "^1.0.0"} if with_dependency else {})
        original = (workspace / "package.json").read_bytes()
        (workspace / "package-lock.json").unlink()
        response = enqueue_dependencies(client, project, worktree)
        assert response.status_code == 202
        with session_factory()() as session:
            tick(session, "offline-node-lock")
        run = client.get("/api/runs/" + response.json()["id"]).json()
        assert run["status"] == "succeeded", run
        report = run["metadata"]["dependencies"]
        assert report["lock_generated"] and len(report["registry_metadata"]) == int(with_dependency)
        assert (workspace / "package-lock.json").is_file() and (workspace / "install-proof.json").is_file()
        assert (workspace / "package.json").read_bytes() == original
        assert (repository / ".git/index").read_bytes() == index
        assert not (repository / "package-lock.json").exists()
        if with_dependency:
            assert report["registry_metadata"][0]["name"] == "demo"
            assert len(report["registry_metadata"][0]["metadata_sha256"]) == 64


def test_offline_resolution_failure_never_starts_install(
    repository, owned_runner, validation_sandbox, fake_node
):
    with TestClient(app) as client:
        project, worktree = prepared_validation(client, repository, [])
        workspace = owned_runner.data_dir / worktree["relative_path"]
        node_manifest(workspace, fixture_lock_error=True)
        (workspace / "package-lock.json").unlink()
        response = enqueue_dependencies(client, project, worktree)
        assert response.status_code == 202
        with session_factory()() as session:
            tick(session, "offline-node-lock-failure")
        run = client.get("/api/runs/" + response.json()["id"]).json()
        assert run["status"] == "failed", run
        assert not (workspace / "install-proof.json").exists()
        assert not (workspace / "node_modules").exists()
