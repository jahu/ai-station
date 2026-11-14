"""The published guide must remain usable without JavaScript or root hosting."""

import importlib.util
import json
import shutil
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

import pytest

REPOSITORY = Path(__file__).resolve().parents[2]


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.targets = []
        self.identifiers = set()

    def handle_starttag(self, tag, attributes):
        fields = dict(attributes)
        if fields.get("id"):
            self.identifiers.add(fields["id"])
        for name in ("href", "src"):
            if fields.get(name):
                self.targets.append(fields[name])


def test_public_download_version_matches_the_application_release():
    config = json.loads((REPOSITORY / "website/site.config.json").read_text())
    application = json.loads((REPOSITORY / "frontend/package.json").read_text())
    assert config["version"] == application["version"], (
        "Update website/site.config.json when preparing a release; "
        "otherwise the public installer links keep serving an older version."
    )
    assert (REPOSITORY / f"docs/releases/{config['version']}.md").is_file()


@pytest.fixture
def website(tmp_path):
    source = REPOSITORY / "website"
    spec = importlib.util.spec_from_file_location("public_website_build", source / "build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root = tmp_path / "source"
    root.mkdir()
    shutil.copytree(source / "src", root / "src")
    (root / "assets/install").mkdir(parents=True)
    # The guide needs its actual capture and icon, not the large media showcase.
    for name in ("station.svg", "install/first-account.png"):
        shutil.copyfile(source / "assets" / name, root / "assets" / name)
    for name in ("LICENSE", "NOTICE", "asset-provenance.json", "site.config.json"):
        shutil.copyfile(source / name, root / name)
    module.ROOT = root
    return module, root, tmp_path / "output"


@pytest.mark.parametrize("canonical", ["", "https://example.test", "https://example.test/project"])
def test_guide_and_sitemap_preserve_portable_routes_and_current_release(website, canonical):
    module, source, output = website
    config = json.loads((source / "site.config.json").read_text())
    config["canonical_url"] = canonical
    (source / "site.config.json").write_text(json.dumps(config))
    module.build(output)
    landing = (output / "index.html").read_text()
    guide = (output / "install/index.html").read_text()
    assert 'href="install/"' in landing
    assert "{{" not in guide
    assert f"AI-Station-{config['version']}-windows-x64-Setup.exe" in guide
    assert f"AI-Station-{config['version']}-linux-amd64.deb" in guide
    for document in (landing, guide):
        for asset in ("windows-x64-Setup.exe", "linux-amd64.deb"):
            assert (
                f'href="{config["repository"]}/releases/download/v{config["version"]}/'
                f'AI-Station-{config["version"]}-{asset}"'
            ) in document
        assert f"/blob/{config['release_branch']}/docs/releases/{config['version']}.md" in document
    assert "<script" not in guide
    parser = Links()
    parser.feed(guide)
    for target in parser.targets:
        parsed = urlsplit(target)
        if parsed.scheme or parsed.netloc:
            continue
        if not parsed.path:
            assert parsed.fragment in parser.identifiers
            continue
        path = (output / "install" / parsed.path).resolve()
        assert path.is_relative_to(output.resolve())
        assert path.exists()
    if canonical:
        assert f'href="{canonical}/install/"' in guide
        sitemap = (output / "sitemap.xml").read_text()
        assert f"<loc>{canonical}/</loc>" in sitemap
        assert f"<loc>{canonical}/install/</loc>" in sitemap
    else:
        assert 'rel="canonical"' not in guide
        assert not (output / "sitemap.xml").exists()
    config["canonical_url"] = ""
    (source / "site.config.json").write_text(json.dumps(config))
    module.build(output)
    assert not (output / "sitemap.xml").exists()
