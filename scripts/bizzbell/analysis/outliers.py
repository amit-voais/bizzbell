"""bb analyse outliers: collected videos ranked by how far each beat its own channel's median.

It reads one JSON file that a person or the agent gathered. It does not fetch anything and needs no login.
Adapted from yt-viral/swipe.py in Jakeschincariol/youtube-agent-skill (MIT, see NOTICE)."""
import re
import statistics
import unicodedata

from ..errors import BBError
from .text import finite, printable, read_json_input, source_name

DEFAULT_MIN_MULTIPLE = 1.5
DEFAULT_MIN_VIDEOS = 4
DEFAULT_TOP = 25
_SCALE = {unicodedata.normalize("NFC", k): v for k, v in (
    ("k", 1e3), ("m", 1e6), ("b", 1e9), ("lakh", 1e5), ("lac", 1e5), ("crore", 1e7), ("cr", 1e7),
    ("लाख", 1e5), ("करोड़", 1e7))}
_VIEWS = re.compile(r"^(\d[\d,._]*)\s*(%s)?(?:\s*(?:views?|%s))?$" % (
    "|".join(sorted(_SCALE, key=len, reverse=True)), unicodedata.normalize("NFC", "व्यूज़")))

NOTES = [
    "This shows which videos did well against their own channel, not why they did. The title, the topic, the "
    "thumbnail, the date and luck are all mixed together in the number.",
    "Heuristic: the median comes only from the videos in your file and includes the video itself. A list holding only "
    "a channel's best videos gives a high median and hides its outliers.",
    "Older videos have had longer to collect views, and Shorts and long videos are not split here. Compare like "
    "with like when you collect.",
]


def parse_views(value):
    """(views, rounded in the source) from 1234, \"12,000\", \"12.000\", \"1.2M\" or \"3 lakh views\"; else None."""
    if isinstance(value, str):
        m = _VIEWS.match(unicodedata.normalize("NFC", value).strip().casefold())
        if not m:
            return None
        digits, suffix = m.group(1), m.group(2)
        if suffix:
            number = finite(digits.replace(",", "").replace("_", ""))
            return None if number is None else (number * _SCALE[suffix], True)
        if re.match(r"^\d{1,3}(\.\d{3})+$", digits):
            digits = digits.replace(".", "")
        number = finite(digits.replace(",", "").replace("_", ""))
        return None if number is None else (number, False)
    number = finite(value)
    return None if number is None or number < 0 else (number, False)


def _channel_key(name):
    return " ".join(unicodedata.normalize("NFKC", name).casefold().split())


def analyse(path, min_multiple=DEFAULT_MIN_MULTIPLE, min_videos=DEFAULT_MIN_VIDEOS):
    """The report as a dict: `outliers`, best first, and the channels that could not be scored."""
    rows = read_json_input(path, "collected video list")
    if isinstance(rows, dict):
        rows = rows.get("videos")
    if not isinstance(rows, list):
        raise BBError("%s should be a list of videos, or {\"videos\": [...]}" % printable(path))
    channels, seen, skipped, repeats = {}, set(), 0, 0
    for row in rows:
        name = row.get("channel") if isinstance(row, dict) else None
        views = parse_views(row.get("views")) if isinstance(row, dict) else None
        if not isinstance(name, str) or not name.strip() or views is None:
            skipped += 1
            continue
        title = row.get("title") if isinstance(row.get("title"), str) else ""
        url = row.get("url") if isinstance(row.get("url"), str) else ""
        key = _channel_key(name)
        identity = url.strip() or ((key, title.strip()) if title.strip() else None)
        if identity and identity in seen:
            repeats += 1
            continue
        if identity:
            seen.add(identity)
        channels.setdefault(key, {"name": name.strip(), "videos": []})["videos"].append((title, url, views))
    if not channels:
        raise BBError("%s has no usable video. Each one needs a \"channel\" and a \"views\" number" % printable(path))
    outliers, thin, no_median = [], [], []
    for ch in channels.values():
        if len(ch["videos"]) < min_videos:
            thin.append({"channel": ch["name"], "videos": len(ch["videos"])})
            continue
        median = statistics.median(v[2][0] for v in ch["videos"])
        if median <= 0:
            no_median.append(ch["name"])
            continue
        for title, url, (views, rounded) in ch["videos"]:
            multiple = views / median
            if multiple >= min_multiple:
                outliers.append({"channel": ch["name"], "title": title, "url": url, "views": int(views),
                                 "views_rounded_in_source": rounded, "channel_median": round(median, 1),
                                 "multiple": round(multiple, 2)})
    outliers.sort(key=lambda r: (-r["multiple"], -r["views"], r["title"]))
    return {
        "tool": "outliers", "heuristic": True, "source": source_name(path),
        "videos_read": sum(len(c["videos"]) for c in channels.values()), "channels": len(channels),
        "skipped_rows": skipped, "repeated_rows": repeats, "min_multiple": min_multiple, "min_videos": min_videos,
        "outliers": outliers, "thin_channels": thin, "channels_with_zero_median": no_median, "notes": NOTES,
    }


def render(rep, top=DEFAULT_TOP):
    """The report as Markdown."""
    lines = ["# Outliers against each channel's own median (heuristic)", "",
             "Source: %s, %d videos across %d channels. Shown: %.1fx or better." % (
                 rep["source"], rep["videos_read"], rep["channels"], rep["min_multiple"])]
    if rep["skipped_rows"]:
        lines.append("Skipped %d row(s) without a channel or a readable views number." % rep["skipped_rows"])
    if rep["repeated_rows"]:
        lines.append("Ignored %d repeated video(s)." % rep["repeated_rows"])
    lines += ["", "## Ranked", ""]
    for r in rep["outliers"][:top]:
        approx = " (rounded in the source)" if r["views_rounded_in_source"] else ""
        lines.append("- %.2fx: %s, %s views against a median of %s%s: %s" % (
            r["multiple"], r["channel"], format(r["views"], ","), format(int(r["channel_median"]), ","), approx,
            r["title"] or r["url"] or "(no title)"))
    if not rep["outliers"]:
        lines.append("Nothing reached the threshold.")
    elif len(rep["outliers"]) > top:
        lines.append("And %d more in outliers.json." % (len(rep["outliers"]) - top))
    if rep["thin_channels"]:
        lines += ["", "## Not scored", "", "Fewer than %d videos collected, too few for a median: %s." % (
            rep["min_videos"], ", ".join("%s (%d)" % (t["channel"], t["videos"]) for t in rep["thin_channels"]))]
    if rep["channels_with_zero_median"]:
        lines += ["", "Median of zero views, so no multiple: %s." % ", ".join(rep["channels_with_zero_median"])]
    lines += ["", "## How to read this", ""] + ["- " + n for n in rep["notes"]]
    return "\n".join(lines) + "\n"
