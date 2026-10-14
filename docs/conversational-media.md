# Long media in Chat and Work

The main conversation uses the same durable media jobs as Video and Avatars.
Choose Video and a duration, or describe a whole number of seconds/minutes in
the current video instruction. Supported exact durations are 1–60 seconds.
Without an explicit duration, the existing short-preview behavior remains.
A duration outside that range produces a clarification before GPU work is queued.
The optional typed `media` scope records duration and continuous/shot mode;
it cannot be combined with coding, project creation, search or other action scopes.

An avatar instruction with one portrait and one WAV now animates the complete
recording. Spoken text first becomes a canonical TTS artifact, then the animation
planner publishes its windows. Old dedicated short-preview APIs remain available.
Direct video/avatar routing does not need a conversational LLM or cloud provider.

The message shows one aggregate job card, accurate segment progress and the final
player/download. Native intermediate videos stay in the Run inspector rather than
filling the transcript or default Library. Planner success is not job success.
The conversation's Stop and the job card's Stop both cancel the entire media Task;
Resume creates a new plan revision while retaining successful prior work. The job
card keeps its own bounded polling, including dependent cleanup after a failure.

Optional media defaults are excluded from first-turn receipt fingerprints, so
already accepted requests replay across this additive schema change. Media scope
is also rejected in an existing coding continuation. Chat/Work permission policy
continues to apply: local media tools do not grant coding or external AI access.

Host dispatch rejection is reconciled against the owned process journal. A known
rejection with no owned process releases resources and permits a fresh resume;
a lost reply for an existing same-executor process is inspected and adopted without
relaunching it. Unknown ownership retains the inspection/recovery boundary.

Tests cover exact conversational output, Chat/Work parity, complete recorded and
synthesized speech, final-only transcript projection, task-wide Stop and rejection/
duplicate-dispatch reconciliation using fake GPU generation and real CPU composition.
