"""bb analyse edit: a transcript to an edit decision list. It only reads the transcript and never touches media.

Adapted from yt-edit/deadair.py in Jakeschincariol/youtube-agent-skill (MIT, see NOTICE)."""
from .text import clip, filler_words, load_cues, only_filler, source_name, unspaced, words

DEFAULT_FLOOR = 0.45
MIN_RESTART_WORDS = 3
RESTART_WORDS = 5
UNSPACED_RESTART_LETTERS = 10

NOTES = [
    "Heuristic: all of this is worked out from the words and timings in the transcript, not from the audio.",
    "A dead-air cut is a gap between spoken lines. The transcript cannot hear music, a sound effect or a planned "
    "pause, so check each one against the film.",
    "A retake is two lines in a row that open with the same words, or the same whole line said twice. A repeat said "
    "on purpose looks the same.",
    "Filler cues are for review and are not counted in the suggested cuts. In a Hindi or Hinglish voice-over they "
    "are often written in on purpose, and several of them (na, haan, yaar) are also ordinary words.",
]


def _is_restart(earlier, later):
    """`earlier` and `later` are (all words, words without fillers). Fillers are dropped so that a false start with an
    extra "umm" still matches, but a short line can have too few words left: the whole line said twice counts too."""
    (all_a, kept_a), (all_b, kept_b) = earlier, later
    if kept_a and kept_b and all_a == all_b and len(all_a) >= MIN_RESTART_WORDS:
        return True
    n = min(len(kept_a), len(kept_b))
    if n and unspaced(kept_a[0][0]):      # a token here is one letter, so it takes more of them to mean anything
        return n >= UNSPACED_RESTART_LETTERS and kept_a[:UNSPACED_RESTART_LETTERS] == kept_b[:UNSPACED_RESTART_LETTERS]
    n = min(n, RESTART_WORDS)
    return n >= MIN_RESTART_WORDS and kept_a[:n] == kept_b[:n]


def _union_seconds(spans):
    total, reach = 0.0, None
    for start, end in sorted(spans):
        if reach is None or start > reach:
            total += end - start
            reach = end
        elif end > reach:
            total += end - reach
            reach = end
    return total


def analyse(path, floor=DEFAULT_FLOOR, extra_fillers=()):
    """The decision list as a dict: `cuts` (dead air and retakes) and `review` (filler cues, never counted as cuts)."""
    cues, skipped = load_cues(path)
    extra = {tuple(words(p)) for p in extra_fillers if words(p)}
    duration = max(c[1] for c in cues)
    cuts, filler_cues, filler_lines, counts = [], [], [], {}
    last_speech, reach = None, None
    for start, end, text in cues:
        toks = words(text)
        if reach is not None and start - reach > floor:
            keep = floor / 2.0
            cuts.append({"kind": "dead", "start": round(reach + keep, 3), "end": round(start - keep, 3),
                         "why": "%.2f s gap between spoken lines" % (start - reach)})
        reach = end if reach is None else max(reach, end)
        kept, found = filler_words(toks, extra)
        filler_line = only_filler(toks, extra)
        if filler_line:
            filler_cues.append({"start": start, "end": end, "seconds": round(end - start, 3), "text": clip(text)})
            found = found or [" ".join(toks)]
        elif found:
            filler_lines.append({"start": start, "end": end, "words": found, "text": clip(text)})
        for word in found:
            counts[word] = counts.get(word, 0) + 1
        if filler_line or not toks:
            continue
        if last_speech and _is_restart(last_speech[1], (toks, kept)):
            cuts.append({"kind": "retake", "start": last_speech[0][0], "end": last_speech[0][1],
                         "why": "same opening as the next line: \"%s\"" % clip(last_speech[0][2], 60)})
        last_speech = ((start, end, text), (toks, kept))
    cuts = sorted((c for c in cuts if c["end"] > c["start"]), key=lambda c: c["start"])
    for c in cuts:
        c["seconds"] = round(c["end"] - c["start"], 3)
    removed = _union_seconds((c["start"], c["end"]) for c in cuts)
    return {
        "tool": "edit", "heuristic": True, "source": source_name(path), "cue_count": len(cues),
        "skipped_broken_cues": skipped, "duration_seconds": round(duration, 3), "dead_air_floor_seconds": floor,
        "cuts": cuts, "suggested_cut_seconds": round(removed, 3), "length_after_cuts": round(duration - removed, 3),
        "review": {"filler_cues": filler_cues, "filler_cue_seconds": round(sum(c["seconds"] for c in filler_cues), 3),
                   "filler_words": filler_lines, "counts": dict(sorted(counts.items(), key=lambda x: (-x[1], x[0])))},
        "notes": NOTES,
    }


def render(rep):
    """The report as Markdown."""
    lines = ["# Edit decision list (heuristic)", "",
             "Source: %s, %d lines, %.2f s. Dead-air floor %.2f s." % (rep["source"], rep["cue_count"],
                                                                     rep["duration_seconds"],
                                                                     rep["dead_air_floor_seconds"])]
    if rep["skipped_broken_cues"]:
        lines.append("Skipped %d line(s) with broken timing." % rep["skipped_broken_cues"])
    lines += ["", "## Suggested cuts", ""]
    for c in rep["cuts"]:
        lines.append("- %s %.2f to %.2f (%.2f s): %s" % (c["kind"].upper(), c["start"], c["end"], c["seconds"],
                                                         c["why"]))
    if not rep["cuts"]:
        lines.append("None found.")
    lines += ["", "%d cuts, %.2f s, leaving %.2f s." % (len(rep["cuts"]), rep["suggested_cut_seconds"],
                                                       rep["length_after_cuts"]),
              "", "## Filler cues to review", ""]
    rev = rep["review"]
    for c in rev["filler_cues"]:
        lines.append("- Whole line, %.2f to %.2f (%.2f s): %s" % (c["start"], c["end"], c["seconds"], c["text"]))
    for c in rev["filler_words"]:
        lines.append("- In a line, %.2f to %.2f [%s]: %s" % (c["start"], c["end"], ", ".join(c["words"]), c["text"]))
    if not rev["filler_cues"] and not rev["filler_words"]:
        lines.append("None found.")
    else:
        lines += ["", "Heard: " + ", ".join("%s x%d" % kv for kv in rev["counts"].items()),
                  "Whole filler lines add up to %.2f s, not counted above." % rev["filler_cue_seconds"]]
    lines += ["", "## How to read this", ""] + ["- " + n for n in rep["notes"]]
    return "\n".join(lines) + "\n"
