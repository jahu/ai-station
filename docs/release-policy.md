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

On 2026-10-26, GitHub's branch-protection and ruleset APIs both returned HTTP 403
for this private repository: these features require upgrading to GitHub Pro or
making the repository public. **Server-enforced protection is not enabled.**
The repository has not been made public.

[CODEOWNERS](../.github/CODEOWNERS) declares @jahu as the code owner, but it does
not by itself prevent direct pushes, other reviews or merges. This is currently
a contributor/agent policy, not a technical access-control guarantee. GitHub's
CODEOWNERS feature itself also requires a supported plan for private repositories;
the file is prepared for that future configuration.

When the plan supports protection, configure an exact `master` rule in
**Settings → Branches** (or **Rules → Rulesets**) to:

- Require a pull request and code-owner approval before merging.
- Dismiss stale approvals after new commits and require resolved review conversations.
- Block force pushes and deletion; prevent bypass where supported.
- Keep only the owner authorized for release merges; collaborators use PRs.

Code-owner review makes the owner's approval necessary; it does not stop others
from leaving advisory reviews. GitHub also prevents authors from approving their
own PRs. Automation currently authenticates as @jahu, so an owner-authored release
PR needs a separate contributor/App identity as author before mandatory owner
approval can be satisfied. Do not weaken protection or count an agent acting as
@jahu as the owner's human approval.

See GitHub's [protected branch documentation](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches).
