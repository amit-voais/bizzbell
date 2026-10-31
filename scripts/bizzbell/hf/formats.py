"""Output sizes and safe zones for Version B. Each ratio is laid out again, never cropped from another.

Safe zones are fractions of the frame kept clear of platform UI (Reels/Shorts buttons and captions bar at the
bottom, the profile row at the top). Every text element must sit inside it."""
from ..errors import UsageError

# name -> width, height, safe zone (left, top, right, bottom as fractions of the frame)
FORMATS = {
    "9x16": {"ratio": "9:16", "w": 1080, "h": 1920, "safe": (0.06, 0.11, 0.06, 0.20)},
    "1x1": {"ratio": "1:1", "w": 1080, "h": 1080, "safe": (0.06, 0.06, 0.06, 0.08)},
    "16x9": {"ratio": "16:9", "w": 1920, "h": 1080, "safe": (0.05, 0.07, 0.05, 0.08)},
    "4x5": {"ratio": "4:5", "w": 1080, "h": 1350, "safe": (0.06, 0.07, 0.06, 0.10)},
}
ORDER = ["9x16", "1x1", "16x9", "4x5"]
REQUIRED = ["9x16", "1x1", "16x9"]      # 4x5 is made only when its text fits (spec section 5, stage 9)


def name(ratio):
    """'9:16', '9x16', '9X16' -> '9x16'. Raises UsageError for an unknown ratio."""
    r = str(ratio).strip().lower().replace(":", "x").replace("/", "x")
    if r not in FORMATS:
        raise UsageError("unknown ratio %r (use one of %s)" % (ratio, ", ".join(FORMATS[k]["ratio"] for k in ORDER)))
    return r


def parse_list(text):
    """'9:16,1:1' -> ['9x16', '1x1'] in the canonical order; empty -> every ratio."""
    if not text:
        return list(ORDER)
    want = [name(x) for x in str(text).split(",") if x.strip()]
    return [r for r in ORDER if r in want]


def safe_box(ratio):
    """The safe zone in pixels: (left, top, right, bottom) edges."""
    f = FORMATS[name(ratio)]
    l, t, r, b = f["safe"]
    return (round(f["w"] * l), round(f["h"] * t), round(f["w"] * (1 - r)), round(f["h"] * (1 - b)))


def unit(ratio):
    """Base type unit in px: 1.0 at 1080 px on the short side."""
    f = FORMATS[name(ratio)]
    return min(f["w"], f["h"]) / 1080.0
