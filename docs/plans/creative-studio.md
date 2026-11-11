# Creative Studio: branded reels, presentations and films

User goal, 2026-11-11. This is the delivery contract, not a statement that the
feature is already available. Existing media generation and editing remain in
place. Do not replace this goal with a template-only demo or mark it complete
after the project registry or a successful synthetic render.

Owner quality clarification, 2026-11-11: materials must be professionally
art-directed social content, with dynamic images, actual video and purposeful
motion, not a sequence of text on colored backgrounds. Static shots remain
valid when they serve the brief. A simple typography render qualifies only the
rendering component; it cannot qualify the product or close this goal. Design
for a strong hook, retention, platform-appropriate rhythm and shareability;
never promise virality or fabricate engagement metrics.

## Experience

**Studio** is a creative workspace for repeatable publication-quality materials.
Create a project such as a business, a course or a personal brand, describe its
audience and style, and keep related materials together. No repository path,
Git configuration, technical rendering flags or Chat/Work mode is required.
Projects are optional: a standalone request can create a standalone material.

A project holds its name, recognizable names/domains, description and one
editable identity: palette, typography, visual direction, tone, audience,
language, editorial rules and audio direction. Defaults select reel,
presentation or film, aspect ratio, length and narration/music policy. Never
assume a particular business, person, subject or language. Logos and reference
media must use existing owned Library artifacts, not arbitrary host paths.

Each material has an independent brief, script, storyboard, editable scene
timing, sources, audio and render history. Explain the chosen project and format
before/alongside execution and allow override. A changed project applies to new
work only; historical plans/renders retain the exact identity version used.
Archiving preserves project, sources and history. Deletion must not orphan or
silently purge existing results.

The unified assistant uses its existing LlamaIndex ReAct controller. Supply a
bounded catalog of the current account's projects and typed operations; choose
by the prompt's meaning and project names/domains, not a growing regex router.
Do not guess across ambiguous projects. Project-free requests stay supported.
Standalone Studio and assistant requests must use the same planner/builders.

## Execution and quality

Task → Run → Events → Artifacts remains the only execution path. Plan with the
selected local provider, validate structured scene/script output, generate
requested assets with existing images/speech/music adapters, then render using
Hyperframes. Observe actual completed children before composing their outputs.
Voice, music, both or silence follow the user's intent and visible project
defaults. Never silently deliver a silent film when audio was requested.

Hyperframes supplies deterministic HTML motion graphics, typography, diagrams,
captions and transitions. It complements Wan footage, rather than asking a
diffusion model to draw readable text. Use pinned dependencies and a finite,
typed composition contract compiled by trusted code. Project text, model output
and downloaded content cannot supply executable scripts, package names, shell
commands, runtime flags, URLs or host mounts. Rendering executes behind a typed
native Runner operation, with owned process identity, resource reservation,
deadline, Stop, restart recovery and immutable output publication. No raw HTML
execution endpoint and no control-plane Docker socket.

Default publication sizes are 1080×1920 for reels and 1920×1080 for widescreen
presentations/films, square when explicitly selected. Render at deterministic
30 fps with readable text/safe areas; higher output quality must not be confused
with native diffusion detail. Use local fonts and frozen assets: no network or
missing CDN resources during rendering. Enforce per-scene text/contrast/layout
bounds, keep sources, and export a high-quality playable MP4 with verified
duration, frame count and requested audio. Track QA failures as real failures.
Check narration duration before finalizing scene timings; pad/extend scenes,
never cut words to satisfy an earlier guessed duration. Mix music below speech,
avoid clipping, and expose voice/music controls. Reuse existing voice leveling
and timeline audio primitives where appropriate. Avatar and generated-footage
insertion must retain source provenance, aspect fitting and actual timing.

