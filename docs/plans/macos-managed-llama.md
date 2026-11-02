# Managed native llama.cpp on macOS — NR-13/14

The consumer flow reuses runtime/model setup Tasks and Runs. Preparing engine
bytes, loading a model and producing a first answer have separate readiness
evidence. SDK preparation alone does not admit the Mac consumer launcher, Metal
inference or Linux image/media recipes.

## Native SDK preparation

Two fixed profiles use the existing hash-pinned b12032 ARM/Intel manifests.
After administrator review of the exact manifest/license, `/api/setup/runtimes`
queues an ordinary `runtime.prepare` Run using `native_llama_setup`, effective
model/network/workspace/filesystem permissions and a 1024 MiB worker reservation.
The shared download stage verifies the SDK archive in application storage; HTTP
handlers neither download nor assemble it.

Runner `/v1/setup/native-llama` provides typed catalog, prepare, inspect, cancel
and adoption operations. Matching Mac architecture/minimum OS, estimated RAM
and free storage are checked before dispatch. The owned environment controller
journals intent before launching its fixed offline job via DarwinProcessManager.
The actual installed Python uses isolation/no-bytecode mode, without repository
Python paths or systemd. This declares no hard/no-swap memory guarantee. Linux
environment policies retain their existing launch and scope behavior.

SDK bytes remain in the immutable native bundle namespace. Separate readiness
under `runtime/native-llama-environments` records the private preparation. Adoption
rechecks the whole bundle, stores an opaque identity mapping, then switches the
active observation. Shared catalog responses expose only that identity, profile
and manifest hash. Private Run IDs/paths stay in owner-scoped history/artifacts.

Durable Stop fences delayed dispatch. Lost acknowledgements inspect the same Run.
Unknown exit codes reconcile only after confirmed process exit and full SDK/
readiness verification. Missing ownership or changed bytes require inspection.
Cancellation, revoked authority and stale worker leases use ordinary setup
cleanup/recovery; resumed queued Runs keep ownership until native Stop is proven.
SDK adoption starts no model.

Normal tests use synthetic Mach-O and fake processes, plus the API/worker/download/
private-artifact path with a fake Runner. The explicit Mac probe uses the installed
wheel and normal Runner main over a private socket. It obtains only the pinned
small public SDK dependency, then checks real owned preparation, duplicate IDs,
permission denial, pre-dispatch and observed-live Stop, stopped-operation activation
denial, adoption privacy, restart and unchanged application Python.
Ordinary native checks still run no model. These results do not qualify Docker
Desktop transport or the complete installer.

## Model loading and first conversation

1. Extend the existing llama.cpp typed adapter with an explicit native profile
   and opaque SDK reference. Resolve its private bundle operation inside Runner;
   callers cannot select a binary, inference socket or argv.
2. Route to the existing NativeLlamaManager with immutable instance/Run identity,
   owned model hash/size/mtime and GGUF context/KV inspection. Linux container
   profiles retain their meaning.
3. Admit CPU and Apple Metal independently using actual RAM/device observations.
   Do not invent dedicated VRAM/CUDA indices or silently switch compute targets.
   Keep unqualified profiles unavailable.
4. Publish shared runtime resources without private setup/conversation IDs. Loads,
   readiness, completion proxy, Stop, watchdog and recovery use existing Runs and
   reservations. Shared native model logs continue to suppress model output.
5. Add hardware-matched owned GGUF choices to guided setup and prove a real first
   conversation through API/worker/Runner on both targets. Actual Docker Desktop
   socket/WAL transport, Finder UX, preserving update/removal, minimum OS, signing
   and Gatekeeper remain separate gates in [the consumer plan](macos-consumer-installation.md).

## Typed CPU model lifecycle

The existing `/v1/llama` load/inspect/Stop/chat/coding-completion routes dispatch
native CPU requests explicitly by SDK profile and opaque `environment_id`.
The native request requires verified owned weights, Q8 cache, an absolute startup
deadline and the inspected RAM budget. No binary, private preparation UUID,
model socket, argv or Metal device is caller selectable. Linux container requests
retain their prior serialized identities and are refused on Mac; native requests
are refused on Linux. There is no implicit platform or compute fallback.

Runner privately resolves the SDK reference and injects its existing singleton
ProcessManager into NativeLlamaManager. Installation-bound mode-0700 model socket
storage under the short native temporary namespace is separate from the mounted
Runner socket. Unknown/changing ownership returns an inspection-required error;
model logs remain suppressed. Closing Runner detaches native observers and retains
only shared native model processes, matching Linux model-container lifetime;
other owned jobs are still canceled. Explicit typed Stop persists its fence and
signals only the owned model. Replacement Runner reattaches the original process,
readiness socket and context without launching another model.

The explicit `macos-native-inference` operation additionally exercises this typed
path using the installed wheel/interpreter and existing fixed 0.6B CPU fixture:
SDK prepare/adopt, real load/reply, duplicate/mutated identity, graceful Runner
replacement with the same model PID and another reply, observed-live Stop and
pre-dispatch Stop. Ordinary SDK checks download no model. This is a component
qualification, not yet guided consumer setup, Metal or Docker Desktop acceptance.

## Control-plane model operations

The normal `llama_load` Run accepts an explicit native CPU profile, owned model
and opaque SDK environment reference. Before reserving/dispatching it, the worker
uses `/v1/models/verify` to recheck the source observation, exact GGUF cache geometry,
context/RAM budget and SDK identity. Native inspection never invokes Docker or
inspects arbitrary host paths; its response distinguishes native readiness from
an image and exposes no private preparation ID or host data path.

The existing durable RAM lock survives model readiness and lost acknowledgements.
A startup deadline is frozen on the first dispatch and reused after lease recovery.
Definition loading, explicit restart, automatic conversation loading and saved
handoff presets keep the same opaque environment reference. Native payloads omit
container-only projector coordinates. Stop and unknown ownership retain their
existing recovery semantics; a Mac RAM estimate is not hard/no-swap enforcement.
Account-scoped runtime-intent validation now checks the portable owned model
coordinate/hash as well as its preset. A private automatic load does not expose
its Run, conversation or SDK preparation to another account using the shared model.

This connects existing verified model definitions to the worker, not yet the
platform-matched first-run catalog. Guided selection/download and actual full
Docker Desktop installation remain the next integration step. Real native metadata
inspection is covered by the explicit installed-Runner CPU fixture; normal queue,
RAM, account/privacy and lost-ack tests use fake model execution.
