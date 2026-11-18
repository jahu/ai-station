# Personal memory across conversations

Goal, 2026-11-18: AI Station should learn useful personal context from ordinary
conversations, consolidate it, and recall it in new chats, with optional,
inspectable local memory. This is not satisfied by a manual CRUD page or vectors.

## Evidence and cause

Current Chat only snapshots pinned global/current-conversation entries. It never
extracts personal facts automatically; summaries are conversation-local and
normally disabled. Automatic orchestration decisions do not receive personal
memory. Embeddings power an explicit Memory-page search/index, not Chat recall.
The production metadata audit found six agent/project entries, zero personal
entries, zero conversation summaries and three vectors. A local 384-dimensional
E5 CPU encoder is configured; missing model installation is not the primary cause.
No production conversation content was exported for this audit.

Official behavior consulted on 2026-11-18:

- [ChatGPT Memory](https://help.openai.com/en/articles/8590148-memory-in-chatgpt):
  saved information and relevant past-chat context can inform later conversations;
  users can review, correct, delete and disable it. History and memory are distinct.
- [Claude memory](https://support.claude.com/en/articles/11817273-use-claude-s-chat-search-and-memory-to-build-on-previous-context):
  topic-oriented memories are updated as users converse; past-chat search is
  separately observable. Per-chat controls and project boundaries matter.

These are public product contracts, not claims about either vendor's private
implementation. AI Station will reuse its SQLite/FTS, local encoder, model
providers and Task → Run → Events → Artifacts rather than add a vector service.

## Delivery contract

1. Personal preferences belong to each account, not machine Settings. Separate
   use of saved memory from automatic learning. Existing manually pinned behavior
   remains compatible; new automatic learning requires an explicit opt-in. A
   visible Memory panel in Chat and Memory explains and controls it. A conversation
   can opt out without changing other conversations. History is still saved;
   this is not an incognito/ephemeral-history feature.
2. Successful visible turns schedule a bounded, durable local extraction Run.
   Both ordinary Chat and unified orchestration must use the same integration.
   Only original user text is evidence. Tool/web/file content, reasoning and model
   assertions cannot become user facts. The selected local model is reused through
   the existing provider/managed-runtime lifecycle; no hidden external extraction,
   downloads or shell authority. Failed/canceled/internal planning turns save none.
3. A closed structured proposal chooses durable facts/preferences, exact source
   quotes and stable topic keys. Extraction sees only original user text and topic
   vocabulary, never stored values/IDs or assistant answers. The server resolves
   consolidation against owned entries and optimistic versions. Validate quotes
   against owned messages before publication. Merge repetitions; update newer
   explicit corrections. Never overwrite manual edits or unrelated scoped entries.
   Preserve creation provenance plus bounded update evidence. Serial owner-scoped
   jobs and version checks avoid stale/concurrent overwrites. Malformed output has
   bounded repair and a visible failure, never a fabricated memory or failed chat.
4. Recall automatically combines bounded profile facts, relevant FTS matches and
   current local semantic matches when the encoder is ready. Pinned context remains
   available. Recall applies before both controller decisions and final replies.
   Keep request handlers free of inference: embedding/model work runs in workers.
   Persist exact IDs, versions, context and retrieval method in ordinary Runs.
   Missing/unavailable embeddings degrade visibly to working lexical/profile recall;
   no download or expensive model switch occurs just to search memory.
5. New/updated facts are indexed automatically using the existing CPU embedding
   executor. Coalesce indexing safely and invalidate old vectors on edit. No GPU
   eviction/reload is needed for the encoder. Freeze model identity and respect
   the normal claim/cancel/deadline/recovery contracts.
6. Check consent again before reading/inference/publication, not merely at enqueue.
   Disable/forget prevents pending jobs from publishing unwanted data. Deleted facts
   are not recreated from the same previously processed messages; retain bounded
   non-content suppression keys and source-processing receipts. Disabling keeps an
   inspectable entry without automatic reactivation. Historical Run snapshots stay
   audit records and are not silently rewritten.
7. Memory UI shows automatic versus manual entries, provenance/update evidence,
   learning/indexing status, corrections, disable/delete, and a concise personal
   overview. Chat shows memory on/off and memory used/saved with inspectable links.
   Account-level off and per-conversation off must actually stop learning/recall.
8. Explicit opt-in learning from existing owned conversations handles previously
   discussed facts without scanning all history silently. Bounded batches, stable
   source identities, visible progress/Stop and already-processed/deleted-message
   exclusion use ordinary Runs. Other accounts/projects/agents are excluded.
9. Preserve account, project and agent isolation. Global personal means account-
   private. Existing agent report retention and explicit project memory contracts
   retain their current permissions and behavior. No universal memory-write grant.

## Implementation and verification

- Add an Alembic migration for conversation opt-out and memory learning metadata;
  use existing UserSetting preferences, Message metadata and owned Run receipts.
- Implement scoped consent/settings, extraction/consolidation and automatic index
  scheduling; integrate successful visible turn completion once, idempotently.
- Implement worker recall and context integration for direct Chat and controller;
  keep bounded readable profile/FTS fallback and immutable retrieval evidence.
- Build the consent/provenance/status experience and history-learning operation.
- Temporary DB/fake providers test: cross-chat name and preferences, corrections,
  repetition, manual edits, forgotten/disabled facts, opt-out before/during work,
  malformed/injected proposals, wrong ownership/scope, cancellation, restart,
  dependencies, semantic identity/index refresh and missing-encoder fallback.
- Real opt-in local model/CPU embedding smoke in an isolated temporary account:
  ordinary introduction → extraction → new conversation recall → correction →
  later recall → forget/off. Test unified orchestration as well as direct Chat.
  Verify desktop/mobile UI, then full local checks, review/PR to develop, preserving
  deployment and cleanup. No production chat backfill or opt-in is forced.

Completion requires the end-to-end behavior above, not documentation or green
unit checks alone. Record exact evidence and limitations. Keep source/fixtures
small, reuse installed models, remove owned test helpers and temporary data after
verification, and preserve the user's dirty root checkout.

## Real-model finding and design correction — 2026-11-18

The first local Qwen 9B acceptance successfully saved a name and recalled it
semantically in a new conversation. However, extraction from the subsequent
question echoed the saved name and mistyped its UUID. Supplying saved values to
the extractor created a feedback path: an existing fact could be presented as
new user evidence. An exact quotation alone does not prove semantic support.

The extractor now receives source text plus topic vocabulary only. Consolidation
and database IDs stay server-owned; inference cannot copy/mistype an entry ID.
No-fact responses have an explicit empty-object envelope; an empty root list is
also a safe no-op. Nonempty untyped lists/unknown fields remain rejected. Stored
facts still inform the separate answer/decision recall path, never extraction.
This is a general evidence boundary, not a question/name-specific classifier.
