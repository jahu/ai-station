# Real local creation showcase

User brief: 2026-11-07. Deliver high-quality, real outputs in README and primarily
the existing website, with actual prompt/result screenshots and a convincing
single-prompt orchestration example. Preserve the current static Cloudflare site,
branding and modular application. This is not a new inference integration.

## Evidence and account boundary

Use a dedicated non-administrator `demo` account. Its Library, conversations and
Runs must initially be empty. Create every showcase input, result, conversation
and agent draft under that owner. No existing operator media, prompts, account
sessions or Library exports may appear in public files or screenshots. Demo
credentials and browser state remain in ignored private acceptance storage.
All inference uses normal authenticated APIs, durable Runs and the existing
worker/Runner; do not execute a parallel media pipeline outside the application.

## Creative deliverables

1. Qwen-generated fictional adult presenter portrait and a cinematic coastal
   scene, with carefully reviewed photorealism, anatomy, eyes and material detail.
2. Real Edit/Recompose comparison preserving identity while changing scene,
   clothing and expression; inspect whole images, not only thumbnails.
3. Local speech clips with native playback controls, spoken-language labels,
   source/model attribution and clear synthetic-media identification. Research
   recognizable male and female reference voices using primary licensed sources.
   Recording reuse rights must not be confused with subject consent or additional
   model terms. Respect the installed engine's actual license and watermarks.
4. A short speaking avatar using the best qualified available profile, with
   motion, eyes, lip synchronization, audio and ending checked. Disclose native
   resolution and any upscale; do not call upscaled output native HD.
5. A short image-to-video scene with generated synchronized sound, complete
   decoding and browser playback checked.
6. A genuine conversation that chains a reference image and speech input through
   studio restaging and then avatar output, retaining the supplied recording.
   Show actual tool/result history,
   not a seeded fictitious success. Explain that the assistant selects tools,
   observes results and passes artifacts forward; technical LlamaIndex details
   belong in an optional implementation note.
7. Desktop/mobile screenshots from the same account, including prompts and
   inline results. Add an inspectable link from each curated result to its UI
   screenshot and recipe, with only explicitly approved public metadata.

Public adult-model messaging may state the existing compatible NSFW/local-model
capability and absence of an extra platform filter. Public example imagery stays
non-explicit; do not generate pornography or nudity for later blurring. No claim
that every model has identical behavior, unlimited capabilities or waived rights.

## Website and README presentation

Preserve the existing dark/green visual identity and dependency-free static build.
Add an editorial creation gallery, accessible before/after image controls,
click-to-play audio/video, and a concrete one-prompt-to-results story. Native
controls and useful content must work without JavaScript. Use responsive images,
lazy loading, video posters and `preload="none"`; never autoplay voice. Keep
sources local and avoid analytics, third-party players or private API URLs.

Show the actual workstation: i7-6900K, 32 GB RAM, two RTX 3060 12 GB devices.
Faster hardware can reduce generation time; more VRAM can enable larger models
or settings. Do not promise improved visual quality merely from a faster GPU
using identical model/settings. Keep per-result model, resolution, duration,
steps and measured elapsed time where verified.

README gets a concise visual entry point and links to the richer website,
alongside clear invitations to try the app, report problems and contribute.
No fabricated endorsements, partner branding, product users or quality metrics.

## Publication and acceptance

Maintain a private capture ledger mapping each asset to its demo-owned Run,
input artifacts, recipe, hashes, license and QA result. Public provenance omits
credentials, local paths and private source information. Curate high-quality
results; unsuccessful experiments remain private and are not advertised.

The owner previously required review of new imagery before publication. Prepare
the complete private preview and reviewable media first; obtain that approval
before pushing media to a public branch or deploying it. Normal source PRs target
`develop`; only the human owner may approve/merge the protected release branch.
Do not bypass this by publishing a feature-branch preview containing new images.

Validate the actual built website at desktop/mobile sizes, keyboard controls,
before/after interactions, media play/pause/end, reduced-motion behavior, absence
of external requests, and browser errors. Verify all public files against the
approved asset list and ownership/provenance ledger. Backend/runtime changes are
outside scope unless a genuine blocker is diagnosed and independently reviewed.

## Preparation evidence (2026-11-07; not yet published)

- Dedicated non-admin demo account created and initially empty; authenticated
  generation and result capture use only that account. Credentials and source
  reference files stay outside tracked files in private acceptance storage.
- Two Qwen photographs succeeded: a fictional presenter (896 × 1152, 35 steps)
  and a coastal car scene (1344 × 768, 35 steps). Both were visually inspected.
- Qwen edit produced visibly granular skin and was rejected for the gallery.
  The existing LUSTIFY v10 Turbo adapter produced a cleaner emerald-blazer edit
  (8 steps, CFG 1); identity, skin texture and the requested brooch were inspected.
- Wan 2.2 created a 3.375-second 1280 × 704 film. MMAudio generated matched harbor
  ambience; the application's own sound-preview Run produced the combined MP4.
  Full FFmpeg decoding and real browser start/pause/resume/end passed.
- Original English Fish speech and five initial Polish Chatterbox reference impressions
  completed as ordinary Runs. Morgan Freeman, Donald Trump, Elon Musk, Oprah
  Winfrey and Michelle Obama sources are credited per sample. Signal checks found
  no clipped PCM samples. Playback MP3s use transparent linear gain to reduce
  large level differences, with a -1.5 dBFS PCM peak cap. Original application
  WAVs stay unchanged; no cuts, denoising, EQ, voice conversion or watermark-removal
  processing is performed. Watermark retention has not been separately measured.
  Offline ASR recovered the intended sentence with minor
  recognition errors. These checks do not prove timbral likeness or subjective
  listening quality; the owner can listen in the private preview before approval.
