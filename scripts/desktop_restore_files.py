"""Private retained-file staging/publication. Caller owns the cold restore fence."""

import hashlib
import json
import os
import shutil
import stat
from uuid import UUID

import desktop_snapshot_files as files
import desktop_versions as versions
from desktop_bridge import private_directory


def exists(path):
    return path.exists() or path.is_symlink()


def inventory(root, *, prefix=None):
    """Hash regular files; preserve link text without following link targets."""
    result = {}
    catalog = files.catalog(root)
    for key, entry in catalog.items():
        if prefix is not None and key != prefix and not key.startswith(prefix + "/"):
            continue
        info = entry["signature"]
        kind = entry["kind"]
        if kind == "file":
            result[key] = {
                "kind": "file",
                "mode": stat.S_IMODE(info[5]),
                "size": info[2],
                "sha256": files.source_hash(root, key, info),
            }
        elif kind == "directory":
            result[key] = {"kind": "directory", "mode": stat.S_IMODE(info[5])}
        else:
            parts = files.relative(key).parts
            fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                for part in parts[:-1]:
                    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    os.close(fd)
                    fd = child
                if files.signature(os.stat(parts[-1], dir_fd=fd, follow_symlinks=False)) != info:
                    raise ValueError("The retained link changed during inspection")
                result[key] = {"kind": "link", "target": os.readlink(parts[-1], dir_fd=fd)}
            finally:
                os.close(fd)
    if files.catalog(root) != catalog:
        raise ValueError("Retained files changed during inspection")
    return result


def roots(tree, root):
    return {
        key: [getattr((root / key).lstat(), field) for field in ("st_dev", "st_ino")]
        for key in tree
        if "/" not in key
    }


def subtree(tree, name):
    return {key: value for key, value in tree.items() if key == name or key.startswith(name + "/")}


def same_tree(root, expected, *, partial=False):
    actual = inventory(root)
    if (not partial and set(actual) != set(expected)) or any(expected.get(k) != v for k, v in actual.items()):
        raise ValueError("Restore file bytes, types or inventory changed; originals retained")
    return actual


def request_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


class SecretConflict(ValueError):
    def __init__(self, paths):
        self.paths = sorted(paths)
        super().__init__(
            f"{len(paths)} current credential files differ. Review keeping current credentials before restoring."
        )


