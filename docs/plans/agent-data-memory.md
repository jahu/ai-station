# Scoped memory in local agent analysis

Prior gap: selecting Files & data or Local coding with memory_search or
project_memory is rejected by the exclusive coding-family validator. Thus an
agent cannot use its saved observations while analysing data. Data results also
cannot opt into the existing Remember reports tool.

Reuse the existing context child Runs and verified offline JSON input. Add own
agent memory and explicitly linked project memory as reviewed local context;
exclude all other agents/projects, global and disabled memories. Freeze original
entry IDs, versions and provenance in a bounded JSON artifact. Before executing,
verify the source bytes, owning workflow, scope and still-authorized entry
versions. Historical captures stay inspectable independently of live edits.

Local code/Python receives captured text only, never unrestricted memory tools or
new network authority. Files are optional when scoped context is explicitly
selected; an empty memory observation must remain visibly empty, not invented
facts. Preserve existing public-source order and old definition identities.
Existing artifact/source projections must show memory observations and provenance.

For Python data agents, optionally support Remember reports after the final
validated result. Reuse MemoryEntry and persist_agent_memory; save a bounded
answer/table and result links in the agent's own scope. Grant memory_write to the result-inspection child, never generated code or its
model-generation child. Metadata dispatch stages retain their existing reviewed
workflow authority. Failure, Stop or uncertain cleanup must save no memory. Retention remains
explicitly selected and inspectable in Memory.

No schema, native executor or model download is needed. Existing shared deadline,
approval, Task-wide Stop and conservative recovery remain. Both agent editors
should explain scoped context and distinguish it from public research.

Acceptance: a two-execution data agent reads only its own memory, processes a
verified snapshot offline, remembers its validated first answer and observes it
on the second execution. Test project scope, disabled/edited entries, tampered
artifacts, Stop/failure without retention, exact child permissions and legacy
public/HTTP workflows. Qualify compiled desktop/mobile editing and the real
native Python path separately from fake inference. Keep #409 live until this
reviewed feature passes its own gates and release verification.


Implementation and focused verification are recorded in PR #410. Thirteen new
backend cases cover own/project scope, changed/deactivated/tampered captures,
Stop, failed Python, atomic retention rollback and Local coding handoff. Actual
native Docker Python ran two consecutive analyses on each compiled desktop/mobile
case; the second consumed the first retained result. These checks inject inference
and do not claim new model/GPU qualification. Full-gate and deployment authority
are in `data/acceptance/agent-data-memory-20261024`, especially
`workspace-full-check-result.json` and `post-deployment-qualified.json`.
