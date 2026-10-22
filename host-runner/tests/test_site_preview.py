import asyncio
import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from ai_station_runner import site_preview_protocol as protocol
from ai_station_runner import site_preview_renderer as renderer


def config(**extra):
    return {"kind": "open", "entry": "index.html", "width": 800, "height": 600, "max_seconds": 30, **extra}


def request(action=None, **extra):
    return {
        "kind": "action",
        "id": str(uuid4()),
        "expected_revision": 0,
        "action": action or {"kind": "snapshot"},
        **extra,
    }


@pytest.mark.parametrize("path", ["index.html", "assets/main-abc.js", "images/café.png"])
def test_canonical_build_members_and_internal_resources(path):
    assert protocol.asset_path(path) == path
    assert protocol.resource_path(protocol.ORIGIN + "/" + path + "?v=1#section") == path


@pytest.mark.parametrize(
    "path",
    [
        "",
        ".",
        "../x",
        "/index.html",
        ".env",
        "assets/../x",
        "assets//x",
        "a\\x",
        "a:x",
        "a%2fx",
        "a?x",
        "a#x",
        "a\nx",
        "a\x7fx",
    ],
)
def test_ambiguous_or_escaping_asset_paths_fail(path):
    with pytest.raises(ValueError):
        protocol.asset_path(path)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://127.0.0.1/",
        "http://preview.invalid.evil/x",
        "https://preview.invalid/",
        "http://user:secret@preview.invalid/",
        "http://preview.invalid:80/x",
        "http://preview.invalid/%2e%2e/secret",
        "http://preview.invalid/%252e%252e/secret",
        "http://preview.invalid//x",
        "http://preview.invalid/a\nx",
    ],
)
def test_only_fixed_internal_origin_is_brokered(url):
    assert protocol.resource_path(url) is None


@pytest.mark.parametrize(
    "changes",
    [
        {"width": True},
        {"width": 1601},
        {"height": 100},
        {"max_seconds": 901},
        {"url": "https://example.org"},
        {"entry": "../../file"},
    ],
)
def test_initialization_cannot_select_network_or_unbounded_viewport(changes):
    with pytest.raises(ValueError):
        protocol.open_request(config(**changes))


@pytest.mark.parametrize(
    "action",
    [
        {"kind": "click", "x": 0, "y": 599},
        {"kind": "text", "text": "<script>literal input</script>"},
        {"kind": "key", "key": "Enter"},
        {"kind": "scroll", "delta_x": -1500, "delta_y": 1500},
        {"kind": "reset"},
        {"kind": "snapshot"},
    ],
)
def test_only_typed_bounded_interactions_are_accepted(action):
    value = request(action)
    assert protocol.action_request(value, 800, 600) == value


@pytest.mark.parametrize(
    "action",
    [
        {"kind": "evaluate", "script": "process.exit()"},
        {"kind": "click", "x": True, "y": 0},
        {"kind": "click", "x": 800, "y": 0},
        {"kind": "click", "x": 0, "y": -1},
        {"kind": "text", "text": "x" * 2001},
        {"kind": "text", "text": "x\x00"},
        {"kind": "key", "key": "Control+L"},
        {"kind": "reset", "url": "file:///etc/passwd"},
        {"kind": "scroll", "delta_x": 0, "delta_y": 1501},
        {"kind": []},
    ],
)
def test_interactions_cannot_be_commands_scripts_urls_or_hotkeys(action):
    with pytest.raises(ValueError):
        protocol.action_request(request(action), 800, 600)


def test_action_identity_revision_and_resource_response_are_strict(monkeypatch):
    for changes in (
        {"id": "../x"},
        {"id": str(uuid4()).upper()},
        {"expected_revision": True},
        {"expected_revision": -1},
        {"command": "sh"},
    ):
        with pytest.raises(ValueError):
            protocol.action_request(request(**changes), 800, 600)
    reply = {
        "kind": "resource",
        "id": 1,
        "status": 200,
        "content_type": "text/html",
        "body": base64.b64encode(b"ok").decode(),
    }
    assert protocol.resource_response(reply, 1) == b"ok"
    for changes in (
        {"id": True},
        {"id": 2},
        {"status": 302},
        {"content_type": "text/html\r\nset-cookie:x"},
        {"body": "!"},
        {"headers": {"authorization": "secret"}},
    ):
        with pytest.raises(ValueError):
            protocol.resource_response({**reply, **changes}, 1)
    monkeypatch.setattr(protocol, "MAX_RESPONSE", 1)
    with pytest.raises(ValueError):
        protocol.resource_response(reply, 1)