class FileRestore:
    def __init__(self, data, operation):
        if not isinstance(operation, str) or str(UUID(operation)) != operation:
            raise ValueError("Use a canonical restore UUID")
        self.data, self.operation = versions.canonical(data), operation
        private_directory(self.data)
        parent = self.data / "recovery"
        parent.mkdir(mode=0o700, exist_ok=True)
        private_directory(parent)
        self.root = parent / ("desktop-" + operation)
        self.root.mkdir(mode=0o700, exist_ok=True)
        private_directory(self.root)
        if self.root.stat().st_dev != self.data.stat().st_dev:
            raise ValueError("Retained-file staging must share the application data filesystem")
        self.incoming = self.root / "incoming"
        self.originals = self.root / "originals"
        self.discarded = self.root / "restored-before-abort"
        self.scratch = self.root / "scratch"
        for folder in (self.incoming, self.originals, self.discarded, self.scratch):
            folder.mkdir(mode=0o700, exist_ok=True)
            private_directory(folder)

    def load(self):
        request = json.loads(versions.read_private(self.root / "request.json", files.LIMIT))
        if (
            not isinstance(request, dict)
            or request.get("schema") != 1
            or request.get("operation_id") != self.operation
            or request.get("data") != str(self.data)
        ):
            raise ValueError("The private retained-file restore request changed")
        for tree in (request["original"], request["desired"]):
            for key in tree:
                files.relative(key)
        if not isinstance(request["original_roots"], dict) or set(request["original_roots"]) != {
            key for key in request["original"] if "/" not in key
        }:
            raise ValueError("The original restore root inventory changed")
        state_path = self.root / "state.json"
        if not exists(state_path):
            # A request can become durable one fsync before its initial state.
            # Reconstruct only while no live root has ever moved/replaced.
            if list(self.originals.iterdir()) or list(self.discarded.iterdir()):
                raise ValueError("Missing publication state requires inspection; originals retained")
            same_tree(self.data, request["original"])
            if roots(request["original"], self.data) != request["original_roots"]:
                raise ValueError("Original restore identities changed before state recovery")
            self.save({"phase": "preparing", "request_sha256": request_hash(request)})
        state = json.loads(versions.read_private(state_path, files.LIMIT))
        if (
            not isinstance(state, dict)
            or state.get("request_sha256") != request_hash(request)
            or state.get("phase")
            not in {"preparing", "prepared", "publishing", "published", "aborting", "aborted", "committed"}
        ):
            raise ValueError("The private retained-file restore journal changed")
        for names, tree in (
            (request["original_roots"], request["original"]),
            (state.get("new_roots"), request["desired"]),
        ):
            if names is None and state["phase"] in {"preparing", "aborted"}:
                continue
            if not isinstance(names, dict) or set(names) != {key for key in tree if "/" not in key}:
                raise ValueError("The retained-file restore root inventory changed")
            for name, signature in names.items():
                if (
                    len(files.relative(name).parts) != 1
                    or not isinstance(signature, list)
                    or len(signature) != 2
                    or any(type(v) is not int or v < 0 for v in signature)
                ):
                    raise ValueError("The retained-file restore root identity changed")
        return request, state

    def save(self, state):
        files.write_json(self.root / "state.json", state)

    def prepare(
        self, backup, identity, *, secrets_policy="review", canceled=lambda: False, progress=lambda *_: None
    ):
        backup = versions.canonical(backup)
        if backup.is_relative_to(self.data) or self.data.is_relative_to(backup):
            raise ValueError("A restore source must stay separate from application data")
        if secrets_policy not in {"review", "keep_current"}:
            raise ValueError("Choose a reviewed credential preservation policy")
        manifest = files.verify_files(backup, identity)
        source = backup / "files"
        source_catalog = files.catalog(source)
        request_path = self.root / "request.json"
        if exists(request_path):
            request, state = self.load()
            if (
                request["backup"] != str(backup)
                or request["identity"] != identity
                or request["secrets_policy"] != secrets_policy
            ):
                raise ValueError("The retained-file restore source/policy changed")
            if state["phase"] != "preparing":
                if state["phase"] != "prepared":
                    raise ValueError("Inspect the existing retained-file publication before preparing again")
                same_tree(self.incoming, request["desired"])
                return state
        else:
            old = inventory(self.data)
            current_catalog = files.catalog(self.data)
            desired, sources = {}, {}
            for item in manifest["entries"]:
                key, kind = item["path"], item["kind"]
                if kind == "external_reference":
                    continue  # Never materialize external resource authority.
                if key == "secrets" or key.startswith("secrets/"):
                    if kind == "symlink":
                        raise ValueError("Review linked credential files before restoration")
                if kind == "directory":
                    desired[key] = {"kind": kind, "mode": 0o700}
                elif kind == "symlink":
                    desired[key] = {"kind": "link", "target": item["target"]}
                else:
                    desired[key] = {
                        "kind": "file",
                        "mode": 0o700 if item["executable"] else 0o600,
                        "size": item["size"],
                        "sha256": item["sha256"],
                    }
                    sources[key] = {"source": "backup", "signature": source_catalog[key]["signature"]}
            conflicts = []
            for key, item in old.items():
                if key != "secrets" and not key.startswith("secrets/"):
                    continue
                if item["kind"] == "link" or key in desired and desired[key]["kind"] != item["kind"]:
                    raise ValueError("Review conflicting credential file types before restoring")
                if item["kind"] == "file":
                    if key in desired and desired[key]["sha256"] != item["sha256"]:
                        conflicts.append(key)
                    desired[key] = {**item, "mode": 0o600}
                    sources[key] = {"source": "current", "signature": current_catalog[key]["signature"]}
                else:
                    desired[key] = {"kind": "directory", "mode": 0o700}
            if conflicts and secrets_policy != "keep_current":
                raise SecretConflict(conflicts)
            request = {
                "schema": 1,
                "operation_id": self.operation,
                "data": str(self.data),
                "backup": str(backup),
                "identity": identity,
                "secrets_policy": secrets_policy,
                "credential_conflicts": conflicts,
                "original": old,
                "original_roots": roots(old, self.data),
                "desired": desired,
                "sources": sources,
            }
            files.write_json(request_path, request)
            state = {"phase": "preparing", "request_sha256": request_hash(request)}
            self.save(state)
        same_tree(self.data, request["original"])
        existing = same_tree(self.incoming, request["desired"], partial=True)
        needed = sum(
            item["size"]
            for key, item in request["desired"].items()
            if item["kind"] == "file" and key not in existing
        )
        # Known unpublished chunks can be replaced on resume; never count a
        # foreign file or symlink as reclaimable space.
        allowed = {
            hashlib.sha256(("incoming/" + key).encode()).hexdigest() + ".part" for key in request["sources"]
        }
        reclaimable = 0
        for path in self.scratch.iterdir():
            if path.name not in allowed:
                raise ValueError("Unknown retained-file restore scratch entry")
            files.ordinary(path.lstat())
            reclaimable += path.stat().st_size
        if shutil.disk_usage(self.root).free + reclaimable < needed + 64 * 1024**2:
            raise ValueError("Restore needs free space for retained files and recovery records")
        for count, (key, item) in enumerate(sorted(request["desired"].items()), 1):
            if canceled():
                raise InterruptedError("Retained-file restoration canceled before publication")
            target = self.incoming / key
            if item["kind"] == "directory":
                target.mkdir(mode=0o700, exist_ok=True)
                private_directory(target)
            elif item["kind"] == "link":
                if exists(target):
                    if not target.is_symlink() or os.readlink(target) != item["target"]:
                        raise ValueError("Staged restore link changed")
                else:
                    target.symlink_to(item["target"])
                    files.sync(target.parent)
            else:
                entry = request["sources"][key]
                root = self.data if entry["source"] == "current" else source
                if (
                    files.copy_file(root, key, target, entry["signature"], self.scratch, canceled=canceled)
                    != item["sha256"]
                ):
                    raise ValueError("The staged restore file differs from its frozen source")
                if item["mode"] == 0o600:
                    os.chmod(target, 0o600, follow_symlinks=False)
            progress(count, len(request["desired"]))
        same_tree(self.data, request["original"])
        same_tree(self.incoming, request["desired"])
        state.update(phase="prepared", new_roots=roots(request["desired"], self.incoming))
        self.save(state)
        return state

    def require_root(self, container, name, expected, tree):
        path = container / name
        info = path.lstat()
        if [info.st_dev, info.st_ino] != expected:
            raise ValueError("Restore directory/file identity changed")
        actual = inventory(container, prefix=name)
        if subtree(actual, name) != subtree(tree, name):
            raise ValueError("Restore root contents changed; originals retained")

    def move(self, source, target, name):
        if len(files.relative(name).parts) != 1:
            raise ValueError("Only frozen application root entries may move during restore")
        descriptors = []
        try:
            for parent in (source, target):
                private_directory(parent)
                descriptors.append(os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW))
            if exists(target / name):
                raise ValueError("An unexpected restore destination exists")
            os.rename(name, name, src_dir_fd=descriptors[0], dst_dir_fd=descriptors[1])
            for fd in descriptors:
                os.fsync(fd)
        finally:
            for fd in descriptors:
                os.close(fd)

    def publish(self, *, progress=lambda *_: None):
        request, state = self.load()
        if state["phase"] in {"published", "committed"}:
            same_tree(self.data, request["desired"])
            return state
        if state["phase"] not in {"prepared", "publishing"}:
            raise ValueError("Only fully prepared retained files may be published")
        names = sorted(set(request["original_roots"]) | set(state["new_roots"]))
        if state["phase"] == "prepared":
            same_tree(self.data, request["original"])
            same_tree(self.incoming, request["desired"])
            state["phase"] = "publishing"
            self.save(state)
        for count, name in enumerate(names, 1):
            if name in request["original_roots"]:
                if exists(self.originals / name):
                    self.require_root(
                        self.originals, name, request["original_roots"][name], request["original"]
                    )
                else:
                    self.require_root(self.data, name, request["original_roots"][name], request["original"])
                    self.move(self.data, self.originals, name)
            if name in state["new_roots"]:
                if exists(self.incoming / name):
                    self.require_root(self.incoming, name, state["new_roots"][name], request["desired"])
                    self.move(self.incoming, self.data, name)
                else:
                    self.require_root(self.data, name, state["new_roots"][name], request["desired"])
            elif exists(self.data / name):
                raise ValueError("An unexpected live file appeared during restore")
            progress(count, len(names))
        same_tree(self.data, request["desired"])
        state["phase"] = "published"
        self.save(state)
        return state

    def abort(self):
        request, state = self.load()
        if state["phase"] in {"committed", "aborted"}:
            if state["phase"] == "committed":
                raise ValueError(
                    "The restored database was committed; automatic file rollback is unavailable"
                )
            return state
        if state["phase"] in {"preparing", "prepared"}:
            state["phase"] = "aborted"  # No live file was published.
            self.save(state)
            return state
        state["phase"] = "aborting"
        self.save(state)
        for name in reversed(sorted(set(request["original_roots"]) | set(state["new_roots"]))):
            new = state["new_roots"].get(name)
            old = request["original_roots"].get(name)
            if new is not None and not exists(self.incoming / name):
                if exists(self.discarded / name):
                    self.require_root(self.discarded, name, new, request["desired"])
                else:
                    self.require_root(self.data, name, new, request["desired"])
                    self.move(self.data, self.discarded, name)
            if old is not None:
                if exists(self.originals / name):
                    self.require_root(self.originals, name, old, request["original"])
                    self.move(self.originals, self.data, name)
                else:
                    self.require_root(self.data, name, old, request["original"])
            elif exists(self.data / name):
                raise ValueError("An unrelated file appeared during restore rollback")
        same_tree(self.data, request["original"])
        state["phase"] = "aborted"
        self.save(state)
        return state

    def commit(self):
        request, state = self.load()
        if state["phase"] not in {"published", "committed"}:
            raise ValueError("Only published files can finish the database/file restore")
        same_tree(self.data, request["desired"])
        state["phase"] = "committed"
        self.save(state)
        return state
