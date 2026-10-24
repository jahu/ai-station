# Public data analysis and captured-source follow-ups in conversations

Status: implementation candidate after deployed/real-qualified research/data
agents (#390). The implementation worktree is `.tools/conversation-research-data`,
branch `feat/conversation-research-data`, based on develop `2da23e7`.
Qualification is recorded under `data/acceptance/conversation-research-data-20261024`.
Inspect its records before claiming deployment or actual local-model acceptance.
Fake inference, real isolated CPU and actual public/local-model checks are separate.

## User outcome

A conversation can analyse explicitly reviewed public search/page observations,
optionally combine them with CSV/Excel/JSON files, and return its ordinary inline
answer, table, chart and downloads. No persistent agent or repository setup is
required. A follow-up such as “draw a chart from those data” uses the same captured
observations offline. Only an explicit fresh-source request may fetch again.
Ordinary conversation/file analysis, agent scopes and saved history remain valid.

## Existing implementation to reuse

`conversation_data.py` already binds an orchestrator message to a private project,
an ordinary agent_workflow without an Agent row, and the shared offline data
pipeline. `data_research.py` and `agent_page_coding.py` now verify reviewed public
source Runs and create one immutable complete-observation JSON input. Reuse those
components and the existing local-model admission, Python execution, output
validation, repair, deadline, Stop and result projections. No native operation,
execution engine, schema migration, dependency or model download is needed.

## Typed scope and authority

1. Add an optional typed research selection to the conversation DataScope:
   reviewed public query, reviewed URLs and whether to read search-result pages.
   Compute only the existing web_search/search_pages/http_fetch tools; require a
   query for search-page reads and at least one selected source. Reuse current
   public-URL validation and limits. Never accept model-selected paths, artifact
   IDs, providers, tools, credentials or project IDs in that scope.
2. Files are optional only with that explicit public selection. Leave standalone
   AgentDataScope and conversation requests without research minimum-one/eight
   inputs. Research consumes one of eight Python slots, leaving seven files.
   Preserve absent-research serialization exactly: adding a nullable default must
   not change old receipts, stored message bindings or read-only projections.
3. Web availability alone grants no data execution. An explicit analysis action
   selects its typed sources; strong current-user analysis instructions plus
   explicit current-user URLs in Chat or Work may select the same action deterministically.
   Quotes, attachments, fetched content, prior replies and model output cannot
   select new public targets. Manual queries retain their authority. Keep ordinary
   Chat page reading/search and the existing offline CSV route unchanged.
4. Freeze the selected scope on the user message and orchestrator Run. Grant
   exactly the existing data permissions and any separately reviewed research
   authority. The existing data permission set includes network_read for local
   provider transport; that flag alone never grants public URL/query selection. HTTP handlers validate/enqueue; only workers fetch or inspect.
   Validate same conversation/message/Task/project and original deadline before
   publishing research or code. Replays must resolve to the same scope and Task.
5. Agent-free research is accepted only through validate_workflow/root_binding's
   exact controller-owned conversation origin. Do not simply remove the current
   persistent-agent checks in data_research: reuse must prove its own origin,
   source manifests/dependencies, grants, byte hashes and handoff-child ownership.

## JSON inputs and offline source reuse

General bounded JSON inspection is the needed input capability, not a second
research execution path. Extend the existing data upload/inspection and preview
contracts to JSON objects/arrays, preserving raw bytes. Bound bytes, nesting,
preview values/rows and processing; reject invalid JSON, duplicate keys and
non-finite numbers. Keep CSV/XLSX behavior and unsupported-file rejection. Python
reads the complete approved file; a JSON preview is never its full input.

Register research snapshots through that same read-only inspection contract. An
inspection child on the same Task can gate the existing data preparation using
RunDependency, so a successful first result guarantees its JSON snapshot is ready
for later ordinary data use. Preserve original source-artifact lineage, hashes,
partial/truncation flags and timestamps. Metadata inspection grants no network or
code execution of its own.

Extend the current same-conversation natural data-reference resolver to adopt the
completed result's verified input IDs, including its inspected captured-source
JSON. A reused snapshot becomes an ordinary offline input on the new data Task:
no research tools or public requests. Existing local-provider transport
permissions retain their established meaning; the Python child has no network
grant. The controller derives
this scope from the prior successful same-conversation result; it does not trust
an injected input ID or earlier model prose. Verify original input bytes and source
lineage before generation and dispatch. Reuse the existing previous-question/
answer context as untrusted guidance. Freeze a new deadline for the new question;
all repairs keep that deadline and exact inputs. Explicit refresh creates a new
reviewed research scope and new immutable source observations instead of replacing
old files or silently refreshing them.

## UX

Keep the transcript/results as the workspace. Extend the existing analysis controls
with concise public-source selection and optional files, local model/Auto and
existing advanced repair settings. Use the same compatible source UI and warnings
as agents, within the correct Task. Show whether a follow-up uses captured sources
and their original timestamp; offer an explicit refresh choice. No technical JSON
path, worktree or repository setup should be required. JSON upload previews belong
in the current Library picker/inspection component, with accurate file types.

## Qualification before release

- Fake network/model/Python, temporary DBs and real owned Git: typed scope,
  activation, source-only and mixed-file tasks, exact permissions/receipts/origin,
  foreign message/Task/source rejection, tampered bytes/lineage, partial sources,
  deadline, repair and Stop before each stage. Old CSV-only and agent workflows
  must remain covered by the unchanged normal suite.
- JSON parser limits and hostile inputs; real offline CPU code consumes complete
  nested JSON beyond the preview, combines it with CSV, and leaves originals intact.
- Compiled desktop/phone: source selection, Send, streamed progress, inline sources/
  answer/chart/table/downloads, natural same-captured-data follow-up, explicit
  refresh, reload and Stop. Count actual public requests to prove reuse is offline.
- Full successful local checks, complete PR diff review and image/source/assets
  verification; squash to develop and backed-up controller-only deployment.
- Actual free public JSON + local model + native Python: compare computed rows to
  the captured source, then follow up without another public read. Distinguish
  fake/CPU/actual model proof and restore the exact operator model preset afterward.

The whole-platform goal remains active. Remaining media resource admission/quality,
recognition approval and restore/private remote operations are not waived by this
increment. Root Memory WIP and the live/proof worktrees for #390 remain untouched.
