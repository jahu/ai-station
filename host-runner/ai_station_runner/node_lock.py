"""Resolve missing npm locks offline using metadata fetched by the typed runner."""

import json
import os
import re
import time
from urllib.parse import unquote, urlsplit

from ai_station_runner.coding_sandbox import dependency_policy, validation_argv, write_policy
from ai_station_runner.dependency_manifest import _regular_file
from ai_station_runner.gitops import GitError
from ai_station_runner.node_dependencies import _installed_name, package_manifest, package_name, verify_lock
from ai_station_runner.node_registry import fetch_metadata, metadata_url
from ai_station_runner.node_runtime import runtime_policy

MAX_PACKAGES = 200
MAX_TOTAL_METADATA = 48 * 1024 * 1024

# This is fixed adapter code, never project/model-supplied JavaScript. Data goes
# through a JSON file. Both cache seeding and npm resolution have no network.
CACHE_WRITER = """
const fs = require('node:fs');
const cache = require(process.argv[1]);
const entry = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const body = JSON.stringify(entry.body);
const key = 'make-fetch-happen:request-cache:' + entry.url;
(async () => {
  for (const accept of ['application/json',
      'application/vnd.npm.install-v1+json; q=1.0, application/json; q=0.8, */*']) {
    await cache.put(process.argv[2] + '/_cacache', key, body, {metadata: {
      time: Date.now(), url: entry.url, reqHeaders: {accept},
      resHeaders: {'content-type': 'application/json', 'cache-control': 'public,max-age=300'},
      options: {compress: true}
    }});
  }
})().catch(error => {console.error(error.message); process.exitCode = 1;});
"""


def missing_package(output):
    try:
        error = json.loads(output).get("error", {})
    except (ValueError, AttributeError) as exc:
        raise GitError("Offline npm resolver returned an invalid result") from exc
    if not isinstance(error, dict):
        raise GitError("Offline npm resolver returned an invalid error")
    if error.get("code") != "ENOTCACHED":
        raise GitError(
            f"Offline npm resolution failed ({error.get('code', 'unknown error')}): "
            + str(error.get("summary", ""))[:600]
        )
    match = re.search(r"request to (https://[^ ]+) failed:", str(error.get("summary", "")))
    if not match:
        raise GitError("Offline npm resolver did not identify registry metadata")
    url = urlsplit(match.group(1))
    if url.scheme != "https" or url.netloc != "registry.npmjs.org" or url.query or url.fragment:
        raise GitError("Offline npm resolver requested an unsupported source")
    return package_name(unquote(url.path.removeprefix("/")))


def generate_lock(workspace, common_dir, runtime, scratch, env, execute, *, deadline, policy_dir):
    sources = []
    fetched = set()
    total = 0
    staging = scratch / "lock-resolution"
    staging.mkdir(mode=0o700)
    source = _regular_file(workspace, workspace / "package.json").read_bytes()
    if len(source) > 256000:
        raise GitError("Node manifest exceeds its size limit")
    (staging / "package.json").write_bytes(source)
    staged_lock = staging / "package-lock.json"

    def offline(argv, label):
        if time.monotonic() >= deadline:
            raise GitError("Node dependency resolution exceeded its time limit")
        policy = policy_dir / f"npm-{label}-{len(sources)}.policy.json"
        write_policy(
            policy,
            workspace,
            common_dir,
            runtime_policy(dependency_policy(workspace, common_dir, network=False), runtime),
        )
        return execute(validation_argv(policy, argv), workspace, env, deadline=deadline, capture=True)

    def seed(name):
        nonlocal total
        if name in fetched or len(fetched) >= MAX_PACKAGES:
            raise GitError("Offline npm metadata resolution cannot progress or exceeds its package limit")
        print(f"Fetching checked public npm metadata: {name}", flush=True)
        document, provenance = fetch_metadata(name, timeout=max(0.1, min(20, deadline - time.monotonic())))
        payload = json.dumps({"url": metadata_url(name), "body": document})
        total += max(len(payload.encode()), provenance.get("metadata_bytes", 0))
        if total > MAX_TOTAL_METADATA:
            raise GitError("Node dependency resolution exceeds its metadata limit")
        path = scratch / f"registry-{len(sources)}.json"
        path.write_text(payload)
        seeded = offline(
            [
                str(runtime.node),
                "-e",
                CACHE_WRITER,
                str(runtime.npm.parent.parent / "node_modules/cacache"),
                str(scratch / "npm-cache"),
                str(path),
            ],
            "cache",
        )
        if seeded["exit_code"] != 0:
            raise GitError("Configured npm runtime cannot cache checked offline metadata")
        fetched.add(name)
        sources.append(provenance)

    argv = runtime.argv("ci", staging, scratch)
    argv[2] = "install"
    argv += ["--package-lock-only", "--offline", "--json"]
    print("Resolving package-lock.json offline from checked public npm metadata", flush=True)
    while True:
        # Only this Run's intermediate lock is discarded. The project's lock
        # is created exclusively after a complete checked resolution succeeds.
        if staged_lock.exists() or staged_lock.is_symlink():
            _regular_file(staging, staged_lock).unlink()
        result = offline(argv, "resolve")
        if result["exit_code"] != 0:
            seed(missing_package(result["stdout"]))
            continue
        verify_lock(staging, package_manifest(staging))
        lock = json.loads(staged_lock.read_bytes())
        installed = {_installed_name(path) for path in lock["packages"] if path}
        omitted = set()
        for record in lock["packages"].values():
            omitted.update(record.get("optionalDependencies", {}))
        omitted -= installed
        if omitted:
            missing = sorted(omitted - fetched)
            if not missing:
                raise GitError("Optional npm dependencies could not be locked from checked registry metadata")
            for name in missing:
                seed(package_name(name))
            continue
        payload = staged_lock.read_bytes()
        descriptor = os.open(
            workspace / "package-lock.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
        return {"lock_generated": True, "registry_metadata": sources}
