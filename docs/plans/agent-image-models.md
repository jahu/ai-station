# Agent image model controls and result layout

New image-agent drafts default to Qwen unless the current user explicitly names a supported model. The controller enforces that default instead of trusting a model-authored Juggernaut choice. Retain explicit Juggernaut requests. Switching a proposal to Qwen clears Juggernaut-only seed/negative prompt and stale model-specific coordinates; existing saved agents and past Runs are not rewritten.

Reuse one Qwen/Juggernaut selector in the full agent media editor and compact conversation card. Saving a choice keeps the agent disabled until Accept and Enable, uses the existing saved-revision update API, and shows pending/error feedback. In the full editor expose Juggernaut's negative prompt beside the existing seed under Advanced. Switching to Qwen atomically clears both unsupported options; keep backend API validation strict.

Agent outputs form a vertical result → workflow → history layout. Scope static positioning to agent media results, including conversation results, so the Images workspace can retain its two-column sticky preview. Verify computed positioning and non-overlap while scrolling on desktop/mobile with a neutral completed image fixture, alongside actual model-setting saves. Do not run real image generation just to test a form or CSS, and do not publish private Library images.