The creative planner must act as a director/editor, not just a copywriter. Its
structured storyboard describes the hook, narrative beats, shot type, asset
brief/source, on-screen action, camera/framing, timing, transition purpose,
narration, captions, music and sound accents. Generate coherent original images
and actual footage through the existing adapters; reuse approved Library assets
where appropriate. Preserve brand and subject continuity through shared source
references. Distinguish intentional image motion/parallax from generated video
and disclose the actual source in the inspector. Add composition controls for
image movement, video trim and placement, overlays and transitions; do not
mistake a changing headline for a dynamic visual scene. Avoid an arbitrary quota
of video shots: choices should serve the brief, subject, desired pacing and
actual hardware budget. Keep planned visuals, generated media and final edit
inspectable and editable; retain successes when one generation fails.

Default quality targets publication, not the cheapest passing template. Full
material QA includes narrative coherence, a clear opening, variation in shot
scale/composition, temporal continuity, transition frames, text safe areas and
legibility, voice cadence, sound design and a coherent ending/CTA where useful.
Use representative complete branded reels and educational films for visual and
audible acceptance, not a screenshot of one title or a silent six-second test.

## Delivery sequence

1. Private creative projects, versioned brand/default settings, project-bound
   existing creative workspaces, immutable generation context, and a polished
   project browser/editor. Alembic migration and two-account regression tests.
2. Pinned Hyperframes renderer/preparation/diagnostics behind the native boundary;
   real typography/motion render, cancellation and recovery qualification.
3. Durable structured script/storyboard planner and editable material revisions;
   integrate actual speech/music children and final full-HD render. Preserve
   drafts, sources and previous exports. No inference in HTTP handlers.
4. Assistant catalog, typed project selection and material-creation tools,
   including standalone materials and follow-up revisions. Project inference is
   model-based, bounded and inspectable, with owner-validated aliases.
5. Existing avatar/video/image insertion and postproduction; useful review and
   export UX on desktop and mobile. Document exact platform prerequisites and
   delivery status. Do not advertise unqualified Windows functionality.

These are implementation increments; the complete user goal requires all of
the above, not only the first merged PR.

## Acceptance evidence required

- Create two differently styled projects, edit/archive/restore, reopen after
  restart, keep independent materials; no account or administrator-write leak.
- Concurrent/stale saves and repeated submissions cannot overwrite identity,
  duplicate rendering, attach foreign media or lose prior results.
- Same-project renders visibly share palette/type/tone; a second project has
  an independently recognizable identity. Generic subjects work equally well.
- From Chat, create a branded reel and a standalone reel, select widescreen for
  an educational presentation, and correct a project choice in a follow-up.
- Actual voiced, music-only and voiced-plus-music exports; inspect complete
  playback, captions, timing, intelligibility, music ducking and clipping.
- Real full-HD portrait and landscape Hyperframes exports with no clipped text,
  unreadable slides, blank frames or browser/asset errors. Inspect frames at
  transitions and throughout the film, not just the opening screenshot.
- Incorporate actual avatar and generated media into an exported presentation
  through the same owned workflow; inspect aspect and audio synchronization.
- Stop during planning, audio generation and rendering; restart observation
  without duplicate side effects; release only owned resources. Other GPU work
  continues and bounded waiting respects the existing deadline fixes.
- Backend/Runner checks, migration validation, frontend tests/lint/typecheck/
  production build, reviewed diff and local deployment qualification. Any real
  expensive run is explicit; ordinary tests use disposable data/fake adapters.
- Public showcase publication remains a separate owner approval; private test
  outputs belong in the account Library and must not leak into the website.

## Research

Official Hyperframes [CLI](https://hyperframes.app/docs/5-packages/cli) and
[source](https://github.com/heygen-com/hyperframes), inspected 2026-11-11. It
supports local frame-seeking render and HTML media tracks. Pin and inspect the
actual installed version before choosing command flags; do not install from a
moving `latest` during a render or reuse unrelated project runtime ownership.

## Delivery progress

- Project registry and identity workspace merged to develop in #713/#714.
- Native isolated renderer merged to develop in #715; see
  [its contract and qualification scope](../hyperframes-renderer.md).
- Private materials, immutable revisions, local director/storyboards and their
  editor are the current increment; see [material semantics](../studio-materials.md).
- Remaining: guided renderer preparation, actual visual/audio child Runs,
  timing/mix and render/export UI,
  assistant tools/project inference, avatar insertion and complete branded
  publication-quality acceptance. The overall goal remains active.
