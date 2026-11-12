"""Translate CSS paint coordinates into visual language, not visible design tokens."""

import colorsys
import re
from functools import lru_cache

from PIL import ImageColor

CSS_COLOR = re.compile(r"(?<![\w#])#(?:[0-9a-f]{6}|[0-9a-f]{3})(?![\w])", re.IGNORECASE)


@lru_cache(maxsize=256)
def color_name(value):
    # A generative shot cannot promise exact RGB pixels under arbitrary lighting.
    # Preserve hue/tone with a standard CSS name; the compositor still receives
    # the original exact brand palette. Achromatic colors do not have a hue.
    rgb = ImageColor.getrgb(value)
    hue, lightness, saturation = colorsys.rgb_to_hls(*(v / 255 for v in rgb))

    def distance(name):
        other = ImageColor.getrgb(name)
        other_hue, other_lightness, other_saturation = colorsys.rgb_to_hls(*(v / 255 for v in other))
        hue_distance = min(abs(hue - other_hue), 1 - abs(hue - other_hue))
        return (
            4 * hue_distance**2 * min(saturation, other_saturation)
            + (lightness - other_lightness) ** 2
            + (saturation - other_saturation) ** 2
        )

    return min(sorted(ImageColor.colormap), key=distance)


def visual_color_words(text):
    return CSS_COLOR.sub(lambda match: color_name(match.group()), text)
