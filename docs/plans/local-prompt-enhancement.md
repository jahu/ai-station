# Optional local prompt enhancement (NR-04)

Implementation follows NR-02, using the existing `media_translation.py` worker,
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
prompt can use the same boundary when its request/consumer checks are extended.
The current fixed whole-Sonic recipe has no free motion-prompt input: do not
pretend enhancement affects it. Expressive TTS delivery instructions belong to
NR-06 and must not rewrite the narration. Pure upscale has no descriptive prompt.

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
