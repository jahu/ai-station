# Release branch policy

`develop` is the integration branch. Feature/fix pull requests receive full diff
review and successful validation, then use squash merge. Hosted Actions are
currently manual; equivalent successful local checks are required. Actual test
failures are not waived.

`master` is the default release branch. **Only the human owner @jahu may approve
and merge a pull request into master.** Agents prepare release PRs and evidence,
but must not approve or merge them using the owner's credentials. Earlier general
permission for autonomous release work does not override this rule. Never push
directly to `master` or `main`, rewrite history or move a published release tag.

## GitHub enforcement

The owner made the repository public on 2026-10-26. The earlier private/free-plan
restriction no longer applies. **Server-enforced protection is active on master**,
verified through GitHub's branch-protection API:

- Require a pull request with one approving review and code-owner approval.
- [CODEOWNERS](../.github/CODEOWNERS) names only @jahu.
- Dismiss stale approvals after new commits and require resolved review conversations.
- Block force pushes and branch deletion.
- Enforce these requirements for administrators too; no review bypass is configured.

Required hosted status checks remain unset under the existing local-verification
policy. This does not waive actual failed checks. Linear history is not required,
so release promotions can preserve `develop` ancestry with merge commits.

The owner-only release merge policy above still applies: required code-owner
review gates approval, but does not restrict the merge button to a named user.
Classic named-user push restrictions are unavailable for personal repositories.
Review or change the rule under **Settings → Branches → master**.

Code-owner review makes the owner's approval necessary; it does not stop others
from leaving advisory reviews. GitHub prevents authors from approving their own
PRs, so release PRs are created by **github-actions[bot]**, not the owner's CLI
identity. Do not weaken protection or count an agent acting as @jahu as the
owner's human approval.

## Prepare a release PR

After reviewing and validating `develop`, the owner or an authorized agent using
the owner's CLI session runs:

```bash
gh workflow run ci.yml --ref develop -f operation=release-pr
```

The existing manually dispatched CI workflow has two operations. Its default,
`checks`, retains the normal checks. `release-pr` runs only the short release job
with GitHub's automatically issued, repository-scoped token: `contents: read` and
`pull-requests: write`. It performs no checkout, code execution from the worktree,
approval, merge, push, tag or deployment, and needs no stored PAT/App secret or
additional account. The owner must enable Actions' **Allow GitHub Actions to
create and approve pull requests** repository setting; despite the setting's
combined name, this workflow only creates PRs and cannot satisfy @jahu's required
code-owner approval.

Only an owner-triggered run on `develop` can prepare the fixed `develop → master`
PR. Repeated runs reuse an existing bot-authored PR; no file differences create
no PR. An existing release PR with another author is reported for owner
resolution, never closed or replaced silently. Release jobs serialize to prevent
duplicate PRs. This operation prepares a proposal; it does not assert that checks
or human review have passed.

Use the PR link in the run summary, inspect the final diff and verification,
then approve and merge using the human owner account. New commits dismiss the
approval. Agents never submit that approval or merge master. See
[workflow token authentication](https://docs.github.com/en/actions/tutorials/authenticate-with-github_token).

See GitHub's [protected branch documentation](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches).
