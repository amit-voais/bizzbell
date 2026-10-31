"""Deterministic checks for the text layers before the screenplay: research sources and claims, humanize fillers."""
import re

from ..gate import check
from .screenplay import norm_words, story_vo_lines

URL = re.compile(r"https?://\S+")
DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")

# Spoken fillers that make Hindi / Hinglish voice-over sound like a person (stages/03-humanize.md).
FILLERS = {
    "hinglish": ("yaar", "matlab", "umm", "um", "haan", "arre", "accha", "achha", "dekho", "suno", "chalo"),
    "hi": ("यार", "मतलब", "उम्म", "हाँ", "हां", "अरे", "अच्छा", "देखो", "सुनो", "चलो"),
}
# "na" / "ना" is a filler only as a tag at the end of a clause ("accha hai na?"); before a verb it means "not"
# ("na jaun") and is not counted.
TAG_NA = re.compile(r"""(?:^|(?<=[\s,.!?…"'(]))(na|ना)\s*(?=[,.!?…;:"')]|$)""", re.I)


def section_lines(text, word):
    """Lines under every Markdown heading that contains `word` (case-insensitive), up to the next heading."""
    out, inside = [], False
    for line in text.splitlines():
        h = re.match(r"^#{1,6}\s+(.*)$", line)
        if h:
            inside = word.lower() in h.group(1).lower()
            continue
        if inside:
            out.append(line)
    return out


def _items(lines):
    return [m.group(1).strip() for m in (re.match(r"^\s*(?:[-*]|\d+[.)])\s+(.+)$", ln) for ln in lines) if m]


@check("sources_dated")
def sources_dated(ctx, file="research.md", section="Sources", min_sources=1):
    """Every item under the Sources heading has an http(s) URL and the date it was read (YYYY-MM-DD)."""
    items = _items(section_lines(ctx.read(file), section))
    if len(items) < min_sources:
        return "no", "%d source item(s) under a '%s' heading; need %d" % (len(items), section, min_sources)
    bad = [it[:60] for it in items if not URL.search(it) or not DATE.search(it)]
    if bad:
        return ("partly" if len(bad) < len(items) else "no"), "no URL or date read: %s" % " | ".join(bad[:4])
    return "yes", "%d sources, each with URL and date read" % len(items)


@check("claims_cited")
def claims_cited(ctx, file="research.md", section="Claims", sources="Sources"):
    """Every claim item cites [S<n>] sources that exist under Sources, or [brief] for facts the user gave."""
    text = ctx.read(file)
    claims = _items(section_lines(text, section))
    if not claims:
        return "no", "no claim items under a '%s' heading" % section
    known = set(re.findall(r"\bS\d+\b", " ".join(_items(section_lines(text, sources)))))
    bad = []
    for c in claims:
        cites = re.findall(r"\[([^\]]+)\]", c)
        ids = [i.strip() for cite in cites for i in cite.split(",")]
        if not ids:
            bad.append("uncited: " + c[:50])
        for i in ids:
            if i.lower() != "brief" and i not in known:
                bad.append("unknown source %s" % i)
    if bad:
        return "no", "; ".join(bad[:5])
    return "yes", "%d claims, each citing a listed source or the brief" % len(claims)


@check("fillers_natural")
def fillers_natural(ctx, file="story_humanized.md", section="Voice-over", min_fillers=2, max_ratio=0.15):
    """Hindi / Hinglish voice-over has real spoken fillers (yaar, matlab, umm, haan, arre, a tag "na?"), at least
    min_fillers and at most max_ratio of the words. Other languages answer yes (their tone is judged by the model)."""
    lang = str(ctx.state.get("lang", "en")).lower()
    key = "hinglish" if lang in ("hinglish", "hi-latn") else ("hi" if lang in ("hi", "hindi") else None)
    if key is None:
        return "yes", "language %s: fillers are judged by the model, not counted" % lang
    lines = story_vo_lines(ctx.read(file), section)
    if not lines:
        return "no", "no spoken lines under a '%s' heading" % section
    spoken = " ".join(lines)
    words = norm_words(spoken)
    fillers = set(FILLERS["hinglish"] + FILLERS["hi"])
    found = [w for w in words if w in fillers] + [m.group(1).lower() for ln in lines for m in TAG_NA.finditer(ln)]
    ratio = float(len(found)) / max(1, len(words))
    if len(found) < min_fillers:
        return "no", "only %d filler(s) (%s) in %d words; a person would say a few" % (
            len(found), ", ".join(found) or "none", len(words))
    if ratio > max_ratio:
        return "partly", "%d fillers in %d words (%.0f%%): overdone" % (len(found), len(words), 100 * ratio)
    return "yes", "%d fillers (%s) in %d words" % (len(found), ", ".join(sorted(set(found))), len(words))


@check("no_stage_directions_in_vo")
def no_stage_directions_in_vo(ctx, file="story_humanized.md", section="Voice-over"):
    """The spoken lines hold only words to be said: no (stage directions) or [notes] inside them."""
    lines = story_vo_lines(ctx.read(file), section)
    if not lines:
        return "no", "no spoken lines under a '%s' heading" % section
    bad = [ln[:60] for ln in lines if re.search(r"\([^)]*\)|\[[^\]]*\]", ln)]
    if bad:
        return "no", "directions inside spoken lines: %s" % " | ".join(bad[:3])
    return "yes", "%d spoken lines, no directions inside them" % len(lines)
