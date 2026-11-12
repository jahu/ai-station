# Isolated Studio renderer

This increment provides the native rendering component for [Creative Studio](plans/creative-studio.md).
The local material director and typed API/worker export bridge are now connected;
see [materials](studio-materials.md). Soundtrack/shot generation, whole-material
coordination and the export UI are connected on develop. Complete-film quality
remains in qualification; guided fresh preparation is described below. Existing image/video workspaces
remain unchanged.

The native Runner accepts a finite composition: full-HD portrait, landscape or
square, 30 fps, up to ten minutes, bounded editorial scenes and owned Artifact
UUIDs. Scenes combine images, trimmed real footage, readable typography and
seekable GSAP motion. Static shots are supported deliberately. Scene wrappers
are untimed; each video owns its absolute source/timeline timing. Generated
markup must pass Hyperframes strict lint and actual Chromium layout checks.
Model text cannot supply HTML, CSS, JavaScript, commands, packages or URLs.

Hyperframes 0.9.26, GSAP 3.15.0 and Fontsource 5.3.0 are lockfile-pinned. Local
fonts include extended Latin; the image preserves their licenses. The fixed
image contains Node 22, Chromium, FFmpeg and the trusted compiler. Rendering
installs nothing, has no network, disables telemetry and receives no GPU.
Only the private per-Run staging folder is mounted; no control-plane Docker
socket or host-wide data mount is introduced.

The native supervisor uses a 256-MiB, zero-swap user memory scope. The owned
container has 4096 MiB, zero swap, four CPUs and 512 PIDs, runs as the native
user with a read-only root, dropped capabilities and no ports/devices. Scheduler
integration must reserve their combined 4352 MiB. Temporary extraction files
belong to the Run staging disk, not a small RAM-backed `/tmp`.

`GET /v1/motion/capabilities` is read-only. Readiness is unavailable by default;
normal tests do not adopt development images. An operator-configured
`AI_STATION_MOTION_IMAGE` or an application-owned prepared-image receipt must
match the immutable image ID, fixed entrypoint and current recipe hash. Guided preparation uses the ordinary private setup Run described below.

`POST /v1/runs/motion` freezes the request, image, local Unix Docker daemon,
implementation observation and absolute deadline. Native process ownership
uses the existing journal, process groups and deadline manager. Retrying the
same receipt observes the original process; changed requests or missing launch
acknowledgements require inspection rather than redispatch. Only the exact
verified container may be removed. An unknown create acknowledgement retains
cleanup uncertainty. `POST /v1/motion/{run_id}/cancel` persists a cancellation
fence even before dispatch; ordinary process Stop also removes that owned
container. Dead-process inspection confirms cleanup before resource release.

The compiler validates colors/contrast, scene/text bounds, canonical media
hashes and actual source coverage. A requested soundtrack must already be a
complete 48-kHz stereo PCM mix; this component never truncates narration or
loops short footage. Export checks H.264, exact size, frame count, 30 fps,
duration, expected audio and complete decoding, then publishes an immutable
MP4 and bounded JSON provenance report.

Private component qualification on 2026-11-11 covered portrait and landscape
with actual image/video sources and calibration audio, Stop, lost-response
observation and supervisor termination followed by container recovery. These
are component tests, not approval of a professional complete reel or a Windows
installer. Product acceptance additionally needs generated visuals, direction,
narration/music mixing, editing, assistant routing and full playback review.

## Activating an existing local engine

Studio's export panel offers **Set up film export** when native rendering is
unavailable. An administrator reviews the component licenses and activates a
compatible image already present on the station. This queues an ordinary private
`motion_setup` Run through `/api/setup/runtimes` and the fixed native
`/v1/setup/motion` profile. Members can see shared readiness, not another
operator's setup history. No new model or renderer image is downloaded here.

The Runner checks the packaged recipe, Linux/amd64 image, fixed entrypoint/user,
and local Docker daemon. It journals the immutable request before publishing an
atomic native selection. A lost acknowledgement is reobserved without rewriting
selection; early Stop fences activation and late Stop keeps the shared engine.
Changed image/recipe/daemon observations cannot publish readiness. Worker recovery
and administrator revocation reuse the existing setup lifecycle. Readiness notices
selection changes immediately, including a previously cached missing-engine result.