- Four genuine Library result/recipe screenshots were captured with demo visible.
  No fabricated result, operator prompt or production Library export is used.
- Browser checks passed at widths 1440, 768 and 390, with no horizontal overflow,
  failed responses, JavaScript errors or external requests. Seven players reached
  their actual end events. Keyboard activation opens prompt details. Static site
  build passed. Website-only checks do not claim another full application test run.
- The live single-prompt 27B conversation produced its studio image, observed that
  actual artifact and passed it with the supplied recording to whole-recording
  Sonic. Both tool outputs completed: the actual 12.76-second native 512×640
  avatar is included, with English captions and a poster from an actual frame.
  Source hashes verify the exact image/audio lineage. A legacy final-reply
  classification defect was fixed independently in PR #691; historical text
  is preserved, and no corrected final reply is fabricated.
- A first 9B attempt could not plan requested outcomes and executed no tool. It
  remains private evidence; selecting 27B is not a claimed generic planner fix.
- A genuine non-admin upload-visibility defect was independently reproduced,
  fixed and deployed through reviewed PR #690. A SQL NULL/NOT IN interaction hid
  uploaded references after an unrelated backup Run. Correlated EXISTS preserves
  backup authorization and normal member access; focused regressions passed.

Completed avatar, verified source lineage, clean actual conversation captures and
per-result provenance are now prepared. Remaining gates: owner visual/listening
and publication approval; reviewed source PR to develop; protected release review
and production website verification. No new
asset has been pushed publicly. The protected release branch remains human-owned.


### Owner feedback: English voices and portrait playback (2026-11-07)

All five named Chatterbox samples were regenerated as real English demo-owned
Runs after the reviewed language adapter change (#693). Offline ASR recovered
the complete shared sentence for each. Source signal checks found no clipping;
MP3 export uses transparent linear gain only. This proves wording and playback,
not subjective voice likeness. Original Fish English speech is unchanged.

Voice cards pair licensed thumbnails with visible synthetic-imitation labels,
keyboard play/pause, real progress/duration, exclusive playback and error fallback.
Credits remain in native details; without JavaScript the native audio controls
work. Portraits retain their individual public-domain/CC licenses, including
CC BY-SA for the Elon Musk adaptation; the site license does not replace them.

Clean request/result screenshots were captured from the actual demo conversation
without editing the DOM or messages. During an earlier parallel capture while
speech was running, two SQLite-related HTTP500 responses occurred; that attempt
was rejected. The subsequent capture completed without HTTP or JS errors.
Residual database contention under simultaneous generation/navigation remains
recorded for follow-up; no blanket all-load reliability claim is made.

The owner subsequently reviewed and accepted the complete existing private
gallery, including portraits, English audio, avatar and actual UI captures.


Final private browser checks passed at 1440, 768 and 390 pixels with no overflow,
HTTP failures, JavaScript errors or external requests. All eight media players
completed actual playback with pause/resume/end. Dedicated checks passed for
keyboard playback, progress, exclusive playback, no autoplay, no-JavaScript
native controls and a visible native fallback when an audio source fails. All 30
showcase source assets match their hashes and exact compiled-file whitelist;
Polish draft clips are excluded from the final gallery. This is browser emulation,
not a claim of physical-phone or subjective listening acceptance.


Final source audit confirmed current database ownership and original application
file hashes for all 12 distinct generated media artifacts; their Tasks and Runs
also belong to the non-administrator demo account and succeeded. Five additional
unaltered Library screenshots show the actual English voice results and exact
spoken text, linked from each voice card. Titles were saved through the normal
demo-owned annotation API; neither DOM text nor execution history was rewritten.
The owner subsequently accepted this existing gallery; see the approval record below.


### Owner approval and original music (2026-11-07)

The owner reviewed and approved the complete existing gallery ("wszystko wyglada
bardzo dobrze, commituj") and requested two generated music examples. Preserve
that approval for the existing 30 assets; no previously rejected image or Polish
draft is added. Two ordinary demo-owned ACE-Step music Runs produced First Light
(45-second instrumental) and Little Signals (45-second synthpop with synthetic vocal). Source and export signal/decode checks are recorded privately.
The complete uncut stereo MP3s use 320 kbps encoding and only linear peak headroom;
no external mastering, stitched musical performance or substituted audio is used.

Music cards reuse the keyboard-accessible, exclusive sample playback and add a
seek slider. Full prompts, lyrics, duration and settings remain inspectable. The
new artwork is native HTML/CSS/SVG, not additional photographic/generated media.
Existing image-publication approval is preserved; the owner can assess the new
music's musical quality in the preview. No human-listening verdict is invented.
Normal publication proceeds through a reviewed PR to develop and an owner-merged
protected master promotion; no direct release-branch push or merge is authorized.

Automated speech transcription did not establish exact lyric fidelity for the
synthpop sample. Its supplied original lyrics are shown as generation inputs,
not a verified transcript. Music quality follows owner listening acceptance;
ASR alone must not disqualify a sung performance.


The owner subsequently listened and explicitly preferred the original vocal
synthpop recording to Neon Current. Restore Little Signals as the second public
sample. Automated speech transcription is not a valid proxy for musical quality
or a reason to overrule owner listening acceptance; exact sung-lyric fidelity
remains unclaimed. Neon Current stays private. No new generation was needed.
