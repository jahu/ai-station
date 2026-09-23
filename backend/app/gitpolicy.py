"""Protected-branch policy. Agents never rewrite production history."""

from __future__ import annotations


class GitPolicyError(Exception):
    pass


DEFAULT_PR_POLICY = {
    "commit_task_branch": True,
    "push_task_branch": False,
    "pr_to_integration": False,
    "pr_to_production": False,
    "automatic_merge": False,
    "force_push": False,
}


def normalize_policy(raw: dict | None) -> dict:
    policy = dict(DEFAULT_PR_POLICY)
    for key, value in (raw or {}).items():
        if key in policy:
            policy[key] = bool(value)
    policy["force_push"] = False
    policy["automatic_merge"] = False
    policy["pr_to_production"] = False
    return policy


def assert_branch_allowed(branch: str, protected: list[str], *, action: str) -> None:
    name = branch.strip()
    if name in set(protected) or name in {"main", "master"}:
        raise GitPolicyError(f"{action} is refused on protected branch {name}")
    if not name.startswith("ai/"):
        raise GitPolicyError(f"{action} is only automatic on ai/ task branches")


def assert_push_allowed(policy: dict, branch: str, protected: list[str], *, target: str) -> None:
    policy = normalize_policy(policy)
    if policy.get("force_push"):
        raise GitPolicyError("Force push is disabled")
    assert_branch_allowed(branch, protected, action="push")
    if target in set(protected) or target in {"main", "master"}:
        raise GitPolicyError("Push or merge into a protected branch is disabled")
    if target == "production" or not policy.get("push_task_branch"):
        if target != branch:
            raise GitPolicyError("Push target does not match the task branch policy")
    if not policy.get("push_task_branch"):
        raise GitPolicyError("Pushing the task branch is disabled by project policy")
