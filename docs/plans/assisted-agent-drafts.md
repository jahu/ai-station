# Local AI-assisted agent drafts

Prepare a disabled persistent definition from ordinary instructions using the
selected local model. Keep the existing deterministic draft endpoint for quick,
model-free creation and compatibility; it must remain explicitly labelled in the
UI. The Agents happy path uses the assisted preparation, then opens the existing
review/activation workspace. Creating a draft never enables or runs that agent.

The request enqueues an ordinary Task/Run with a durable client receipt, bounded
local JSON inference, existing model admission/leases/cancellation and a stored
JSON artifact. No inference belongs in an HTTP handler. Only existing operational
local tools may be proposed. Generated definitions pass the normal AgentSettings
validation and remain disabled with no next run. The model cannot provide UUIDs,
credentials, account bindings, project paths, external coding, permission profiles
or activation flags. Fetch URLs must be copied from current user input; generated
search queries are proposals for review, never submitted during preparation.
Page tools are omitted from the drafting catalog when the user supplied no public
URL. A selected page tool must have an explicit reviewed URL, and selected public
search must have a proposed query; otherwise the bounded correction runs before
any draft is saved.

Existing controller-derived market scopes may be preserved for a recognized
explicit quote-watch request; the model cannot change their instruments, thresholds
or account/email bindings. Ordinary stock research keeps public tools.

The model may refine a useful name, goal, instructions, output expectation, tool
selection and supported UTC cadence. Reject unsupported fields and combinations;
a single bounded local correction may fix a malformed definition, with a visible
event. Failures, Stop and interrupted inference publish no agent. Publication,
artifact provenance and terminal status share one database transaction. Receipt
replay returns the existing Run; conflicting reuse is rejected. Recovery follows
the existing conservative policy and never silently repeats uncertain inference.

Agents shows preparation/loading, Stop, durable return through its saved URL and
clear failure/retry states. The normal definition editor remains the authority for
reviewing tools, public query/URLs, data inputs, schedules and activation.
Built-in local-model Work agent requests use the same preparation service as a child Run
on the conversation Task and publish their disabled draft inline. Work with an
another Chat provider preserves an explicitly labelled, model-free quick draft
and requires local model selection before activation. This does not execute a
model-selected workflow or remove existing records.

Normal qualification uses temporary databases and fake local streams: queued-only
handlers, successful source/artifact identity, malformed correction, failed and
canceled inference, permissions, forbidden fields/URLs/tools, receipt replay/races,
model-load dependencies and stale lease recovery. Frontend checks include pending,
Stop, restored URL, errors, model selection and the preserved quick path. Run real
local inference only as an explicitly opted-in acceptance, without Web/tools,
cloud, credentials or model downloads.

Conversation results show a compact goal/model/tools/schedule summary with a
review link; they do not expand the full settings form by default. Existing
in-conversation controls stay available through an explicit edit action, with
reports still visible. Model names resolve through the read-only catalog.
