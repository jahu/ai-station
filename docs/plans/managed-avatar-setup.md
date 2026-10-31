# Guided local avatar setup

NR-14 continues after guided video PR #542. That PR is reviewed, merged into
`develop` and deployed, preserving 38 tables, configured media/models, credentials,
memory/index and the same private-access node. Its final compiled desktop/phone
and real setup/generation/composition/editor/recovery/Stop/privacy checks pass.
The full release goal remains active; this next profile is not available yet.

## Inspected starting point

Preserve the existing, owner-accepted Sonic whole-recording workflow described in
[whole-recording avatars](whole-recording-avatars.md). It uses clean source
`c1bd2d133ecc72f1a5abd990f1de101efcc3cfdb` and 14 active model/config companions,
8,315,655,620 bytes total. A new read-only audit rehashed all 14 against their
retained pinned publisher/download receipts. No model or original environment was
changed. Sources are `LeonJoe13/Sonic`,
`stabilityai/stable-video-diffusion-img2vid-xt` and `openai/whisper-tiny`.

The working Python is 3.10.21. It imports six local dependency overrides plus a
shared base environment; 195 visible distribution entries are not an installation
recipe. The headless inference imports select a 75-package closure whose 120
dependency requirements pass, including the local Transformers 4.43.2,
Diffusers 0.29.0 and Accelerate 0.33.0 overrides. RECORD verification now matches
23,673 payload files across all 75 selected distributions. The base exposes both
GUI and headless OpenCV 4.11 metadata; actual shared `cv2` bytes match the headless
distribution. Freeze that coherent headless provider, rather than installing
both. Do not install the unrelated base training/UI stack or copy its `.pth` file
into a prepared environment. Independent offline assembly and actual inference
remain required.

The public-package audit resolved 74 compatible exact wheels (3,292,268,437
bytes). ANTLR 4.9.3, required by the unchanged OmegaConf profile, is published
only as a 117,034-byte source archive. Its exact PyPI hash is verified and its
small reviewed setup declares no compiled extensions. Preserve the known runtime
versions: build this one pinned pure-Python wheel offline with pinned build tools
inside the new owned environment, then verify its deterministic output before
installing. Do not enable arbitrary source packages, invoke a network resolver
during preparation or substitute an unreviewed wheel mirror. This explicit source
exception must appear in the fixed recipe and get its own normal boundary checks.
A separate clean Python 3.10.21 build environment with setuptools 79.0.1 and wheel
0.45.1 reproduced this wheel twice with network denied and a fixed epoch. Both
144,590-byte outputs have SHA-256
`e403b2aa433c161c3ed3dc04e9176db63aef53c6dc0af5bb9617748e9c0dd1ba`.
Neither build changed the original environments. This proves the source-build
input strategy; no complete avatar preparation is qualified by this audit.

Sonic's checked source carries CC BY-NC-SA 4.0. Its weights, SVD, Whisper, RIFE,
face detector, Python and dependencies require separately inspected component
notices; never label the entire bundle permissively licensed. Review pinned
publisher files before making a license-acceptance card available.

## Delivery

1. Reuse verified downloads, the ordinary account-owned setup Task/Run and the
   shared native offline preparation lifecycle. Freeze a built-in Sonic recipe,
   independent Python 3.10, SDK, coherent binary wheels and every active model
   companion. Host Runner/control plane remain on Python 3.12. Generalize only
   the fixed standalone extraction primitive needed for the runtime's Python;
   preserve existing speech/music/video defaults and identities.
2. Preserve the original Sonic/legacy Echo installations. Any explicit Sonic
   configuration, including an incomplete configuration, keeps priority. Managed
   selection is a fallback when none is explicit. Do not make Echo appear ready
   because Sonic is installed. Reuse whole-recording requests, source checks,
   canonical audio, exact timing and saved creative history.
3. Reuse the immutable store with closed-world checked model references. The
   existing Sonic `direct_file` contract forbids links: managed links therefore
   need an explicit exact-recipe validation path; never globally weaken external
   symlink checks or silently duplicate eight GiB of weights. Freeze an opaque
   shared environment identity without disclosing another account's setup Run.
4. Prepare offline in an owned four-GiB/zero-swap scope; import/codec probes use
   CPU only. Inference retains the existing 18-GiB zero-swap scope, real GPU
   admission, process ownership and absolute whole-recording deadline. Retain
   one/two-GPU operation and the full supported recording length. Show measured
   landscape/portrait bounds and explain 512×768 is not native HD.
5. Add the existing setup-card design to Models and an entry from missing avatar
   readiness. Show hardware, storage, reviewed sources/licenses, preparation
   progress, Stop/Resume and Open Avatars. One saved portrait/audio workflow
   handles the whole recording. Do not add another mode or execution engine.

## Qualification gates

Normal fake/tiny tests cover archive/model/link boundaries, offline installation,
explicit/partial configuration precedence, immutable identities, private setup
histories, Stop/adoption, stale claims/revocation, whole-recording publication and
unchanged Echo serialization. Expensive qualification is explicitly opted in.

A fresh private account must prepare the real independent environment with
Stop/Resume, create an ordinary portrait/audio avatar through API/separate worker
and compiled UI, decode the complete expected frame/audio timeline and retain
Library/history on desktop and phone. Verify same-process Runner recovery,
owned Stop/resource release and second-account denial. Reuse earlier source and
quality evidence only for what it actually proves: a new two-second environment
check is not another 40-second HD/lip-sync acceptance result.

Keep activation unavailable until those checks pass. Review the full diff and
local gates before a PR to `develop`; deploy only while idle with backup and
preservation checks. Public/private evidence is kept separate. Remaining effects,
expressive-voice setup, broader catalogs, consumer Linux/Windows/macOS journeys,
NR-06/07 quality, naming and the final owner QA workbook remain in the full goal.
