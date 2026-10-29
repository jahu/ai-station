# Independent project landing page

The owner requested a public-facing landing page without committing to a domain
or a permanent product name. Keep its source in `website/`, as an independent
static package that can later move unchanged to a separate repository.

## Delivery contract

- A complete, responsive product narrative: local AI, actual workspaces, media,
  agents, hardware results, architecture, installation, licensing and FAQs.
- Existing approved neutral promotional assets only, with provenance. No new
  production Library capture or export.
- Honest current capabilities and setup requirements, separate from the consumer
  onboarding roadmap. No fabricated adoption figures or commercial/open-source claims.
- Product name, version, repository and optional canonical URL in one config.
- Relative local assets; local fonts, no analytics/API/forms or app credentials.
- Standalone build using the Python standard library; output deployable as static
  files at a domain root or repository subpath. No application dependency changes.
- Accessible controls, keyboard and reduced-motion behavior, clipboard fallback,
  video and screenshot previews, and useful no-JavaScript content.
- Validate the compiled page in desktop/mobile browsers and at a host subpath;
  review the final source diff before merging into `develop`.

Hosting and public deployment are a later owner choice. This work does not expose
new host ports to the LAN/internet, register a domain, change GitHub Pages or modify
the running AI Station installation. A local preview is for review only.

See [website instructions](../../website/README.md).
