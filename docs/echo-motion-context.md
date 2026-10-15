# EchoMimic motion checkpoints

The installed EchoMimic pipeline encodes the masked reference video in
`prepare_mask_latents` and decodes the final denoised tensor in `decode_latents`.
The current multi-window adapter carries seventeen decoded MP4 frames between
windows. Repeated video decoding and VAE encoding can progressively damage detail.

Full-recording jobs will preserve the last five temporal groups of the final
Wan 2.1 latent tensor as an app-owned safetensors checkpoint. The next window
keeps its seventeen-frame conditioning mask but substitutes that exact latent
prefix after the existing masked-video preparation. Masked preparation uses the
checkpoint's direct VAE-decoded floating-point frames, retaining the causal boundary
context without an MP4 roundtrip; its first five encoded groups are then replaced
with the unchanged checkpoint. During each configured flow-scheduler step, the same
prefix is restored at the next noise level using the window's original noise;
the final zero-noise prefix equals the checkpoint. This prevents the discarded
overlap from being regenerated with different lighting. Its original portrait stays
the CLIP identity reference. Installed EchoMimic code, models and input files are
not modified; the adapter uses a per-process subclass.

Checkpoints are bounded F32 tensors, shape `[1,16,5,size/8,size/8]`, with exactly
one motion tensor and a model/config observation fingerprint. The native request
checks canonical owned paths, extension, size, hash, shape and current profile
before launching; the child checks hash/finiteness again. A checkpoint requires a
preceding owned video and a full-job audio window. The worker adopts it as a hidden
general document Artifact linked to its video/Run. A changed or trashed checkpoint
fails closed; legacy clips without checkpoints retain the existing pixel path.

Cancellation, leases, GPU/RAM admission, durable Stop/Resume and final composition
use the existing media graph. Normal tests use fake processes/tensors. Real
acceptance must use a neutral close portrait and verify multiple native windows,
complete final audio/video timing and playable output. A short successful test
cannot qualify every longer duration or visual quality profile.
