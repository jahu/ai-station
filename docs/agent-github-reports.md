# Scheduled GitHub reports

Agents can use **GitHub repository** to read a connected repository and prepare a
report with their selected local model. Natural-language requests mentioning GitHub
start as disabled drafts; choose the repository, local model, tools and schedule
before enabling. The same reviewed scope can be saved in the Agents editor or the
agent draft inside Chat/Work. Selecting a repository saves metadata, not a Run.

The definition's optional `github` scope stores a connector UUID and the reviewed
`owner/repository`, persisted by Alembic 0023. It identifies a resource, not a CLI
command. Enabling checks that the connector exists, is enabled and still names
that repository. A later rename, disconnection or retarget cannot redirect a
scheduled read: publication and native dispatch recheck the frozen target and fail
with inspectable history. The tool requires at least 70 seconds maximum runtime;
its fixed native read has a 60-second deadline and checks the remaining workflow
budget before launch. The normal default remains 600 seconds.

A schedule creates ordinary Task → workflow Run → GitHub child Run → local report
Run → artifacts. The child receives only `network_read` and `github_read`, even
when the parent also has memory permissions. Existing approval, dependencies,
owned-process Stop and conservative recovery apply. The tool is a pre-report
workflow step; models cannot ask it to read arbitrary repositories or make account
writes. GitHub credentials stay with the existing native gh session.

The complete snapshot retains up to 30 entries per native list. Local inference
receives at most ten issue and ten PR titles, each shortened to 180 characters,
with URLs, capture time, snapshot counts and explicit excerpt/untrusted markers.
Counts describe this bounded observation, not complete repository totals. Source
files and comments are not fetched. Only the selected local provider prepares the
report; no external-AI permission is granted. Optional Remember reports uses the
existing agent-scoped memory/provenance contract. Memory search can retrieve that
report on the next execution. Raw GitHub snapshots are not implicitly copied into
memory by Remember workflow observations.

Connectors show the current refresh and retain the latest successful snapshot for
the same target. Completion updates its query key, so finishing between two UI
polls does not leave the previous snapshot displayed. Concurrent reads retain the
checking indicator until the other active reads finish.

Normal coverage uses disposable databases, fake gh/LLM responses and the shared
native cancellation/recovery tests. It checks target persistence, migration of old
definitions, minimal child permissions, bounded local context, changed targets,
expired budgets, draft activation and snapshot refresh. No real integration runs
without explicit opt-in.

On 2026-10-15, two actual interval executions read jahu/ai-station using native gh
GET and generated reports through the configured local qwen3:8b endpoint. All
eight Runs succeeded, two scoped memories were saved, and the second execution
retrieved the first report. The agent was paused afterward. A final-source
one-shot execution also passed after refining the report instructions and context
labels. Evidence: `data/acceptance/agent-github-20261015/real-result.json` and
`final-oneshot/real-result.json`. These prove those exact tools/model/schedules;
normal automated tests remain fake and do not consume inference or network calls.
