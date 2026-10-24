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
