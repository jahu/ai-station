# Website-agent build policy

The isolated preview is delivered. Project-free Local agents already create their
own private Git project; this foundation must be reused. The remaining gap is that
new agent projects deliberately default to no dependency installation/checks, so a
website request can end with source edits and no verified build to preview.

Add an inspectable saved `workspace_policy` to Agent definitions, defaulting to
both automation flags off for existing agents. Explicit website-building drafts
may propose installing declared public dependencies and running detected checks;
they remain disabled until reviewed activation. Expose these choices beside the
private-workspace/project scope, including the possible public package downloads.
The setting applies only to a newly created private Local coding workspace. A
linked existing project's saved policy remains authoritative and is never changed
by enabling an agent. External coding and spreadsheet tools cannot acquire this
policy. No new shell, tools, execution target or permission profile is introduced.

Freeze the policy with the agent definition, validate its exact setup provenance,
pass it into ordinary project setup, and reuse existing dependency/validation/build
Runs. Stop/deadline and immutable project-check policy remain unchanged. Website
model guidance requests a complete self-contained static build, declared package
manifest/build/test scripts and usable output; actual success still requires the
existing checks and build artifact producer. No generated page may widen network
or execution scope. Failed builds stay visible and cannot publish a preview.

Acceptance: migrate old definitions with automation off; create/reload/duplicate
policies; reject incompatible tools; freeze/verify workspace adoption and guard
against policy tampering; preserve linked-project policies and legacy defaults;
retain public-page sources, same Task and Stop; verify UI review/save and package
scope. Then qualify the full reviewed-URL → local model → build → preview →
follow-up path with disposable sources. Do not unload the operator's separately
selected model solely for UI tests or claim a fake-provider run as real inference.

## Implementation and evidence — 2026-10-22

The new JSON definition field and Alembic migration 0028 are implemented. Existing
agents retain automation off. Explicit Local website drafts propose both flags
and a 30-minute total deadline; generic coding/data/external agents retain their
previous defaults. Settings and conversation definition cards expose dependency
scope and build preferences; ordinary unrelated edits preserve them. Linked
projects keep their saved policy. Workspace setup verifies the exact frozen
preferences before adoption; coding guidance follows the actual project policy.

Focused backend coverage passed 133 tests, including migration downgrade/upgrade,
API save/reload/duplicate, legacy defaults, frozen setup tampering and existing
project preservation. Focused UI coverage passed 80 tests, TypeScript/build/lint
passed, and actual compiled desktop/mobile checks passed at 1440/390 without a
worker, model or project execution. Evidence is under
`data/acceptance/agent-website-build-policy-20261022`; earlier focused command logs
are retained with `next-workspace-` names in the preview acceptance directory.
Full regression and release review remain required. This is not a claim that the
new end-to-end website/model/build flow was already executed on real GPUs.

Factory scope review found an ambiguity: “create an agent that reads CSV files
from a website” must not become a website builder or acquire build automation.
Website creation verbs now bind to the site itself, with explicit Polish/English
modifiers. The focused factory/page-coding scope suite passed 34 tests, including
this negative case. The earlier full check was invalidated by this actual source
fix; its output is retained as preliminary, not release qualification.

## Final local qualification

The corrected frozen source passed **1844 Python tests**, eight explicitly opt-in
integrations skipped, and Ruff. The unchanged frontend passed **526 UI tests**,
format/lint/types/build and both Compose configs; the final backend image was
rebuilt and its backend files plus compiled frontend assets matched the reviewed
source. Actual desktop/mobile definition review/save/reload passed on the final
factory code without worker/model execution. The source-bound regression results,
image proof and browser record are under the acceptance directory above. These
checks qualify policy propagation; the separate real-model website scenario is
still pending. Native source matches deployed PR #337 and needs no Runner restart.
