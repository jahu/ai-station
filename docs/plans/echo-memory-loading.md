# Preserve EchoMimic quality while reducing model-loading RAM

The whole-avatar agent path is implemented, but real normal-worker acceptance
remains open. The older standalone 30-second sample recorded roughly 24 GiB
process RSS during loading. The workstation currently has about 13 GiB available;
other user applications must remain untouched. Repeating that loader is not a
useful qualification.

Read-only inspection found a concrete cause: upstream first loads the original
Wan transformer, falls back to allocating missing audio parameters, then loads a
complete BF16 flash checkpoint over that model. The historical job log confirms
220 missing base keys and zero missing flash keys. Upstream also eagerly reads
large PyTorch checkpoints and retains the flash state dictionary.

Prototype a process-local adapter that creates transformer/VAE/CLIP parameters on
meta, strictly assigns the existing complete checkpoints, and memory-maps the
fixed existing PyTorch files. Preserve dtype, full tensor keys/shapes, tokenizer,
text encoding, scheduler, sampling, inputs and motion continuation. Never modify
upstream installation/model bytes, create converted weight copies, download
models, or expose loader/path/command selection through HTTP. Reject incomplete
checkpoints rather than retaining random/meta parameters.

Start with bounded CPU loading and exact tensor/shape/dtype comparisons against
the configured checkpoint. Then qualify actual short avatar output within a
kernel RAM/zero-swap bound and a fixed deadline, using existing approved synthetic
portrait/speech and the existing owned-process machinery. Preserve the actual
operator model preset and other applications. Record technical, visual/lip-sync
and memory results separately. No reduced reservation or available product option
is justified until this evidence passes. Existing native dispatch stays unchanged
while the prototype is unqualified; an explicit private engineering flag is not a
new public API. Qualification evidence belongs in
`data/acceptance/echo-memory-loading-20261024`.

## Prototype evidence

The initial bounded CPU probe rejected CLIP's constructor because upstream moves
its new meta tensors to CPU before weights exist. A narrowly scoped constructor
factory now retains meta until strict assignment and always restores itself on
failure. The failed attempt remains in the evidence directory.

The corrected CPU probe loaded all four components and compared every tensor's
keys, shape and values against the original checkpoints (including the original
BF16 conversion for VAE/CLIP). Transformer, VAE, T5 and CLIP checks passed; model
sizes/timestamps stayed exact and CUDA was never initialized. The service was
configured with an 8-GiB/zero-swap limit. Its process RSS included mapped file
pages (about 15 GiB peak); this is not a claim that total machine physical use was
8 GiB or that GPU inference fits. GPU inference and output quality remain open.

Native dispatch does not select this prototype. A private engineering entry flag
requires both explicit real-test opt-in and the actual canonical Run's 11-GiB,
zero-swap kernel scope before importing inference. Default arguments are
unchanged. Focused loader, motion and scope checks passed 45 cases. The next test
uses the existing owned ProcessManager and a bounded actual native window; it is
an engineering qualification, not yet ordinary agent end-to-end acceptance.

## Bounded native rendering result

The corrected private native window at source `c093d7e` produced all 81 frames
at 384×384/eight steps with an audio track in about109 seconds. The owned scope
observed the actual11-GiB kernel limit, zero swap and no OOM; process ownership,
expiry and cleanup remained with ProcessManager. All source bytes, installed
model observations and the original operator GPU/Q8/46080 preset were preserved.
First/middle/final frames retain the clothed synthetic portrait and coherent face,
with visible mouth movement. This is a short technical/coherent-face result,
not a claim of exact lip-sync, Standard output parity or every size/duration.
The initial directory-validation rejection is retained separately and restored
the operator preset before correction.

## Product integration candidate

Expose an optional `bounded_11g` profile only with
`AI_STATION_ECHO_BOUNDED_PROFILE=true` and working private user memory scopes.
Keep it disabled by default until local qualification. The same existing full
BF16 weights are used; this profile is constrained to384×384 and at least8 steps.
No precision/path/command/memory-limit field is accepted from HTTP. The native
entry checks its actual canonical Run scope before importing inference.

Short/full/avatar-agent requests freeze the profile, source IDs, quality and
original expiry. Default serialization omits the field to preserve saved receipts.
Every bounded segment reserves11264 MiB plus existing headroom; Standard retains
its native argv and existing records. New Standard jobs reserve24 GiB based on
the observed loader peak; the previous16-GiB full-job reservation and absent
short-job reservation could start despite insufficient RAM. Speech handoffs, resume, composition metadata and native
requests retain the selection. Unavailable profiles fail without a fallback.

Fresh Avatars/Chat can recommend the available bounded profile when measured free
RAM is insufficient for Standard. Manual/saved settings stay authoritative.
Agents/conversation review offers a separate explicit profile/time suggestion;
it preserves source IDs, enabled state, existing larger limits and schedules.
No render writes, auto-activation or Run is introduced by the editor.

Before merge: full normal Python/Runner and UI gates, exact image/Compose checks,
compiled real API/SQLite1440/390 review, actual ordinary agent→native windows→
verified full output, visual review and controller/native backed-up rollout.
Product evidence: `data/acceptance/echo-memory-profile-20261024`. The complete
platform goal remains open.


## Ordinary-agent proof and admission review

At `64cfd15`, the real ordinary agent/worker/native pipeline produced two scoped
Echo windows, preserved latent continuation and composed125 frames/five seconds
with the actual source audio at384×384/eight steps. Full video/audio decode,
finite non-silent audio, original source hashes, both scopes, cleanup and exact
operator preset restoration passed. First/middle/final and join frames retain a
coherent face. Exact word-level lip-sync and all durations/profiles remain open.

Review additionally reproduced unsafe Standard admission for both short and
whole-recording jobs:20 GiB free could start a loader historically measured near
24 GiB RSS. The two failing-before regressions remain in
`standard-reservation-before.log`. New Standard jobs now reserve24576 MiB plus
existing headroom; original argv, request identities and existing Run records
remain. Both regressions pass after correction. A new full Python gate is required
for this material admission change. The bounded renderer/entry/weight loader and
its11264-MiB reservation are unchanged; compare exact functions before reusing
the recorded real bounded output without another inference run.
