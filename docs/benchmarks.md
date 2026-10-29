# Recorded workstation results

These are observations from real AI Station work, recorded on 2026-10-25/26 and 29:
Intel Core i7-6900K, 32 GB RAM and two NVIDIA RTX 3060 cards with 12 GB VRAM each.
The devices are separately allocated; this is not an architecture requirement or
a claim that any model can use their VRAM as one unrestricted pool.

The [sanitized measurements](benchmarks/results-2026-10-26.json) retain settings,
timing boundaries, source-receipt hashes and the LLM's actual printed timing lines.
They contain no user prompts, credentials, private library export or new inference.
Raw development receipts remain under ignored `data/acceptance/` on the test station.

| Operation | Observed elapsed time | Scope |
| --- | --- | --- |
| LUSTIFY Generate | 100.05 s | 768×1024, Q4_0, 8 steps, CFG 1, seed 42, two-GPU profile |
| LUSTIFY Edit | 147.38 s | Same image profile, aligned reference, strength 4 |
| LUSTIFY Recompose | 149.23 s | One reference, beside layout, strength 2 |
| LUSTIFY Recompose | 189.50 s | Two ordered references, same output profile |
| Wan independent shots | 478.01 s | Two actual concurrent 2 s shots on separate GPUs; 1280×704 / 20 steps; exact 96-frame / 4 s composition |
| Wan continuous film | 11755.00 s | 18 sequential windows; 1280×704 / 20 steps/CFG 5/seed 43; exactly 1,440 frames / 60 s; one-frame APG continuation |
| EchoMimic recorded avatar | 2897.78 s | Fresh Chatterbox preparation plus 24 windows / 384 px / 8 steps / GPU 1 and composition; exactly 1,500 frames / 60 s |

Image timing is the recorded `started_at`→`finished_at` interval. Video/avatar
figures are the recorded complete workflow interval, including their preparation
and composition; later independent ASR, browser playback and human review are
excluded. They are not sampling-kernel timings. The avatar input is exactly the
first 60 seconds of a fresh 62.44-second narration, not the entire uncut source text.
No silence extension, loop or time stretching was used to manufacture duration.

## Whole-recording avatar follow-up, 2026-10-29

The [separate sanitized measurement](benchmarks/results-2026-10-29.json) records
the actual Sonic whole-recording application path: native 512×768, 25 diffusion
steps, seed 43, both GPUs and the complete 40.08-second source recording.
End-to-end observation took **8838.01 seconds (2 h 27 min 18 s)**, from accepted
UI request to observed terminal worker result, including preparation, generation,
CPU interpolation, mux, native checks and completion polling. Later browser and
visual review are excluded. This timing boundary differs from the historical
workflow timestamps above; neither is a diffusion-only kernel benchmark.

The final 1002 frames/25 fps and all 961920 source speech samples passed complete
decode/hash checks and ordinary Library playback. The observed 18-GiB/zero-swap
process scope is a host-memory boundary, not an 18-GB GPU requirement. The short
side is 512 pixels: this is not native HD. The owner's sharpness/lip-sync judgment
is pending; retain the original Echo quality failure. See the
[explicit acceptance supplement](qa/whole-avatar-follow-up.md).

## Local language model

One existing completion from the owned **RVN-Q4_K_M-multilingual.gguf** runtime:
26,895,998,464 parameters (27B class), both GPUs, Q8 KV cache and an observed
46,080-token context allocation. The prompt itself contained 467 tokens; the
server reported 345 generation tokens. It printed **16.90 generated tokens/s**
and **380.17 prompt tokens/s**, separately. Loading is outside both figures.
The original printed lines are in the sanitized JSON. No test request was sent
to the operator's model to obtain these numbers.

This is a single observed completion, not an average, saturation test, long-context
throughput measurement or ranking against another product. Prompt caching,
length, generation settings, model build, GPU load and quantization affect speed.
An allocated context ceiling is not evidence that a prompt of that length was
processed at the same rate. No speed is inferred from model marketing or web data.

## Quality and reproducibility

The recorded image cases, complete media decode, exact frame/audio accounting,
selected visual comparisons and actual compiled-player checks have their own
receipts. They do not establish universal generation quality. The long Wan film
still shows cool/cyan/purple drift; the avatar changes contrast/color and facial
detail. Exact lip-sync and identity fidelity are not claimed. Historical failed
candidates remain failed; they are not replaced by these newer figures.

See [Video](long-media.md), [parallel shots](parallel-video-shots.md),
[Avatars](avatars.md) and the [release acceptance audit](plans/platform-acceptance-audit.md)
for the precise qualified scope. To compare another machine, freeze model bytes,
runtime build, GPU allocation, dimensions/context, seed and timing boundary first.
