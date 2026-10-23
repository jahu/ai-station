# Music in the main conversation

Status: implemented with the Music adapter (#361). The operator approved the
weights; offline verification, queued 10/30-second GPU output/Library and native
Stop passed. The full backend/native gate passes 2318 tests. Release state and
the concrete acceptance profiles are recorded in the
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


## Original songs from one Send — active increment

Persistent original-lyric agents are deployed (#370). Real local drafting,
original Polish words, a normal-worker 10-second GPU WAV and restoration of the
operator's 46080-token model preset passed. Tiny CPU Whisper did not recognize
the sung words; lyrical intelligibility remains a separate listening check.
Evidence: `data/acceptance/agent-music-lyrics-20261023`.

Extend the existing conversation Music scope with a reviewed goal-lyric mode.
Natural current-turn vocal-song generation or **With lyrics → Write lyrics** may
request it; explicit instrumental/supplied-word choices retain their authority.
The existing orchestrator Run performs bounded creative inference before its
atomic music-child publication. Reuse shared pure description/song validation;
there is no transient persistent agent, second music engine or new Host API.
The selected conversation model/provider is disclosed and bound through ordinary
provider snapshots, permissions, model admission, leases and Stop. Only this
writing mode needs a text model; instrumental and supplied lyrics keep their
existing no-inference path. Honor qualified reasoning only when model work exists.

Preparation may replace only caption and authorized lyrics. Duration, GPU, seed,
permissions, current-turn scope and supplied words cannot be changed by output.
Require exact bounded JSON with at most one correction. Preserve prepared words
as an owned JSON artifact and provenance on the existing music child; show actual
song lyrics from the resulting audio metadata beside playback. Do not invent a
finished track before its checked WAV exists. Stop during writing publishes no
music child. Recovery/receipts cannot replay uncertain generation.

Default fixed scope serialization must preserve old request fingerprints. Exact
Web, attachment/Git/project/runtime mixes stay rejected; ordinary default Web is
normalized off without a search. Quotes, prior context and model plans do not
authorize a new song. Verify natural/selected entry and follow-up, provider grants,
legacy receipts, fixed no-inference behavior, immutable fields, invalid/truncated
output, Stop and actual inline words. Qualify compiled desktop/phone and a short
real selected-local-model case while preserving the operator's runtime preset.
