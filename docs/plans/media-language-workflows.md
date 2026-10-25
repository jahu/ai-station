# Shared translation for music and video

Next increment after image translation PR #442. Implementation is not yet
qualified or deployed. Reuse `media_translate`, reviewed apply, private local
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
