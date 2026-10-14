# Lossless motion context between Wan windows

Pixel-based continuation decodes a completed MP4 and encodes its final frames
through the VAE again. Repeating that process can accumulate reconstruction and
codec loss. The native adapter now saves the final five temporal latent groups
as a small, owned Float32 safetensors checkpoint and reuses that state directly
for the next window. The seventeen-frame overlap and exact output timeline remain
unchanged. No model, installed ComfyUI source or user input is modified.

The checkpoint is bounded to 4 MiB, one named tensor and an exact profile-specific
shape. Its header and weight size/mtime fingerprint are checked before launch;
hash and finite-value checks are repeated inside the owned inference process.
It never uses pickle or an unrestricted model loader. A hidden general document
Artifact records its hash, source video and producer Run. A trashed checkpoint
must be restored before continuation. Old videos without checkpoints retain
pixel-based compatibility.

Normal tests cover header bounds, dtype/shape/profile mismatches, rejected native
requests before dispatch and hidden Artifact lineage. The configured video Python
successfully imports the app-owned helper. A real two-window 1280×704, five-second GPU job passed with exact 120-frame
composition, owned checkpoint Artifacts and confirmed latent input on the second
window. Evidence is in `data/acceptance/wan-motion-20261015/real-result.json`.
This proves the checkpoint path; longer-chain visual quality remains separate. The previously verified 60-second pixel-continuation
film was a four-step draft; full decode/timing verification is separate from
visual quality and long-chain stability.
