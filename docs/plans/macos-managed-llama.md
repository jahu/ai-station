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
permission denial, Stop, adoption privacy, restart and unchanged application Python.
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
