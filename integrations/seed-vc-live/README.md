# Seed-VC live worker

This separate **GPL-3.0** component connects the frozen external Seed-VC engine to
AI Station's native live-session coordinator over standard input/output. The core
application does not import this component or Seed-VC. Their licenses remain
separate; the source and GPL license are provided here. Model weights retain their
own licenses and are not bundled.

The worker accepts a private, coordinator-created request file and bounded mono
PCM blocks. It opens no microphone, speaker, camera, HTTP listener or model
publisher connection. Browser capture and playback belong to the application;
any attempt by the external engine to use PortAudio fails explicitly. Readiness
follows model loading and warmup, never import success alone.

Use through the typed live-session service. This component is not a general
command/API entry point. Runtime preparation and native ownership validation are
required before dispatch. See [the live feature contract](../../docs/plans/live-identity.md).
