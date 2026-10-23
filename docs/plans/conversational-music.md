# Music in the main conversation

Status: implemented on the draft Music adapter (#361), not yet deployed. The
operator approved the weights; offline file verification and native 30-second
GPU output passed. Complete execution/release qualification follows the
[local music plan](local-music-generation.md). No new execution boundary.

## One message to an audio result

Chat and Work can select **Generate music** or use an explicit current-turn
request such as `Wygeneruj 60 sekund spokojnej muzyki fortepianowej`. Deterministic
routing queues the same `audio.music` child on the existing conversation Task,
without first loading/calling a text model. The existing inline audio artifact,
Library, Run events, refresh restoration and Task-wide Stop remain authoritative.
Music is local regardless of the model selected for ordinary conversation.

The action scope offers duration, instrumental/supplied lyrics and optional seed
and GPU settings. Share validation with the Audio workspace. Resolve random seed
only once when publishing the child. Parent Run identity provides its receipt;
child publication, message and parent completion commit atomically. No Runner
HTTP or filesystem inspection inside that publication transaction: observe music
readiness first and pass the checked profile to the existing run creator.

## Intent and permission checks

- An explicitly selected music action or a direct current music-generation
  instruction authorizes this operation. Prior answers, attachments, source
  content, quoted examples and the planner's suggestion cannot authorize a GPU
  workload by themselves. Agent/project creation and requests for a written
  prompt/plan retain their respective routes.
- Music settings apply only to that action. Reject mixed project/runtime/Git,
  attachment, reference-media, video or exact Web research scope. Plain Web
  availability, enabled by default, is normalized off for this local media
  operation; an explicit search query/render request must never be discarded.
- Grant only the existing model read/artifact write permissions. The music child
  uses existing GPU/host RAM reservations, native process ownership and recovery.
  No external AI, automatic downloads or arbitrary code tools are introduced.
- Check the actual configured music profile before publishing. An unavailable
  engine yields a clear setup response and no music child or false success.
  The local wrapper still verifies immutable source/checkpoints at execution.
- Add the optional scope to turn receipts without changing fingerprints for old
  requests which did not contain it. A repeated Send retains the same parent and
  child; a retry cannot silently publish another expensive job.

## Verification

Use the fake native engine and temporary DB: Auto and selected Music in Chat and
Work, no text-provider call, default Web on without search, scope/mixed-input and
duration/lyrics validation, no prior-context/planner authority, one published
child on repeated receipt, unavailable setup, output audio and Task-wide Stop.
Frontend checks cover action selection, scope reset, lyrics/duration, inline
audio and normal conversation preservation. Inspect compiled desktop/phone UI.
Run required repository checks and review the updated #361 diff before merging.

Automatic lyric writing and image/audio-conditioned music are subsequent chains,
not behavior to fake by ignoring a reference or silently generating an
instrumental. The first conversation action accepts instrumental descriptions or
explicitly supplied lyrics; requests outside that scope must ask for the required
input. These later chains should reuse ordinary model/Vision Runs and the same
music child, not another executor or queue.
