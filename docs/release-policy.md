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
from leaving advisory reviews. GitHub also prevents authors from approving their
own PRs. Automation currently authenticates as @jahu, so an owner-authored release
PR needs a separate contributor/App identity as author before mandatory owner
approval can be satisfied. Do not weaken protection or count an agent acting as
@jahu as the owner's human approval.

See GitHub's [protected branch documentation](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches).
