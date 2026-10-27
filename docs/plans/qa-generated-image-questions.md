# Questions about the conversation's image

Real browser QA found that an ordinary question about a generated image, with
passive default Web enabled, searched public stock photographs instead of
inspecting the exact image in the conversation. A successful text completion is
not evidence that the generated pixels were inspected.

Recognize direct English/Polish visual questions and descriptions referring to
the generated, previous, attached or current image. Reuse the existing
conversation-result resolver and local Vision action. Disable only this turn's
passive Web preference; explicit research, selected tools, current attachments,
project bindings, source ambiguity, unavailable results and protected paths keep
their existing precedence. Quoted instructions and generic discussion must not
authorize pixels. Source IDs come from verified persisted results, never text.

Keep Task → Run → Events → Artifacts, source snapshots, local-only Vision,
cancellation/recovery and source-byte checks. No new provider, executor, native
operation, schema or dependency is needed. Validate ordinary generated results,
fresh retries after Stop, inspected inputs, missing/ambiguous/unavailable results,
explicit Web/tool scope, quotes and nonvisual questions. Exercise an actual
ordinary question in the original QA conversation after deployment, inspect its
exact Vision source/result and verify no new photo generation or public search.
