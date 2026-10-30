"""Bounded streaming conditioning on the complete inspected source timeline."""

from fractions import Fraction

from ai_station_runner.effects_timing import effects_windows


def frame_indices(window, fps, target_fps):
    count = window.conditioning_frames * target_fps // fps
    return [
        min(window.first_frame + i * fps // target_fps, window.first_frame + window.frames - 1)
        for i in range(count)
    ]


def conditioning(path, source):
    import av
    import torch
    from torchvision.transforms import InterpolationMode
    from torchvision.transforms.v2 import functional as F

    windows = effects_windows(source.frames, source.fps)
    with av.open(str(path)) as container:
        if len(container.streams.video) != 1:
            raise ValueError("Choose a single video stream")
        stream = container.streams.video[0]
        if stream.average_rate != source.fps or stream.codec_context.name not in {
            "h264",
            "hevc",
            "mpeg4",
            "vp9",
            "av1",
        }:
            raise ValueError("Unsupported or changed video timing/codec")
        stream.thread_type = "SLICE"
        stream.codec_context.thread_count = 2
        decoded = iter(container.decode(video=0))
        buffer = {}
        count = 0

        def next_frame():
            nonlocal count
            try:
                frame = next(decoded)
            except StopIteration as exc:
                raise ValueError("Video is truncated") from exc
            if (
                (frame.width, frame.height) != (source.width, source.height)
                or frame.pts is None
                or frame.time_base is None
            ):
                raise ValueError("Video dimensions/timing changed")
            if abs(Fraction(frame.pts) * frame.time_base - Fraction(count, source.fps)) > Fraction(
                1, source.fps * 100
            ):
                raise ValueError("Video is not the inspected constant frame rate")
            image = torch.from_numpy(frame.to_ndarray(format="rgb24")).permute(2, 0, 1)
            clip = F.resize(image, [384, 384], interpolation=InterpolationMode.BICUBIC)
            sync = F.center_crop(F.resize(image, [224], interpolation=InterpolationMode.BILINEAR), [224, 224])
            buffer[count] = (clip, sync)
            count += 1

        for index, window in enumerate(windows):
            while count < window.first_frame + window.frames:
                next_frame()
            clip = torch.stack([buffer[i][0] for i in frame_indices(window, source.fps, 8)]).float().div_(255)
            sync = (
                torch.stack([buffer[i][1] for i in frame_indices(window, source.fps, 25)])
                .float()
                .div_(255)
                .sub_(0.5)
                .div_(0.5)
            )
            yield window, clip, sync
            if index + 1 < len(windows):
                keep = windows[index + 1].first_frame
                for i in list(buffer):
                    if i < keep:
                        del buffer[i]
        try:
            next(decoded)
        except StopIteration:
            pass
        else:
            raise ValueError("Video has more frames than its frozen observation")
        if count != source.frames:
            raise ValueError("Video frame count changed")
