# Create files from the current conversation

Observed regression: a user supplies values in ordinary Chat, then asks for an
Excel workbook using the numbers discussed above. The data generator receives
only the last instruction and empty guidance, losing the supplied values. The
owned integration regression records this in
`data/acceptance/creation-conversation-context-red.log`.

Reuse the existing creation workflow. At enqueue, freeze bounded recent plain
user/assistant text from this conversation, with source message IDs, hashes and
explicit excerpt/older-context flags. Exclude partial/superseded/routing-only
messages and system/tool records. Do not inherit attachment contents, Artifact
IDs, URLs, tools or permissions. No source fetches, hidden memory or new provider.
Record the same snapshot on the submitted user message and orchestration Run;
validate ownership, unchanged source text and the exact snapshot before worker
stages. Only creation uses it; ordinary analysis, persistent-agent definitions and
legacy records retain their existing identity.

Supply the quoted text as reference data under the current instruction, never as
system authority or evidence of current external facts. Clearly label truncation;
missing exact values must remain missing. Preserve one original deadline, empty
native input map, all output validation and Stop/recovery semantics. In Chat, a
compact expandable note lets the user inspect exactly which earlier text was used.

Prove current instructions override history; unrelated conversations and excluded
messages cannot leak; changed snapshots/source bytes, forged scopes and Stop refuse
work. Test bounds, legacy identities, zero-input/repair paths and actual generated
request content. Run required full local gates and compiled desktop/mobile
first/follow-up/reload/Stop checks. Reuse unchanged native/source qualifications;
qualify a small real model/CPU example only after review and backed-up deployment.
