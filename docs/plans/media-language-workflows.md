# Shared translation for music and video

Video/music increment after image translation PR #442, qualified for PR #443.
Controller rollout follows review and merge into develop. Reuse `media_translate`, reviewed apply, private local
provider and existing model lifecycle; no native API or schema changes.

- Translate music captions and video positive/negative descriptive prompts.
  Lyrics, speech, subtitles, references and all execution settings stay unchanged.
  Default-off and absent override serialization preserve existing receipt identity.
- Shared creation functions cover workspaces, Chat/Work and agents. Per-request
  controls expose Inherit / Translate / Original and optional review. Media output
  and Library retain original/effective receipts and actual translator identity.
- Long films group identical segment instructions within the same Task. One
  translation serves each identical group, with every member's immutable inputs
  checked. All prompt preparation gates every film segment, allowing one model
  loading phase before media GPU allocation instead of repeated model swapping.
  Different scene descriptions remain separate groups; no cross-Task sharing.
- Review edits apply only to their exact group. The film result exposes pending
  reviews. Stop covers the complete Task; shared unrelated model consumers remain
  protected. No inference or native process launch occurs in HTTP handlers.
- Ordinary retry/film Resume reuse verified recorded effective prompts. Explicit
  retry translation uses frozen original text/policy; Use original is audited.
  Missing/changed proof blocks reuse. Film recovery creates a new plan revision,
  preserves completed segments and never silently reruns uncertain processes.
  Retry receipts bind both action and caller UUID, including lost acknowledgements.
- Verify caption/video field limits, protected text, supplied lyrics, mixed scenes,
  one preparation for repeated segments, all-preparation barrier, editable review,
  output lineage, Stop, failed preparation, frozen retries and Resume. Run normal
  repository gates, compiled desktop/phone checks and applicable actual local
  integration before release. Update the operator QA catalog.

## Qualification (2026-10-25)

Backend/Runner executable head `388a35f89438f580badfb9f16ce659647c73798a` passed
all 4,048 collected normal Python cases (4,039 passed, nine explicit opt-in skips)
and Ruff format/check. UI review repairs at `b0f0f0bc43eaa52c00fbf9c75008dfcf6020f340`
leave those backend/Runner/dependency trees unchanged. All 841 frontend tests,
format/lint/typecheck/build, six QA exporter checks, exact Docker source/assets,
all Compose configurations and isolated non-root API/worker/SQLite/SSE/reopen passed.

Compiled 1440px/390px browser flows used the actual API/worker and owned CPU media
fixtures with a fake translator: grouped 15-second films, editable approval,
checked final composition, music with unchanged Polish lyrics, saved receipts,
no JavaScript errors or horizontal overflow. Visual review corrected the Audio
review field sizing and preparation labels; final screenshots were inspected.

Actual installed Qwen3.5 9B Q6_K through managed multi-GPU llama.cpp translated
Polish music/video descriptions. A 10-second instrumental WAV and short Wan MP4
were generated, adopted and checksum-retained, with normal owned-model eviction
and cleanup. A four-step 640×384 preview was visually weak and qualifies only the
transport/adoption path. A separate standard 20-step, 33-frame 1280×704 Run passed;
its inspected first frame depicts the requested daylight lake/cloud scene.
No singing-quality, full-duration or universal translation improvement is claimed.
The native adapters and original photo pipeline remain unchanged. Isolated test
storage did not modify preview settings/model presets or external services.

Evidence: `data/acceptance/media-language-workflows-20261025`. The QA catalog now
contains 150 Polish cases across 21 areas. The final release workbook remains a
whole-platform handoff gate; operator testing has not been requested early.
