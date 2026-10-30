# Optional local prompt enhancement (NR-04)

Implementation uses the existing `media_translation.py` worker,
dependency, review, model startup/eviction, receipt and recovery contracts. This
plan does not expose an unimplemented checkbox or claim an engine is available.

## User flow

Add **Improve my prompt locally** beside the descriptive prompt. It is off by
default and independent of translation. A small explanation says the original
is retained and only the descriptive prompt is improved. Settings → Generation
selects the existing local preparation model; no hidden external provider is
allowed. Existing compatible uncensored local models remain selectable.

The submitted version shows **Original**, **Prepared for this model** and the
actual preparation model. Optional review uses the existing editable approval
panel. The generator receives only the verified effective fields after the
preparation dependency succeeds. A failed preparation offers retry or the original
through the existing explicit recovery flow. It never generates twice because
the browser retries an acknowledgement.

## Service changes

Extend the existing nested preparation options with an explicit enhancement flag.
Its false/default value must be excluded from legacy request fingerprints and
stored policy identities; old queued/retry plans keep their exact behavior.
Freeze an enhancement template version, consumer backend/operation and local
model in the preparation policy. The existing executor can select faithful
translation, enhancement, or a combined preparation without a second LLM call.

Keep the current translation SYSTEM and decoder for legacy Runs. New enhancement
templates must preserve explicit instructions, exclusions, identity/reference
roles, protected placeholders, quoted words and numeric constraints. Permit
bounded descriptive expansion only in the requested fields. A successful JSON
parse is insufficient: verify exact keys, protected-token multiplicities,
nonempty values, each consumer's actual length limits and finite bounded output.
Use the existing source hash and grouped-consumer checks before review/apply.

Model-specific fixed templates cover image generation, instruction-only editing,
recomposition, Wan motion/camera descriptions and ACE-Step music descriptions.
Structural edits must remain instructions, without adding an identity-preservation
phrase that contradicts a requested pose/object change. Do not add content
restrictions or promise to override the selected model's own behavior.

Lyrics and spoken text are never enhancement fields. Echo's descriptive motion
prompt uses this boundary for direct clips and complete-recording segment jobs.
When speech is generated first, the local model/policy is frozen before speech
starts. Preparation follows the final portrait/audio and agent-source snapshots;
grouped segments share preparation and review. Creative history exposes review
on the actual animation child, including when the first Run generated speech.
The current fixed whole-Sonic recipe has no free motion-prompt input: do not
pretend enhancement affects it. Expressive TTS delivery instructions belong to
NR-06 and must not rewrite the narration. Pure upscale has no descriptive prompt.

Retry retains the original local model and translation choice. Choosing the
original explicitly disables both enhancement and translation for that attempt.
No migration, additional executor or native runtime change is required.

## Qualification

- Preserve all legacy translation/retry identities when enhancement is off.
- Fake-model API/worker tests prove the actual prepared prompt reaches each
  supported generator, with original/effective/model/template provenance.
- Reject missing/duplicated placeholders, extra fields, excessive expansion,
  changed source hashes and cross-owner consumers. Preserve exact lyrics/script.
- Test Stop during local model loading, preparation, review and generation,
  lost acknowledgements, restart and reuse/retranslation/original recovery.
- Exercise the actual optional checkbox, saved-session restore and editable
  preparation on desktop/mobile. Review the diff and pass local checks before
  rollout; keep real-model quality comparisons separate from synthetic contracts.

## Workstation acceptance, 2026-10-30

PR #517 implements the supported preparation workflows. Its complete affected
backend families pass 687 cases, with 951 frontend baseline cases and 37 final
component-family cases. Compiled private desktop/mobile checks verify actual
submission, review/edit, effective generator input, receipts and restored history.

A real neutral image passed the full local path: Qwen3.5 9B Uncensored Q6_K
prepared the description, optional review approved it, and LUSTIFY v10 Turbo Q4_0
generated the image using that exact text. Original/effective receipts are saved
with the private result. This verifies real use, not an A/B quality benchmark or
a promise that every model will improve every request.

That trial also exposed increasing SQLAlchemy owner-filter state during polling;
PR #518 retains the scope filters without reapplying them on each refresh. Its
490-case account/media gate plus one final regression pass. The final frontend
follow-up covers enhancement by itself, with translation off and review disabled:
40 complete component-family cases and the compiled desktop/mobile path pass.
Private evidence remains under `data/acceptance/prompt-enhancement-20261030/`,
`account-refresh-fix-20261030/` and `image-prompt-checkbox-20261030/`.
