"""Bounded public metadata for the fixed official desktop release channel."""

import json

from ai_station_runner.station_release_metadata import API, admit_release, positive_id

from app.model_download_files import _wait, response

MAX_BYTES = 1024 * 1024


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("The official release metadata contains duplicate fields")
        result[key] = value
    return result


async def release_metadata(check, *, release_id=None):
    endpoint = f"{API}/releases/"
    endpoint += "latest" if release_id is None else str(positive_id(release_id))
    # The existing HTTPS transport pins public DNS and TLS at every hop. No
    # credentials, local files, machine identifiers or caller URLs are supplied.
    async with response(endpoint, 0, check) as result:
        if result.status_code in {403, 429}:
            raise ValueError("The update service is busy. Try checking again later.")
        if result.status_code != 200:
            raise ValueError("The official update service is unavailable")
        if (
            result.request.headers.get("host") != "api.github.com"
            or result.request.url.path != endpoint.removeprefix("https://api.github.com")
            or result.request.url.query
            or result.headers.get("content-encoding", "identity") != "identity"
        ):
            raise ValueError("The update service returned an unexpected source")
        length = result.headers.get("content-length")
        if length is not None and (not length.isdigit() or int(length) > MAX_BYTES):
            raise ValueError("The update metadata exceeds its size limit")
        body = bytearray()
        chunks = result.aiter_raw(chunk_size=65536).__aiter__()
        while True:
            try:
                chunk = await _wait(check, anext(chunks), 15)
            except StopAsyncIteration:
                break
            if len(body) + len(chunk) > MAX_BYTES:
                raise ValueError("The update metadata exceeds its size limit")
            body.extend(chunk)
    try:
        value = json.loads(body, object_pairs_hook=unique_object)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("The update service returned invalid release metadata") from exc
    snapshot = admit_release(value)
    if release_id is not None and snapshot["release_id"] != release_id:
        raise ValueError("The release identity changed during update preparation")
    check()
    return snapshot
