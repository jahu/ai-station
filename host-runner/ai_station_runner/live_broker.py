"""Bounded ephemeral media routing. No models, host audio devices or shell access."""

import asyncio
import contextlib
import hmac
import json
import time

from ai_station_runner.live_ipc import CLOCK, read_async, write_async
from ai_station_runner.live_protocol import Kind, Packet, StreamOrder, decode, encode
from ai_station_runner.unix_sockets import unix_address


def failure_code(error):
    while isinstance(error, BaseExceptionGroup):
        error = error.exceptions[0]
    if isinstance(error, asyncio.QueueFull):
        return "input_overload"
    if isinstance(error, TimeoutError):
        return "processing_timeout"
    if isinstance(error, (EOFError, BrokenPipeError, ConnectionError)):
        return "engine_connection_ended"
    if isinstance(error, ValueError):
        return "invalid_media_packet"
    return "live_processing_failed"


class LiveBroker:
    def __init__(self, *, face=None, voice=None, secret, deadline_at, statistics=None):
        self.face, self.voice = face, voice
        self.secret, self.deadline_at = secret, deadline_at
        self.statistics = statistics or (lambda value: None)
        self.connected = False
        self.used = False  # Browser capture is never silently resumed/replayed.
        self.finished = asyncio.Event()
        self.error = None
        self.counts = {"camera_frames": 0, "audio_blocks": 0, "tracking_pauses": 0}

    async def session(self, reader, writer):
        admitted = False
        try:
            supplied = await asyncio.wait_for(read_async(reader), 2)
            if not hmac.compare_digest(supplied, self.secret.encode()) or self.connected or self.used:
                raise ValueError("The live connection is not authorized or has already been used")
            self.connected, self.used, admitted = True, True, True
            await write_async(writer, b'{"ready":true}')
            outgoing = asyncio.Queue(maxsize=8)
            camera = asyncio.Queue(maxsize=1)
            microphone = asyncio.Queue(maxsize=4)
            order = StreamOrder()
            started = time.monotonic()
            first_audio = None

            async def receive():
                nonlocal first_audio
                camera_count = 0
                async for raw in _packets(reader):
                    packet = decode(raw, incoming=True)
                    order.accept(packet)
                    elapsed = time.monotonic() - started
                    if packet.timestamp_us / 1e6 > elapsed + 2:
                        raise ValueError("The live input clock is ahead of real time")
                    if packet.kind == Kind.CAMERA:
                        if self.face is None:
                            raise ValueError("Face conversion was not enabled")
                        camera_count += 1
                        if camera_count > 30 * (elapsed + 1):
                            raise ValueError("Live camera exceeds its bounded frame rate")
                        if camera.full():
                            camera.get_nowait()  # Latest frame wins; audio is never dropped.
                        camera.put_nowait(raw)
                    else:
                        if self.voice is None:
                            raise ValueError("Voice conversion was not enabled")
                        if first_audio is None:
                            first_audio = time.monotonic()
                            if packet.sequence != 0 or packet.timestamp_us != 0:
                                raise ValueError("Start a fresh live audio clock")
                        if packet.sequence > (time.monotonic() - first_audio + 1) * 5:
                            raise ValueError("Live audio input is arriving faster than real time")
                        microphone.put_nowait(packet)

            async def face_loop():
                while True:
                    raw = await camera.get()
                    await write_async(self.face.stdin, raw)
                    response = await asyncio.wait_for(read_async(self.face.stdout), 2)
                    if response[:1] == b"P":
                        decode(response[1:], incoming=False)
                        await outgoing.put(response[1:])
                        self.counts["camera_frames"] += 1
                        response = await asyncio.wait_for(read_async(self.face.stdout), 2)
                    if response[:1] != b"J":
                        raise ValueError("Invalid face inference response")
                    stats = json.loads(response[1:])
                    if stats.get("tracking") is False:
                        self.counts["tracking_pauses"] += 1
                    await outgoing.put(json.dumps({"face": stats}).encode())

            async def voice_loop():
                while True:
                    packet = await microphone.get()
                    await write_async(
                        self.voice.stdin, CLOCK.pack(packet.sequence, packet.timestamp_us) + packet.body
                    )
                    response = await asyncio.wait_for(read_async(self.voice.stdout), 2)
                    clock = CLOCK.pack(packet.sequence, packet.timestamp_us)
                    if response[:1] != b"A" or response[1 : 1 + CLOCK.size] != clock:
                        raise ValueError("Converted speech does not match its source clock")
                    await outgoing.put(
                        encode(
                            Packet(
                                Kind.SPEECH, packet.sequence, packet.timestamp_us, response[1 + CLOCK.size :]
                            )
                        )
                    )
                    stats = await asyncio.wait_for(read_async(self.voice.stdout), 2)
                    if stats[:1] != b"J":
                        raise ValueError("Invalid voice inference observation")
                    await outgoing.put(json.dumps({"voice": json.loads(stats[1:])}).encode())
                    self.counts["audio_blocks"] += 1

            async def transmit():
                last_observation = started - 5
                while True:
                    await write_async(writer, await outgoing.get())
                    now = time.monotonic()
                    if now - last_observation >= 5:
                        self.statistics({**self.counts, "elapsed_seconds": round(now - started, 2)})
                        last_observation = now

            async def deadline():
                await asyncio.sleep(max(0, self.deadline_at - time.time()))

            async with asyncio.TaskGroup() as group:
                jobs = [
                    group.create_task(receive()),
                    group.create_task(transmit()),
                    group.create_task(deadline()),
                ]
                if self.face is not None:
                    jobs.append(group.create_task(face_loop()))
                if self.voice is not None:
                    jobs.append(group.create_task(voice_loop()))
                await asyncio.wait(jobs, return_when=asyncio.FIRST_COMPLETED)
                for job in jobs:
                    job.cancel()
            self.statistics(self.counts)
        except Exception as exc:
            # No media, reference bytes or local coordinates in public diagnostics.
            if admitted:
                self.error = failure_code(exc)
                with contextlib.suppress(Exception):
                    await write_async(writer, json.dumps({"error": self.error}).encode())
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
            if admitted:
                self.connected = False
                self.finished.set()

    async def serve(self, path, *, connect_timeout=15):
        import os

        with unix_address(path) as address:
            server = await asyncio.start_unix_server(self.session, address)
        os.chmod(path, 0o600)
        try:
            async with server:
                await asyncio.wait_for(
                    self.finished.wait(), min(connect_timeout, max(0, self.deadline_at - time.time()))
                )
        finally:
            server.close()
            await server.wait_closed()
            path.unlink(missing_ok=True)


async def _packets(reader):
    while True:
        try:
            yield await asyncio.wait_for(read_async(reader), 5)
        except asyncio.IncompleteReadError:
            return
