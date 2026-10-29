# Whole-recording avatar quality follow-up

2026-10-29. This supplements the issued catalog v15; it does **not** change its
161 definitions, overwrite results or close QA-020 automatically. The original
AVATAR-005 failure concerns Echo at 384 px/eight steps. The owner also rejected
the separate Sonic 256×384 comparison as too soft. Both results remain valid
history. The replacement below has a different, explicitly frozen profile.

## Actual application qualification

An ordinary Avatars UI submission produced the complete neutral portrait/speech
recording through Task → Run → Events → Artifacts:

| Property | Observed value |
| --- | --- |
| Profile | `sonic_whole_768_v1`, seed 43, 25 diffusion steps |
| Output | Native 512×768, 1002 frames, 25 fps, 40.08 seconds |
| Audio | All 961920 canonical source samples at 24000 Hz |
| Generation | One global 501-base-frame sequence; 525 diffusion windows |
| Hardware | Two discovered RTX 3060 12-GB GPUs |
| Process boundary | Owned 18-GiB/zero-swap scope and four-hour deadline |
| End-to-end observation | 8838 seconds, including preparation, generation, interpolation, verification and completion polling |

The complete output and source hashes, every decoded video/audio frame and
sample count passed verification. The final artifact appears in ordinary
Library results, downloads with the matching hash and plays to its ending in
the compiled desktop UI. A 390-pixel browser viewport has no horizontal overflow
or JavaScript errors. This is browser automation, not a fresh physical-phone test.

Reviewed unenhanced samples at 0/10/20/30/40 seconds and a 20-sample face timeline
show clearer detail than the rejected 256×384 comparison, retained skin color
and no obvious progressive eye deformation in those samples. Mouth/expression
changes remain visible. These observations do not establish perfect identity,
frame-by-frame visual stability or precise lip synchronization. In particular,
512 pixels on the short side is **not native 720p/HD**. No upscaling, frozen-face
replacement, independently animated portrait clips or shortened speech supplied
this result.

The separate real agent journey produced and verified a complete two-second
512×768 result in 505.86 seconds through the same adapter and normal Library.
Its full browser playback passed and the manual QA agent was paused afterward.
This proves the short agent path; it is not a second full-duration agent run.

Private evidence is retained under
`data/acceptance/browser-qa-20261026/`:
`whole-avatar-full-real.json`, `whole-avatar-full-face-timeline.png`,
`whole-avatar-agent-real.json` and the source-bound execution records.
Portraits, speech, films, session cookies and workstation configuration are not
published in the repository.

## Owner quality review

The generated full film is available in the owner's Library. Review the actual
40.08-second result, preferably at its native size, with sound:

1. Check skin/eye detail near the start, middle and ending.
2. Watch for progressive deformation, red/magenta drift, flicker or abrupt resets.
3. Check mouth timing against speech and retention of the spoken ending.
4. Record whether sharpness is sufficient, along with any exact failing timestamps.

The owner's judgment of the new complete profile is pending. Keep QA-020 open
and the issued workbook/results unchanged until that response is reconciled.
Any later acceptance must name this replacement profile and preserve the old
failure rather than silently passing the original Echo definition.
