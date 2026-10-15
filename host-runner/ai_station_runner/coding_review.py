"""Bound cumulative review independently of the context sent to a model."""

import hashlib
import json

from ai_station_runner.coding_files import (
    MAX_REVIEW_FILE,
    MAX_REVIEW_TOTAL,
    describe_change,
    read_review_files,
)
from ai_station_runner.source_inventory import source_file_args

MAX_REPORT = 1024 * 1024


def projected_review(repo, workspace, selected, proposal, *, cumulative, repair=False):
    names = [item["path"] for item in selected]
    if cumulative:
        dirty = repo.read(["diff", "--name-only", "-z", "HEAD"]).stdout
        dirty += repo.read(source_file_args()).stdout
        names = list(dict.fromkeys([*names, *filter(None, dirty.split("\0"))]))
    snapshots = read_review_files(workspace, names)
    replacements = {item["path"]: item["content"] for item in proposal["files"]}
    changes, base_size, projected_size = [], 0, 0
    by_name = {item["path"]: item for item in snapshots}
    reviewed = snapshots if cumulative or repair else [by_name[item["path"]] for item in proposal["files"]]
    for item in reviewed:
        content = replacements.get(item["path"], item["content"])
        projected_size += len((content or "").encode())
        original = item
        if cumulative or repair:
            blob = repo.read(["show", f"HEAD:{item['path']}"], check=False)
            original = {**item, "content": None, "sha256": None}
            if blob.returncode == 0:
                mode = repo.read(["ls-tree", "HEAD", "--", item["path"]]).stdout.split()[0]
                if mode not in {"100644", "100755"}:
                    raise ValueError("Cumulative review requires ordinary source files")
                encoded = blob.stdout.encode()
                if len(encoded) > MAX_REVIEW_FILE or "\0" in blob.stdout:
                    raise ValueError("Task base exceeds bounded text review")
                base_size += len(encoded)
                if base_size > MAX_REVIEW_TOTAL:
                    raise ValueError("Task base exceeds its aggregate review bound")
                original.update(
                    content=blob.stdout, sha256=hashlib.sha256(encoded).hexdigest(), mode=int(mode, 8) & 0o777
                )
            elif repo.read(["ls-tree", "HEAD", "--", item["path"]]).stdout:
                raise ValueError("Could not read the task base for review")
        if original["content"] != content:
            changes.append(describe_change(original, {"path": item["path"], "content": content}))
    if base_size > MAX_REVIEW_TOTAL or projected_size > MAX_REVIEW_TOTAL:
        raise ValueError("Cumulative review exceeds its aggregate bound")
    return changes, snapshots


def checked_report_bytes(report):
    value = json.dumps(report).encode()
    if len(value) > MAX_REPORT:
        raise ValueError("Coding review exceeds 1 MiB; checkpoint reviewed changes or narrow this task")
    return value
