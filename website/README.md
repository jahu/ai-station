# Project landing page

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

- The site distinguishes current Linux/manual setup from the planned guided setup.
- Benchmarks quote the existing recorded runs, with hardware, scope and a link to
  the full methodology. It does not invent user counts, testimonials or partners.
- Only the previously owner-approved neutral screenshots and tour are included,
  unchanged. No current production Library, private conversation or real agent
  configuration is exported. Example conversation/agent text is seeded demo data.
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
