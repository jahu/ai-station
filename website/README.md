# Project landing page

Release 0.3 adds durable ReAct conversation chains, retained references and
compatible model selection for existing image agents.

The real creation showcase in `assets/showcase/` uses a dedicated
non-administrator demo account. The owner approved the 30-asset image/voice/UI
bundle on 2026-11-07 and requested two additional original local music examples.
Future new photographic/generated imagery still requires its own review.
See [the showcase plan](../docs/plans/public-showcase.md).

Release 0.2 adds capability-guided public model discovery and hardware advice
before weights transfer. Publisher links, complete model components, reviewed
installation and explicit update review reuse the application model lifecycle.
Download filenames and release-note URLs come from `site.config.json`; do not
hard-code a prior version in HTML. The preview must use the newly compiled output.
Previously approved neutral media stays unchanged. New showcase assets require
their own publication review.

A standalone, static product website. It lives alongside the application so its
claims and screenshots can be reviewed together. It has **no application runtime,
API, database, npm dependencies or hosting account dependency**. Moving this
directory to a separate Git repository does not require application files.

## Build and preview

Python 3.12+ is already a project prerequisite. From the application repository:

```bash
python3 website/build.py
python3 -m http.server 8766 --bind 127.0.0.1 --directory website/dist
```

Open **http://127.0.0.1:8766**. Stop the preview with Ctrl+C. The AI Station app
on port 8765 is independent and is not restarted or exposed by this preview.

From a standalone website checkout, use `python3 build.py` and serve `dist`.

## Rename, change repository or add a domain

Edit **site.config.json**, then rebuild. It controls the product name, release
version, GitHub repository, release branch and optional canonical website URL.
Names and links are rendered into real HTML at build time; they do not depend on
JavaScript or an API call. The logo is the existing `assets/station.svg` and can
be replaced as a separate branding decision.

Leave `canonical_url` empty until a real HTTPS address exists. Once configured,
the build adds canonical/Open Graph URL and image tags, a sitemap and its robots
entry. A URL with a repository subpath works; asset paths are relative. Rebuilding
without a domain removes an old generated sitemap. No fabricated domain is used.

Page structure and copy live in `src/index.html`, styles in `src/style.css`, and
the small browser-only interactions in `src/app.js`. There are no tracking scripts,
external font requests, signup forms or private application endpoints. Links open
normally in the same tab. Native FAQs, content and installation links work with
JavaScript disabled. Clipboard copying also has a fallback for insecure contexts.

## Future hosting

Upload the contents of **dist/** to any static host, including GitHub Pages,
Cloudflare Pages or an ordinary web server. No domain is required to start; a
host-provided URL can be configured later. GitHub Pages build commands would be
`python3 website/build.py`, with `website/dist` as the deployment artifact.

There is deliberately no deployment workflow, GitHub Pages setting change or
public hosting registration in this change. The owner can choose hosting and a
name before publishing. Normal source changes use a PR to `develop`; release PRs
to `master` are created by the existing bot and remain for human-owner approval.

## Content, privacy and licensing

- The main message is approachable local AI: download, guided installation and a
  familiar conversation, with creation tools in the same app. The three-step
  journey uses the 0.1 Linux/Windows packages; qualification and unsigned-Windows
  behavior remain visible, and manual Linux commands stay in native details.
  Physical Windows NVIDIA and voice/film listening are post-release QA by owner
  decision, not claimed passes. The owner deferred macOS on 2026-11-03;
  it is an unsupported known startup issue, not an active release promise.
- Testing and feedback have a dedicated section with direct issue/suggestion
  links. No technical background or code contribution is required to help.
  README and the page lead with the same promise: no AI or IT background, one
  conversation and guided setup. Keep published-release requirements visible
  until that download-and-install experience is qualified and released. Feedback
  asks for attempted action, expected result and actual result, without secrets.
- Benchmarks quote the existing recorded runs, with hardware, scope and a link to
  the full methodology. It does not invent user counts, testimonials or partners.
- Previously owner-approved neutral screenshots and the tour remain unchanged.
  The new showcase uses actual generated outputs and real result/recipe views
  from a separate demo account. No operator Library, conversation or agent
  configuration is exported. Failed experiments are excluded from the curated
  gallery. Voice impressions are labeled synthetic, with source attribution;
  they are not authentic speech, endorsements or official built-in presets.
  Playback MP3s use documented linear volume matching only; original application
  artifacts stay unchanged. No denoising, EQ or watermark-removal processing.
- Original public examples stay safe for work. Compatible adult/NSFW models are
  described in text, without generating nudity or implying that blurred clothed
  photography was explicit material. Faster GPU performance is distinguished
  from model/settings-dependent quality.
- Native audio/video controls work without JavaScript. Media uses explicit
  playback; no voice or video autoplays. The enhanced voice cards load metadata
  for real durations, provide keyboard play/pause and progress, and pause other
  showcase players. Native audio controls remain the no-JavaScript fallback.
  Five English clips replace the Polish drafts. Licensed portrait thumbnails
  retain their separate source licenses and attribution in each card and NOTICE. Per-result links
  expose the actual prompt/recipe screenshot, not a fabricated chat success.
- `asset-provenance.json` records the media hashes and upstream font source. Geist
  is hosted locally under the SIL OFL; its full license is included.
- `LICENSE` and `NOTICE` are included here and in the output so this directory can
  stand alone. The project is source-available, free for permitted noncommercial
  use; other commercial use requires a separate written license. Models retain
  their own licenses.

Browser QA should cover mobile/desktop, keyboard tabs, FAQs, menu, modal focus and
Escape, video, clipboard fallback, no external requests, and no JavaScript errors.
Use the compiled output and include a GitHub Pages-style subpath. Application
tests are independent; do not claim a new full app qualification for a site-only
change.

Music examples use the same exclusive playback, with keyboard-accessible seeking.
Both are complete 45-second instrumentals, exported from real demo-owned
ACE-Step Runs as 320 kbps stereo MP3s. Prompts and settings are visible; the
rejected vocal experiment remains private and is not advertised.
