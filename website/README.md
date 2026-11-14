# Project landing page

The public site is **https://ai-station.dev**, hosted on Cloudflare Pages from
`master`. The landing page and installation guide use `site.config.json` for
release filenames and links. The current published download is **0.7.0**.
Update the configuration and the “What's new” section together when preparing a
release, then verify the compiled output against the GitHub release assets.
See [the release checklist](../docs/release-policy.md#public-release-information).

Only previously approved neutral showcase media is public. New photographs,
generated imagery or private Library exports still need the owner's review;
see [the showcase plan](../docs/plans/public-showcase.md).

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

`canonical_url` is set to `https://ai-station.dev`. For a standalone fork, set it
to the fork’s own HTTPS address, or leave it empty until one exists. Once configured,
the build adds canonical/Open Graph URL and image tags, a sitemap and its robots
entry. A URL with a repository subpath works; asset paths are relative. Rebuilding
without a domain removes an old generated sitemap. No fabricated domain is used.

Page structure and copy live in `src/index.html`, styles in `src/style.css`, and
the small browser-only interactions in `src/app.js`. There are no tracking scripts,
external font requests, signup forms or private application endpoints. Links open
normally in the same tab. Native FAQs, content and installation links work with
JavaScript disabled. Clipboard copying also has a fallback for insecure contexts.

## Hosting

Cloudflare Pages builds the production `master` branch with
`python3 website/build.py` and publishes **website/dist/** from the repository
root. Set `SKIP_DEPENDENCY_INSTALL=1`: this static site uses Python’s standard
library and must not auto-install the monorepo as a Python package. The owner
approves and merges promotions to `master`; Pages then rebuilds automatically.
Both `ai-station.dev` and `www.ai-station.dev` point to the Pages project.

To use another static host, upload the contents of `dist/`. No application API,
models, secrets or private workstation endpoints belong in the public output.

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
- Current Chat, Library, Video and Agents captures replace the older screenshots; the tour remains a historical composition. The agent screenshot is explicitly a disabled review draft, while the market chart/report links come from the separate verified execution. The owner reviewed these images and the longer film and requested only the agent-copy reframing documented below.
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
Both are complete 45-second tracks, exported from real demo-owned
ACE-Step Runs as 320 kbps stereo MP3s. Prompts and settings are visible; the
owner-selected synthpop recording includes a synthetic vocal and its supplied lyrics.

The coastal film candidate is 8 seconds at 1280×704/24 fps, generated as three real
Wan continuation segments, then given fresh MMAudio sound and an app-produced
preview mix. Its poster comes from the actual final film. The original short
version remains in private evidence as historical evidence. The market example
publishes the original agent chart and report/CSV contents with source dates;
text exports normalize line endings/trailing padding and retain source hashes. It is a
recorded research result, not a live quote feed or proof of unattended daily runs.

Agent positioning leads with one natural-language instruction, review/enable,
and recurring results across content creation, research and routine file jobs.
The market result is one supporting example. The prompt cards are illustrative,
not fabricated transcripts or additional smoke tests. Social video generation is
distinguished from direct social publishing, whose integrations remain planned.

## Installation guide

The separate `install/` page renders from `src/install.html`, with its own
`src/install.css`. The landing page links to it; no setup wizard or additional
installation detail is added to the showcase. Both pages work without JavaScript.
Canonical URLs and the sitemap include the guide and preserve a configured
repository subpath. Public screenshots must be real neutral QA captures, recorded
in asset provenance and reviewed by the owner before publication.
