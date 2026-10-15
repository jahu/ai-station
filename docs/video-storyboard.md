# Deliberate multi-scene video

The existing independent-shot mode repeats one prompt across its render
segments. Extend it with an optional explicit scene list, so a user can describe
the opening, subsequent action and ending while retaining one final MP4.

Keep the current single-prompt path unchanged. An explicit storyboard contains
one to twenty ordered scenes, each with a prompt and integer duration. Total
duration must match the existing bounded 1–60-second request. Storyboards use
independent shots; continuous motion keeps its existing sequential contract.
Each generation prompt combines the shared scene/style instruction with its
scene instruction, within the existing 2000-character executor bound.

Split at scene boundaries before the normal bounded model-window split. Retain
global deterministic segment seeds, ordered final composition and lineage,
resource admission, durable Stop/resume, revision/receipt and source policies.
Store scene identity on selected stage parameters and request metadata, without
changing native inputs or schema. Legacy receipts without a scene field must
still replay without new Runs.

In Video, reveal scene editing only when explicitly planning a shot sequence.
Allow adding, removing and reordering scenes, show the calculated total, validate
inline and preserve the saved request on reopen. Show per-scene progress alongside
existing render progress. Do not imply a shared character or seamless motion
between independent scenes. Inputs remain disabled during owned work.

Verify validation/legacy replay, exact frame and prompt partition, deterministic
seeds, dependencies, resume and final order with fake GPU work and real CPU
composition. Run the full required checks and inspect desktop/mobile interaction.
No new real generation is needed to prove this queue/composition extension;
record any later real visual qualification separately.

## Verification before deployment

1576 backend/Runner tests passed (five explicit opt-in skips), plus Ruff. The
29 focused media tests include real CPU composition/decode and fake GPU dispatch.
Final UI source passed 488 tests, format/lint/types/build, Docker and both Compose
configurations. The actual compiled candidate was inspected at 1440, 390 and
320 pixels: editing/reordering/focus, calculated duration, saved restoration,
active-control disabling and per-scene progress passed without page/API errors
or internal/page overflow. API fixtures were explicitly synthetic; the candidate
had no native socket and its private database retained zero Runs. No actual
storyboard GPU inference is claimed. Evidence: `data/acceptance/video-storyboard-20261015`.