Qualification: 15 native activation tests and 8 worker/account tests, plus actual
API enqueue → worker → private Unix socket → native activation of the already
qualified `ai-station-motion:local-v4` image. Actual readiness, receipt replay and
unchanged selection on replay were checked; no new render or inference was
executed during that activation. Missing engines now use the guided first-use
preparation path described below.
This activation is not generated-film visual/audio quality acceptance.

Readiness keeps the last successful observation while rechecking the same
selection in the background. Periodic refresh must not turn a verified engine
unavailable at the end of a long generation. Initial or changed selections still
require a completed check; failed revalidation clears the cached result. Native
dispatch independently rechecks the actual image, daemon and frozen observation
before launch. The workspace polls only transient `checking` state, so initial
verification enables export without a manual page refresh.


## Completed presenter footage

The export panel can select a completed MP4 presenter from Library. A finite
placement reserves space beside or below the story; the whole story is resized
rather than obscured. One muted video spans the complete timeline, without
restarting at scene boundaries. The final film retains its selected soundtrack.
Use footage speaking the same narration, at least as long as the film. Native
codec inspection refuses insufficient coverage instead of looping or freezing.

The optional field is absent from legacy serialization. Sources retain the
same hash/path/owner checks, combined size bound, lineage and dispatch/publication
revalidation. A new renderer recipe/image is required before activation; merely
upgrading the API does not qualify an older compiler for presenter exports.

Actual CPU qualification on 2026-11-12 rendered six-second, two-scene films in
portrait, landscape and square using approved existing showcase footage and a
calibration soundtrack. The presenter stayed continuous, Chromium verified its
reserved canvas region and audio muting, all outputs decoded completely, and
native ownership/cleanup and zero-swap limits were verified. A separate disposable
account/API/worker/native test published the presenter film with all four source
artifacts in its lineage. These checks generated no new model output and do not
qualify automatic narration-aligned avatar production or a publication-ready reel.


## Timed presenter sequences

The typed composition API can also bind a sequence of at most 32 completed
presenter clips. Their integer durations must cover the complete film exactly;
each clip has its own bounded source trim. Editorial starts retain full numeric
precision and stay on the film's 30-fps timeline, independently of 25-fps source
rounding. The renderer validates the real media coverage before rendering.
Hyperframes owns clip visibility/seeking; GSAP animates only editorial content.
Clips share the reserved presenter region and keep their audio muted.

The API requires the native `max_presenter_clips` capability before queueing a
sequence. Every source remains owner/hash bound and checked again before
publication. Combined source count can reach 93 (60 story visuals, 32 presenter
clips and one mix), still within two GiB. Optional sequence fields are omitted
from old single-clip request serialization.

A real six-second CPU render qualified a join at editorial frame 61 with a
2.04-second offset into the next 25-fps source, complete decoding, strict lint,
reserved layout and single-audio verification. Existing approved footage was
reused; no avatar was synthesized for this component check. Automatic presenter
production and its editor/assistant controls remain separate delivery work.


## Preparing a missing engine

In Studio, open the material's **Prepare film export** panel. A station
administrator reviews the component licenses and download notice, then clicks
**Prepare film export**. CPU preparation runs in the ordinary setup history,
reports toolkit/video/audio/assembly/verification stages and offers Stop. It
downloads runtime components, without AI models or changes to other host apps.
A compatible engine already installed on the station uses activation directly.

Fixed official base digests, packaged npm lockfiles and trusted source archives
feed two bounded owned containers. The native helper verifies the final immutable
image and stage cleanup before publishing readiness. Worker/Runner recovery
observes the same operation; uncertain ownership or commit cannot trigger replay.
See the [contract and exact qualification scope](plans/studio-renderer-setup.md).
This prepares rendering infrastructure; professional long-film quality remains
a separate acceptance gate.
