"""Capture unchanged upstream conditioning and finish one complete recording.

No imports of Torch/PyAV at module load: ordinary tests never load GPU runtimes.
"""


class _InputsReady(Exception):
    pass


def capture_inputs(native_test, device, *args):
    """Run the original audio preparation, stopping before its costly postprocess.

    The actual diffusion invocation is preserved, including global frame count,
    temporal attention, guidance and audio buckets. Do not create a dummy movie
    merely to satisfy native_test's final CPU→GPU→CPU normalization/cat.
    """

    class Capture:
        def __init__(self):
            self.device = device
            self.prepared = None

        def __call__(self, *positional, **keyword):
            self.prepared = (positional, keyword)
            raise _InputsReady()

    capture = Capture()
    try:
        native_test(capture, *args)
    except _InputsReady:
        if capture.prepared is not None:
            return capture.prepared
        raise
    raise ValueError("Sonic preparation did not reach its expected pipeline call")


def recording_frames(frames, timing, interpolate):
    """Yield one frame at a time, retaining only neighboring base images.

    Caller owns tensor validation/normalization and encoding. The sole repeated
    endpoint is prescribed by integer audio timing, never an internal freeze.
    """
    source = iter(frames)
    try:
        previous = next(source)
    except StopIteration as exc:
        raise ValueError("Missing whole-recording base frames") from exc
    yield previous
    for _ in range(1, timing.base_frames):
        try:
            current = next(source)
        except StopIteration as exc:
            raise ValueError("Truncated whole-recording base frames") from exc
        yield interpolate(previous, current)
        yield current
        previous = current
    exhausted = object()
    if next(source, exhausted) is not exhausted:
        raise ValueError("Unexpected extra whole-recording base frames")
    if timing.endpoint_frames:
        yield previous


def encode_recording(frames, timing, rife, output, width, height):
    import av
    import torch

    if list(frames.shape) != [1, 3, timing.base_frames, height, width] or frames.device.type != "cpu":
        raise ValueError("Invalid complete decoded Sonic recording")
    written = 0
    with av.open(str(output), "w") as movie:
        stream = movie.add_stream("libx264", rate=25)
        stream.width, stream.height, stream.pix_fmt = width, height, "yuv420p"
        stream.options = {"crf": "18", "threads": "2"}
        base = (frames[:, :, index] for index in range(timing.base_frames))
        for frame in recording_frames(base, timing, rife.inference):
            if not torch.isfinite(frame).all():
                raise ValueError("Non-finite generated avatar frame")
            rgb = frame[0].clamp(0, 1).mul(255).to(torch.uint8).permute(1, 2, 0).numpy()
            for packet in stream.encode(av.VideoFrame.from_ndarray(rgb, format="rgb24")):
                movie.mux(packet)
            written += 1
        for packet in stream.encode():
            movie.mux(packet)
    if written != timing.target_frames:
        raise ValueError("Avatar does not cover the complete recording")
    return written
