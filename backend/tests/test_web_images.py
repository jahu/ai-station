import io

import httpx
import pytest
from app import web_images
from app.providers import ProviderError
from PIL import Image


def pixels():
    f = io.BytesIO()
    Image.new("RGB", (48, 32), "blue").save(f, format="PNG")
    return f.getvalue()


def transport(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        web_images.httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw)
    )

    async def addresses(host):
        if host == "internal.example.com":
            raise ValueError("Refusing a non-public network address")
        return ["93.184.216.34"]

    monkeypatch.setattr(web_images, "public_addresses", addresses)


@pytest.mark.asyncio
async def test_pinned_download_keeps_authority_and_sni_then_canonicalizes(monkeypatch, tmp_path):
    def handler(request):
        assert request.url.host == "93.184.216.34"
        assert request.headers["Host"] == "photos.example.com"
        assert request.extensions["sni_hostname"] == "photos.example.com"
        assert "authorization" not in request.headers and "cookie" not in request.headers
        return httpx.Response(200, headers={"content-type": "image/png"}, content=pixels())

    transport(monkeypatch, handler)
    data, url = await web_images.download_image("https://photos.example.com/photo.png")
    target = tmp_path / "stored.png"
    assert web_images.canonical_image(data, target) == (48, 32)
    assert url == "https://photos.example.com/photo.png" and Image.open(target).format == "PNG"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "location",
    [
        "http://127.0.0.1/metadata",
        "http://169.254.169.254/latest",
        "https://internal.example.com/picture.png",
    ],
)
async def test_private_redirects_and_dns_are_rejected(monkeypatch, location):
    transport(monkeypatch, lambda request: httpx.Response(302, headers={"location": location}))
    with pytest.raises(ValueError, match="non-public"):
        await web_images.download_image("https://photos.example.com/start")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "headers,body",
    [
        ({"content-type": "text/html"}, b"<html>not a photo</html>"),
        ({"content-type": "image/png", "content-length": str(21 * 1024**2)}, b""),
        ({"content-type": "image/png"}, b"x" * 80),
    ],
)
async def test_bad_type_size_and_invalid_pixels_cannot_be_published(monkeypatch, tmp_path, headers, body):
    transport(monkeypatch, lambda request: httpx.Response(200, headers=headers, content=body))
    with pytest.raises((ValueError, httpx.HTTPError)):
        data, _ = await web_images.download_image("https://photos.example.com/image")
        web_images.canonical_image(data, tmp_path / "bad.png")


@pytest.mark.asyncio
async def test_search_selects_actual_image_urls_not_page_links_and_rejects_private_rows(monkeypatch):
    from app.config import clear_settings_cache

    monkeypatch.setenv("AI_STATION_WEB_SEARCH_URL", "http://127.0.0.1:9999")
    clear_settings_cache()

    def handler(request):
        assert b"categories=images" in request.content
        return httpx.Response(
            200,
            json={
                "results": [
                    {"img_src": "http://127.0.0.1/private", "title": "Bad"},
                    {
                        "img_src": "https://photos.example.com/one.png",
                        "url": "https://example.com/source",
                        "title": "Real photograph",
                    },
                    {"img_src": "https://photos.example.com/one.png"},
                ]
            },
        )

    transport(monkeypatch, handler)
    result = await web_images.search_images("a neutral object")
    assert len(result["sources"]) == 1 and result["sources"][0]["url"] == "https://photos.example.com/one.png"
    assert result["sources"][0]["page_url"] == "https://example.com/source"


@pytest.mark.asyncio
async def test_no_results_is_failure_not_a_fake_image(monkeypatch):
    from app.config import clear_settings_cache

    monkeypatch.setenv("AI_STATION_WEB_SEARCH_URL", "http://127.0.0.1:9999")
    clear_settings_cache()
    transport(monkeypatch, lambda request: httpx.Response(200, json={"results": []}))
    with pytest.raises(ProviderError, match="no usable images"):
        await web_images.search_images("rare object")


@pytest.mark.parametrize(
    "enabled,policy,expected",
    [(False, "public-images-v1", False), (True, None, False), (True, "public-images-v1", True)],
)
def test_web_image_tools_require_explicit_web_permission_and_captured_policy(enabled, policy, expected):
    from app.assistant_controller_tools import available_tools

    tools = available_tools({"web_search": {"enabled": enabled}, "controller_web_image_policy": policy})
    assert ("web.image_search" in tools) == expected
    assert ("web.image_import" in tools) == expected


@pytest.mark.asyncio
async def test_chunked_image_limit_is_enforced_without_content_length(monkeypatch):
    monkeypatch.setattr(web_images, "MAX_BYTES", 64)
    transport(
        monkeypatch,
        lambda request: httpx.Response(
            200, headers={"content-type": "image/png"}, stream=httpx.ByteStream(pixels())
        ),
    )
    with pytest.raises(ValueError, match="exceeded"):
        await web_images.download_image("https://photos.example.com/image")


def test_dimension_and_animation_limits_are_checked_before_publication(monkeypatch, tmp_path):
    monkeypatch.setattr(web_images, "MAX_PIXELS", 100)
    with pytest.raises(ValueError, match="megapixels"):
        web_images.canonical_image(pixels(), tmp_path / "large.png")
    monkeypatch.setattr(web_images, "MAX_PIXELS", 10000)
    output = io.BytesIO()
    Image.new("RGB", (8, 8), "blue").save(
        output,
        format="WEBP",
        save_all=True,
        append_images=[Image.new("RGB", (8, 8), "red")],
        duration=100,
        loop=0,
    )
    with pytest.raises(ValueError, match="still image"):
        web_images.canonical_image(output.getvalue(), tmp_path / "animated.png")
