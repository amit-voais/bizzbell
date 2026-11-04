"""bb analyse retention: where people left, and what was being said then. Shows what happened, not why.

Adapted from yt-retention/retention.py in Jakeschincariol/youtube-agent-skill (MIT, see NOTICE)."""
import csv
import io
import re

from ..errors import BBError, UsageError
from .text import clip, finite, load_cues, parse_clock, printable, read_input, source_name

MIN_POINTS = 8
DEFAULT_MIN_DROP = 0.8
DEFAULT_TOP = 5
LONG_HOOK_SECONDS = 30.0
SAID_LEAD_SECONDS = 2.0
_SECONDS = re.compile(r"second|\bsecs?\b|\(s\)|\btime\b|सेकंड|समय", re.I)
_PERCENT = re.compile(r"%|percent|ratio|प्रतिशत", re.I)

NOTES = [
    "These numbers show what happened, not why. A drop says people left around this moment; it does not say the "
    "line or the picture there made them leave.",
    "Heuristic: the opening window, the size of a cliff and the window of words shown for each cliff are rules of "
    "thumb, and each can be changed with an option.",
]


def _number(cell):
    """(value, marked with a percent sign, was a clock time) or None."""
    text = cell.strip().replace(" ", "").replace(" ", "")
    marked = text.endswith("%")
    text = text.rstrip("%")
    if ":" in text:
        clock = parse_clock(text)
        return None if clock is None else (clock, False, True)
    if re.match(r"^\d+,\d{1,2}$", text):
        text = text.replace(",", ".")
    elif re.match(r"^\d{1,3}(,\d{3})+(\.\d+)?$", text):
        text = text.replace(",", "")
    value = finite(text)
    return None if value is None or value < 0 else (value, marked, False)


def _delimiter(text):
    first = next((ln for ln in text.splitlines() if ln.strip()), "")
    return "\t" if "\t" in first else ";" if ";" in first else ","


def _header_unit(label):
    if _PERCENT.search(label):
        return "percent"
    return "seconds" if _SECONDS.search(label) else None


def read_points(path):
    """([(position, percent still watching)] sorted by position, what the file says about its axis, skipped rows)."""
    text = read_input(path, "retention export").lstrip("﻿")
    header, cols, points, unit, skipped = None, None, [], None, 0
    try:
        for row in csv.reader(io.StringIO(text, newline=""), delimiter=_delimiter(text)):
            parsed = [_number(c) for c in row]
            found = [i for i, p in enumerate(parsed) if p is not None]
            if cols is None:
                if len(found) < 2:
                    header = row if any(c.strip() for c in row) else header
                    continue
                cols = found[:2]
                if header and cols[0] < len(header):
                    unit = _header_unit(header[cols[0]])
            if len(row) <= max(cols) or parsed[cols[0]] is None or parsed[cols[1]] is None:
                skipped += 1
                continue
            pos, val = parsed[cols[0]], parsed[cols[1]]
            if pos[2]:
                unit = "seconds"
            elif pos[1] and unit is None:
                unit = "percent"
            points.append((pos[0], val[0]))
    except csv.Error as e:
        raise BBError("%s is not a readable CSV (%s)" % (printable(path), e))
    points.sort(key=lambda p: p[0])
    unique = []
    for p in points:
        if unique and p[0] == unique[-1][0]:
            skipped += 1
        else:
            unique.append(p)
    return unique, unit, skipped


def _choose_axis(points, forced, unit, duration):
    """('percent' | 'seconds', why, optional note). A seconds axis ends near the duration, a percent axis near 100."""
    top = points[-1][0]
    if forced:
        return forced, "--axis", None
    if unit:
        return unit, "the file's own heading or marks", None
    if duration and abs(top - duration) <= max(1.0, 0.03 * duration):
        return "seconds", "the last point matches --duration", None
    if top > 100.5:
        return "seconds", "the last point is above 100", None
    if duration:
        return "percent", "the last point does not match --duration", None
    if top <= 1.0:
        return "percent", "every position is between 0 and 1", None
    if top < 90:
        return "seconds", "guess: the last point stops short of 100", (
            "The position column has no unit, so seconds is a guess. Confirm with --axis or --duration.")
    return "percent", "guess: the last point is close to 100", (
        "The position column has no unit, so percent is a guess. Confirm with --axis or --duration.")


def _opening(points, axis, duration, hook_seconds):
    """(window end on the axis, plain description of the window)."""
    if hook_seconds is None and duration:
        hook_seconds = min(LONG_HOOK_SECONDS, 0.25 * duration)
    if hook_seconds is None:
        return 10.0, "the first 10% of the video"
    if axis == "seconds":
        return hook_seconds, "the first %.1f s" % hook_seconds
    return hook_seconds / duration * 100.0, "the first %.1f s" % hook_seconds


