"""Fixed local MP4 encoding policy; never accepts client codec/filter options."""


def h264_options():
    return {"crf": "18", "preset": "medium"}


def video_encoding_metadata():
    return {"codec": "h264", "pixel_format": "yuv420p", "crf": 18, "preset": "medium"}
