# Reviewable setup for video agents

The real #396 five-second film took about 1189 seconds; its first native window
took about 662 seconds. A new video agent's 600-second default can therefore expire
before its first result. #397 made fresh Video/Chat selection resource-aware but
deliberately preserved every agent definition.

Add one compact, shared suggestion to Agents settings and the conversation's
agent review. Show the existing available-memory recommendation for a compatible
text/landscape request and a suggested whole-workflow time limit: 2 hours for up
to 15 seconds, 4 hours for longer requests. These are reviewable maximum allowances,
not speed estimates or promises that every duration finishes within them.

- Never apply on render, activate an agent, start a Run or change a running budget.
  Existing saved values remain authoritative until the operator explicitly acts.
- Agents changes the editable draft, then uses its existing Save definition.
  Conversation review offers an explicit Apply and save action through the same
  versioned Agent settings API. Keep enabled state, schedule and permissions.
- Preserve instructions, scenes, seed, GPU and references. Do not auto-recommend
  the text-only low-memory profile for a portrait/square, fewer-step or image
  request. Never lower an existing larger/custom time limit.
- Use the existing 14,400-second ceiling and immutable execution contracts. Do
  not add a native adapter, new profile, model download or higher global timeout.
- Verify both review surfaces, no writes before operator action, exact saved
  patch, no activation/Run, pending/active disablement and compiled 1440/390 layout.
  Reuse #397 backend/native evidence only after exact source comparison; this is
  an editor improvement, not another expensive media qualification.

Live #397 is reviewed `992bb5c`, merged `9c0af73`, controller source
`.tools/ui-video-memory-recommendation-20261024`; native remains
`.tools/ui-wan-memory-profile-20261024` with fingerprint `f23dc6f7`. Central deployment
metadata and `data/acceptance/video-memory-recommendation-20261024/post-deployment-qualified.json`
are authoritative. Preserve the root Memory WIP and all live/proof trees.