def page():
    return SimpleNamespace(
        url=protocol.ORIGIN + "/index.html",
        mouse=SimpleNamespace(click=AsyncMock(), wheel=AsyncMock()),
        keyboard=SimpleNamespace(insert_text=AsyncMock(), press=AsyncMock()),
        goto=AsyncMock(),
        wait_for_timeout=AsyncMock(),
        screenshot=AsyncMock(return_value=b"png bytes"),
        title=AsyncMock(return_value="Local preview"),
    )


@pytest.mark.asyncio
async def test_action_receipt_replay_and_stale_revision_never_repeat_a_click(monkeypatch):
    output = []
    monkeypatch.setattr(renderer, "message", output.append)
    session, browser = renderer.Session(config()), page()
    await session.frame(browser)
    click = request({"kind": "click", "x": 20, "y": 30})
    await session.action(browser, click)
    first = output[-1]
    await session.action(browser, click)
    assert output[-1] == first and first["revision"] == 1
    assert browser.mouse.click.await_count == 1 and browser.screenshot.await_count == 2
    await session.action(browser, request({"kind": "click", "x": 20, "y": 30}))
    assert output[-1]["reason"] == "stale_revision" and browser.mouse.click.await_count == 1
    await session.action(browser, {**click, "action": {"kind": "click", "x": 21, "y": 30}})
    assert output[-1]["reason"] == "receipt_conflict" and browser.mouse.click.await_count == 1


@pytest.mark.asyncio
async def test_literal_text_and_navigation_failure_cannot_escape_into_script_evaluation(monkeypatch):
    output = []
    monkeypatch.setattr(renderer, "message", output.append)
    session, browser = renderer.Session(config()), page()
    text = "<script>alert('literal')</script>"
    await session.action(browser, request({"kind": "text", "text": text}))
    browser.keyboard.insert_text.assert_awaited_once_with(text)
    browser.url = "chrome-error://chromewebdata/"
    await session.action(browser, request({"kind": "key", "key": "Enter"}, expected_revision=1))
    assert output[-1]["reason"] == "navigation_blocked"
    browser.keyboard.press.assert_not_awaited()
    await session.action(browser, request({"kind": "reset"}, expected_revision=1))
    browser.goto.assert_awaited_once_with(
        protocol.ORIGIN + "/index.html", wait_until="domcontentloaded", timeout=15_000
    )


@pytest.mark.asyncio
async def test_failed_action_is_reserved_and_cannot_be_replayed(monkeypatch):
    output = []
    monkeypatch.setattr(renderer, "message", output.append)
    session, browser = renderer.Session(config()), page()
    browser.screenshot.side_effect = ValueError("frame unavailable after click")
    click = request({"kind": "click", "x": 20, "y": 30})
    with pytest.raises(ValueError, match="unavailable"):
        await session.action(browser, click)
    await session.action(browser, click)
    assert output[-1]["reason"] == "receipt_conflict" and browser.mouse.click.await_count == 1


@pytest.mark.asyncio
async def test_resource_receiver_routes_by_identity_and_stops_on_close(monkeypatch):
    incoming = renderer.Input()
    future = asyncio.get_running_loop().create_future()
    incoming.pending[1] = future
    receive = AsyncMock(
        side_effect=[
            {"kind": "resource", "id": 1, "status": 200, "content_type": "text/plain", "body": "b2s="},
            {"kind": "close"},
        ]
    )
    monkeypatch.setattr(renderer, "receive", receive)
    await incoming.read()
    assert (await future)[1] == b"ok"
    monkeypatch.setattr(renderer, "receive", AsyncMock(return_value={"kind": "resource", "id": 2}))
    with pytest.raises(ValueError, match="identity"):
        await incoming.read()
