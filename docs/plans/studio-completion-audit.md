# Creative Studio implementation audit — 2026-11-12

This audit maps the current Studio goal to delivered behavior. It supersedes
historical pending lists in the delivery diary; it does not imply a new public
installer release or approval to publish private media.

| Requirement | Delivered behavior and evidence |
| --- | --- |
| Independent brand projects | Private projects hold palette, type, tone, audience, language, rules and defaults. CRUD, stale saves, archive/restore and owner isolation have automated coverage. Real Field Notes and Maker Notes films use visibly different identities. |
| Optional projects and formats | Ordinary local-model conversations created branded portrait/music and landscape/silent films, plus a standalone voiced reel. Studio supports reel, presentation and film with portrait, landscape and square formats. |
| Real visual storytelling | The complete portrait reel contains actual generated video and photographs, with camera motion and directed scene changes. A real multi-window portrait Wan clip and the generated-source workflow passed decoding; static editorial scenes remain deliberate options. |
| Complete narration and music | Actual exports cover voice-only, music-only and voice/music. The 75-second educational film retains all 179 spoken words; independent transcription found no edits. The owner accepted narration pace, expression and voice continuity throughout. |
| Generic speech continuity | Shared per-job seed and fixed first-voice conditioning apply to supported app-owned Fish/Chatterbox generation, including other capabilities. Voice references retain their original recording; phrase directions are separate from exact spoken text. |
| Full-HD composition | Actual 1080×1920 and 1920×1080 films passed complete decoding, frame/duration/source/audio checks and sampled scene/transition inspection. Copy-aware text layout, clip fitting and readable backgrounds have dedicated tests. |
| Speaking presenter | A complete real 17.2-second production includes a newly generated Sonic presenter with the original soundtrack. Source, timing, complete decoding, sampled presenter frames and exact audio checks passed. This qualifies integration; each generated take still has its own visual quality. |
| Follow-up editing | A real ordinary chat turn changed only the first headline of a 16-second film. A new parented version retained every photo/video source and trim, the exact score, original material and history. No new media inference was required. |
| Correct project choice | The next real chat turn produced a separate widescreen copy under the other brand's saved identity, without moving/modifying the source material. Full decode, source/audio identity, frame count and sampled visual checks passed. |
| Ownership, Stop and restart | Ordinary Tasks/Runs own planning, audio, visuals, presenter and export. Closed registries forward Stop without canceling historical source Tasks. Fake-adapter tests cover account boundaries, idempotency, cancellation and recovery; prior actual renderer preparation/Stop/restart and first-use export were also qualified. |
| Installation and boundaries | Fixed local renderer preparation and readiness use the existing native Runner/private socket; control-plane containers receive neither Docker control nor host filesystem authority. A preserving deployment kept data, settings, schema, ports and search, with a database backup. |
| Inspectable UI | Studio exposes identities, storyboards, shot sources, expression/timing controls, audio, complete production and export history. Chat returns the actual film and its saved-revision link. Desktop/mobile Studio checks and action-result regression tests passed. |

The reviewed implementation passed 482 Studio/assistant tests. Its subsequent
exact captured-alias correction passed 38 relevant intent/binding/Studio-contract
tests. Global Python lint/format, frontend lint, TypeScript, 42 action tests,
production build, Compose configuration and the exact application-image/offline
probe passed. The unscoped whole-repository suite was interrupted and is not
reported as successful; the relevant successful checks are the local equivalent
per repository guidance. Hosted Actions remain manual.

Private receipts keep actual Run/artifact identities, original failed attempts,
file/audio/frame checks and contact sheets. Synthetic tests qualify orchestration
contracts; the real outputs qualify the specific exercised local integrations.
Nothing in this audit guarantees every generated take's aesthetic quality,
virality, factual accuracy or suitability for unattended public publication.
