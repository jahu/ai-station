# Isolated Studio renderer

This increment provides the native rendering component for [Creative Studio](plans/creative-studio.md).
The local material director and typed API/worker export bridge are now connected;
see [materials](studio-materials.md). Soundtrack/shot generation and the end-to-end
export UI remain in development. Existing image/video workspaces remain unchanged.

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
match the immutable image ID, fixed entrypoint and current recipe hash. Guided
preparation and control-plane registration follow in the next increment.

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
