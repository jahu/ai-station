# Contributing to AI Station

Issues, documentation improvements and pull requests are welcome. For a private
repository, contributors first need repository access from the maintainer.

Read [AGENTS.md](AGENTS.md), [the architecture](docs/architecture.md) and the
[development guide](docs/getting-started.md). Work on a feature or fix branch and
target **develop**. Include relevant validation and keep unrelated changes out
of the pull request.

## Contributor rights

AI Station uses [PolyForm Noncommercial 1.0.0](LICENSE) and may also be offered
under separate commercial licenses. **You retain copyright to your work.**

Before an external contribution is merged, the maintainer must obtain a separate
written contributor agreement from its rights holder that permits the maintainer
to distribute and license that contribution under both the project's
noncommercial terms and separate commercial terms. Employer-owned contributions
need authorization from the employer or other actual rights holder.

The noncommercial license, a DCO sign-off or opening a pull request alone does
not supply that commercial relicensing permission. The maintainer must record
the signed agreement before merging; until then, the contribution can be
discussed and reviewed but must remain unmerged. No CLA-signing service is
configured yet; agreement handling is manual.

Only contribute material you have the right to submit. Identify third-party
material and its license; a contributor agreement does not override someone
else's rights. Do not include private files, credentials, model weights or
unapproved screenshots from your Library.

## Release review

Feature pull requests receive full diff review and successful local checks before
squash merging into `develop`. Only the human repository owner **@jahu** may
approve and merge release pull requests into `master`. Agents prepare the pull
request and validation evidence, then wait for the owner's review.

See [the release branch policy](docs/release-policy.md), including the current
GitHub plan limitation on server-enforced protection.