def analyse(path, transcript=None, duration=None, axis=None, hook_seconds=None, min_drop=DEFAULT_MIN_DROP,
            top=DEFAULT_TOP):
    """The report as a dict: the opening, the steepest drops and the average slide after the opening."""
    points, unit, skipped = read_points(path)
    if len(points) < MIN_POINTS:
        raise BBError("%s has %d usable data row(s); at least %d are needed. Expected two columns: a position and the "
                      "percent still watching" % (printable(path), len(points), MIN_POINTS))
    notes = list(NOTES)
    if max(p[1] for p in points) <= 2.0:
        points = [(x, y * 100.0) for x, y in points]
        notes.append("The watching column looked like ratios (0 to 1), so it was multiplied by 100.")
    chosen, axis_basis, axis_note = _choose_axis(points, axis, unit, duration)
    if axis_note:
        notes.append(axis_note)
    if chosen == "percent" and points[-1][0] <= 1.0:
        points = [(x * 100.0, y) for x, y in points]
        notes.append("The position column looked like ratios (0 to 1), so it was multiplied by 100.")
    cues = None
    if transcript:
        cues, _ = load_cues(transcript)
    duration_basis = "--duration" if duration else None
    if not duration and chosen == "seconds":
        duration, duration_basis = points[-1][0], "the last point of the export"
    if not duration and cues:
        duration, duration_basis = max(c[1] for c in cues), "the last line of the transcript (an estimate)"
    if chosen == "percent" and hook_seconds and not duration:
        raise UsageError("--hook-seconds on a percent axis also needs --duration")

    def seconds(x):
        if chosen == "seconds":
            return x
        return x / 100.0 * duration if duration else None

    cutoff, window = _opening(points, chosen, duration, hook_seconds)
    start = points[0][1]
    inside = [y for x, y in points[1:] if x <= cutoff]
    lost = round(start - min(inside), 2) if inside else None
    if lost is None:
        notes.append("The export has no point inside the opening window, so the opening loss is not reported.")
    steps = []
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if y0 - y1 > min_drop:
            steps.append(((y0 - y1) / (x1 - x0), x0, x1, y0 - y1))
    steps.sort(key=lambda s: (-s[0], s[1]))
    cliffs = []
    for _, x0, x1, drop in steps[:top]:
        at, to = seconds(x0), seconds(x1)
        cliff = {"from": round(x0, 2), "to": round(x1, 2), "lost_points": round(drop, 2),
                 "at_seconds": None if at is None else round(at, 1), "to_seconds": None if to is None else round(to, 1)}
        if cues is not None and at is not None:
            near = [c[2] for c in cues if c[0] <= to and c[1] >= at - SAID_LEAD_SECONDS]
            cliff["said"] = clip(" ".join(near), 200)
        cliffs.append(cliff)
    after = [p for p in points if p[0] >= cutoff]
    slide = None
    if len(after) >= 2:
        unit_span = after[-1][0] - after[0][0]
        per = "percent of the video"
        if seconds(after[-1][0]) is not None:
            unit_span, per = seconds(after[-1][0]) - seconds(after[0][0]), "second"
        if unit_span > 0:
            slide = {"points_lost": round((after[0][1] - after[-1][1]) / unit_span, 3), "per": per}
    return {
        "tool": "retention", "heuristic": True, "source": source_name(path), "points": len(points),
        "skipped_rows": skipped, "axis": chosen, "axis_basis": axis_basis,
        "duration_seconds": None if not duration else round(duration, 3), "duration_basis": duration_basis,
        "start_percent": round(start, 2), "end_percent": round(points[-1][1], 2),
        "opening": {"window": window, "lost_points": lost},
        "cliffs": cliffs, "min_drop_points": min_drop, "slide_after_opening": slide, "notes": notes,
    }


def render(rep):
    """The report as Markdown."""
    lines = ["# Audience retention", "", "Source: %s, %d points, %.1f%% to %.1f%% still watching." % (
        rep["source"], rep["points"], rep["start_percent"], rep["end_percent"]),
        "Axis: %s (%s)." % (rep["axis"], rep["axis_basis"])]
    if rep["duration_seconds"]:
        lines.append("Length: %.1f s (from %s)." % (rep["duration_seconds"], rep["duration_basis"]))
    if rep["skipped_rows"]:
        lines.append("Skipped %d row(s) that could not be read or repeated a position." % rep["skipped_rows"])
    lost = rep["opening"]["lost_points"]
    lines += ["", "## Opening (heuristic window)", "",
              "Not reported." if lost is None else "%.1f points lost in %s." % (lost, rep["opening"]["window"]),
              "", "## Steepest drops (heuristic: over %.1f points in one step)" % rep["min_drop_points"], ""]
    for c in rep["cliffs"]:
        where = "at %.1f s" % c["at_seconds"] if c["at_seconds"] is not None else "at %.1f%% of the video" % c["from"]
        said = c.get("said")
        lines.append("- %.1f points %s%s" % (c["lost_points"], where, ": \"%s\"" % said if said else ""))
    if not rep["cliffs"]:
        lines.append("None: no single step was that steep.")
    slide = rep["slide_after_opening"]
    lines += ["", "## After the opening", "",
              "Not enough points to say." if not slide else "%.3f points lost per %s on average." % (
                  slide["points_lost"], slide["per"]),
              "", "## How to read this", ""] + ["- " + n for n in rep["notes"]]
    return "\n".join(lines) + "\n"
