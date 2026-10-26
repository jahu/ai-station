#!/usr/bin/env python3
"""Build a portable static website using only the Python standard library."""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent


def build(output: Path) -> None:
    config = json.loads((ROOT / "site.config.json").read_text())
    name = config["name"].strip()
    repository = config["repository"].rstrip("/")
    branch = config["release_branch"]
    canonical = config.get("canonical_url", "").strip().rstrip("/")
    if not name or not re.fullmatch(r"https://github\.com/[\w.-]+/[\w.-]+", repository):
        raise ValueError("Set a nonempty name and an HTTPS GitHub repository URL.")
    if not re.fullmatch(r"[\w./-]+", branch):
        raise ValueError("Invalid release branch.")
    if canonical:
        url = urlsplit(canonical)
        if (
            url.scheme != "https"
            or not url.netloc
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError(
                "canonical_url must be an HTTPS website URL without credentials, query or fragment."
            )
    docs = f"{repository}/blob/{branch}/docs"
    values = {
        "NAME": name,
        "VERSION": config["version"],
        "REPO": repository,
        "REPO_NAME": repository.rsplit("/", 1)[1],
        "BRANCH": branch,
        "RELEASE_URL": f"{repository}/releases/tag/v{config['version']}",
        "MEDIA_URL": f"{docs}/media/README.md",
        "MODELS_URL": f"{docs}/models.md",
        "SETUP_URL": f"{docs}/getting-started.md",
        "BENCHMARKS_URL": f"{docs}/benchmarks.md",
        "ARCHITECTURE_URL": f"{docs}/architecture.md",
        "ROADMAP_URL": f"{docs}/plans/consumer-first-setup.md",
        "LICENSE_URL": f"{repository}/blob/{branch}/LICENSE",
        "COMMERCIAL_URL": f"{repository}/blob/{branch}/COMMERCIAL.md",
        "CONTRIBUTING_URL": f"{repository}/blob/{branch}/CONTRIBUTING.md",
    }
    document = (ROOT / "src/index.html").read_text()
    for key, value in values.items():
        document = document.replace("{{" + key + "}}", html.escape(str(value), quote=True))
    canonical_meta = ""
    if canonical:
        address = html.escape(canonical + "/", quote=True)
        image = html.escape(canonical + "/assets/conversation.png", quote=True)
        canonical_meta = f'<link rel="canonical" href="{address}">\n  <meta property="og:url" content="{address}">\n  <meta property="og:image" content="{image}">'
    document = document.replace("{{CANONICAL_META}}", canonical_meta)
    if re.search(r"\{\{[A-Z_]+\}\}", document):
        raise ValueError("Unresolved template variable.")
    output.mkdir(parents=True, exist_ok=True)
    shutil.copytree(ROOT / "assets", output / "assets", dirs_exist_ok=True)
    for name in ["style.css", "app.js"]:
        shutil.copyfile(ROOT / "src" / name, output / "assets" / name)
    for name in ["LICENSE", "NOTICE", "asset-provenance.json"]:
        shutil.copyfile(ROOT / name, output / name)
    (output / "index.html").write_text(document)
    (output / "robots.txt").write_text(
        "User-agent: *\nAllow: /\n" + (f"Sitemap: {canonical}/sitemap.xml\n" if canonical else "")
    )
    sitemap = output / "sitemap.xml"
    if canonical:
        sitemap.write_text(
            f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>{html.escape(canonical + "/")}</loc></url></urlset>\n'
        )
    elif sitemap.exists():
        sitemap.unlink()
    print(f"Built static website: {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    arguments = parser.parse_args()
    build(arguments.output.resolve())
