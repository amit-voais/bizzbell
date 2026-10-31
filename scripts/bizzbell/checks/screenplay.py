"""Deterministic checks for screenplay.json (spec section 6.7): per-second rows, shot length, word-for-word VO,
caption length, no text in AI frames, numbers from the research, bibles verbatim, consent for real faces.

The schema is templates/screenplay.json (documented in stages/04-screenplay.md)."""
import os
import re
import unicodedata

from ..gate import check

SCREENPLAY = "screenplay.json"

# Words that ask an image model to draw text or marks. Negated mentions ("no logo", "without text") are allowed.
DRAW_TEXT = ("text", "texts", "logo", "logos", "lettering", "letters", "caption", "captions", "subtitle",
             "subtitles", "watermark", "number plate", "license plate", "licence plate", "signboard", "signage",
             "emblem", "emblems", "insignia", "brand name", "written", "writing", "words", "label", "labels",
             "headline", "slogan", "typography")
NEGATION = r"(?:no|not|never|without|free of|nothing|zero|avoid|none)"


def _doc(ctx, file):
    doc = ctx.json(file)
    if not isinstance(doc, dict):
        raise ValueError("%s is missing or not a JSON object" % file)
    return doc


GROUPS = ("characters", "locations", "props")


def bibles(doc):
    """{id: {"group", "text", "name", "real_person", "photos"}} from screenplay.json "bibles" (grouped as
    characters / locations / props; a value may be the text itself or an object with "text")."""
    out = {}
    raw = doc.get("bibles") or {}
    for g in GROUPS:
        for k, v in (raw.get(g) or {}).items():
            v = v if isinstance(v, dict) else {"text": v}
            out[k] = {"group": g, "text": str(v.get("text") or v.get("bible") or ""), "name": v.get("name") or k,
                      "real_person": bool(v.get("real_person")), "photos": list(v.get("photos") or [])}
    return out


def shot_bible_ids(shot):
    """The bible ids a shot uses, in prompt order: characters, location, props."""
    loc = shot.get("location")
    return list(shot.get("characters") or []) + ([loc] if loc else []) + list(shot.get("props") or [])


def line_start(ln):
    return float(ln.get("at", ln.get("start", -1)))


def _duration(doc):
    d = doc.get("duration")
    if not isinstance(d, (int, float)) or isinstance(d, bool) or d <= 0:
        raise ValueError("duration must be a positive number of seconds")
    return int(round(d))


def norm_words(text):
    """Lower-case words, punctuation and symbols dropped, hyphens split: the unit of the word-for-word checks.
    Works for Devanagari too (vowel signs stay inside their word)."""
    out = []
    for tok in re.split(r"[\s\-‐-―_/]+", (text or "").lower()):
        w = "".join(ch for ch in tok if unicodedata.category(ch)[0] not in "PSZC")
        if w:
            out.append(w)
    return out


def _first_diff(a, b):
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            return i
    return n if len(a) != len(b) else -1


def _ctx_words(words, i):
    return " ".join(words[max(0, i - 3):i + 4]) or "(end)"


@check("rows_cover_every_second")
def rows_cover_every_second(ctx, file=SCREENPLAY):
    """rows[] has exactly one row for every whole second 0 .. duration-1."""
    doc = _doc(ctx, file)
    dur = _duration(doc)
    seen = {}
    for r in doc.get("rows", []):
        t = r.get("t") if isinstance(r, dict) else None
        if not isinstance(t, (int, float)) or isinstance(t, bool) or t != int(t):
            return "no", "a row has no whole-second t: %r" % (r,)
        seen[int(t)] = seen.get(int(t), 0) + 1
    missing = [t for t in range(dur) if t not in seen]
    dupes = [t for t, n in sorted(seen.items()) if n > 1]
    extra = [t for t in sorted(seen) if t < 0 or t >= dur]
    if missing or dupes or extra:
        return "no", "missing seconds %s; duplicated %s; outside 0-%d: %s" % (missing[:20], dupes[:20], dur - 1,
                                                                             extra[:20])
    return "yes", "rows 0-%d present, one each (%d s)" % (dur - 1, dur)


@check("shots_cover_timeline")
def shots_cover_timeline(ctx, file=SCREENPLAY):
    """shots[] run from 0 to duration with no gap or overlap, and every row names the shot playing at its second."""
    doc = _doc(ctx, file)
    dur = _duration(doc)
    shots = sorted(doc.get("shots", []), key=lambda s: s.get("start", 0))
    if not shots:
        return "no", "no shots"
    ids = [s.get("id") for s in shots]
    if len(set(ids)) != len(ids):
        return "no", "duplicate shot ids"
    t, problems = 0.0, []
    for s in shots:
        if abs(float(s.get("start", -1)) - t) > 1e-6:
            problems.append("%s starts at %s, expected %s" % (s.get("id"), s.get("start"), t))
        t = float(s.get("end", t))
    if abs(t - dur) > 1e-6:
        problems.append("shots end at %s, duration is %s" % (t, dur))
    for r in doc.get("rows", []):
        want = [s["id"] for s in shots if float(s["start"]) <= r.get("t", -1) < float(s["end"])]
        if want and r.get("shot") != want[0]:
            problems.append("row t=%s names %s, but %s is playing" % (r.get("t"), r.get("shot"), want[0]))
    if problems:
        return "no", "; ".join(problems[:6])
    return "yes", "%d shots cover 0-%d s; every row names its shot" % (len(shots), dur)


@check("shot_lengths")
def shot_lengths(ctx, file=SCREENPLAY, min_seconds=1, max_seconds=3, graphic_max_seconds=4):
    """Live shots last min..max seconds (1-3); graphic shots at most graphic_max_seconds."""
    doc = _doc(ctx, file)
    bad = []
    for s in doc.get("shots", []):
        length = float(s.get("end", 0)) - float(s.get("start", 0))
        top = graphic_max_seconds if s.get("kind") == "graphic" else max_seconds
        if length < min_seconds or length > top:
            bad.append("%s is %.1f s" % (s.get("id"), length))
    if bad:      # one long shot is enough to break the 1-3 s rule: completeness is not graded
        return "no", "outside %s-%s s: %s" % (min_seconds, max_seconds, ", ".join(bad))
    return "yes", "every live shot is %s-%s s, graphics at most %s s" % (min_seconds, max_seconds,
                                                                      graphic_max_seconds)


def story_vo_lines(text, section="Voice-over"):
    """Spoken lines from the Voice-over section of story_humanized.md ("- L01: words" or "- words")."""
    out, inside = [], False
    for line in text.splitlines():
        h = re.match(r"^#{1,6}\s+(.*)$", line)
        if h:
            inside = section.lower() in h.group(1).lower()
            continue
        if not inside:
            continue
        m = re.match(r"^\s*(?:[-*]\s+|\d+[.)]\s+)?(?:\*\*)?(L\d+)(?:\*\*)?\s*[:.)-]\s*(.+)$", line)
        if m:
            out.append(m.group(2).strip())
            continue
        m = re.match(r"^\s*[-*]\s+(.+)$", line)
        if m:
            out.append(m.group(1).strip())
    return out


@check("vo_word_for_word")
def vo_word_for_word(ctx, file=SCREENPLAY, story="story_humanized.md", section="Voice-over"):
    """lines[].text, in order, says exactly the words of the humanized story's Voice-over (punctuation ignored)."""
    doc = _doc(ctx, file)
    source = story_vo_lines(ctx.read(story), section)
    if not source:
        return "no", "no spoken lines found under a '%s' heading in %s" % (section, story)
    want = norm_words(" ".join(source))
    got = norm_words(" ".join(ln.get("text", "") for ln in doc.get("lines", [])))
    i = _first_diff(want, got)
    if i < 0:
        return "yes", "all %d spoken words match %s word for word" % (len(want), story)
    return "no", "differs at word %d: story has \"%s\", screenplay has \"%s\"" % (i + 1, _ctx_words(want, i),
                                                                                 _ctx_words(got, i))


@check("rows_vo_match_lines")
def rows_vo_match_lines(ctx, file=SCREENPLAY):
    """rows[].vo, read second by second, are the same words as lines[].text, and each second with words has a line
    playing in it."""
    doc = _doc(ctx, file)
    rows = sorted(doc.get("rows", []), key=lambda r: r.get("t", 0))
    lines = doc.get("lines", [])
    want = norm_words(" ".join(ln.get("text", "") for ln in lines))
    got = norm_words(" ".join(r.get("vo", "") for r in rows))
    i = _first_diff(want, got)
    if i >= 0:
        return "no", "rows differ from lines at word %d: lines \"%s\", rows \"%s\"" % (
            i + 1, _ctx_words(want, i), _ctx_words(got, i))
    orphans = [r["t"] for r in rows if norm_words(r.get("vo", "")) and not any(
        line_start(ln) < r["t"] + 1 and float(ln.get("end", 0)) > r["t"] for ln in lines)]
    if orphans:
        return "partly", "words in seconds with no line playing: %s" % orphans[:10]
    return "yes", "rows carry the %d words of lines[] in order" % len(want)


@check("lines_timed")
def lines_timed(ctx, file=SCREENPLAY):
    """Every line has at (start) < end inside 0..duration, lines do not overlap, and every line names a real shot."""
    doc = _doc(ctx, file)
    dur = _duration(doc)
    shot_ids = set(s.get("id") for s in doc.get("shots", []))
    lines = sorted(doc.get("lines", []), key=line_start)
    if not lines:
        return "no", "no lines"
    bad, prev_end = [], 0.0
    for ln in lines:
        a, b = line_start(ln), float(ln.get("end", -1))
        if not (0 <= a < b <= dur):
            bad.append("%s %.1f-%.1f is outside 0-%d" % (ln.get("id"), a, b, dur))
        if a < prev_end - 1e-6:
            bad.append("%s overlaps the line before" % ln.get("id"))
        if ln.get("shot") not in shot_ids:
            bad.append("%s names unknown shot %s" % (ln.get("id"), ln.get("shot")))
        if not str(ln.get("text", "")).strip() or not str(ln.get("tts", "")).strip():
            bad.append("%s needs text and tts" % ln.get("id"))
        prev_end = max(prev_end, b)
    if bad:
        return "no", "; ".join(bad[:6])
    return "yes", "%d lines timed inside 0-%d s, no overlaps" % (len(lines), dur)


@check("captions_short")
def captions_short(ctx, file=SCREENPLAY, max_chars=42):
    """Every caption (rows[].caption) fits in max_chars characters."""
    doc = _doc(ctx, file)
    limit = int((doc.get("captions") or {}).get("max_chars", max_chars))
    long_ = sorted(set(r.get("caption", "") for r in doc.get("rows", []) if len(r.get("caption", "")) > limit))
    if long_:
        return "no", "longer than %d characters: %s" % (limit, " | ".join(c[:60] for c in long_[:4]))
    return "yes", "every caption is %d characters or fewer" % limit


def _asks_for_text(prompt):
    """The text-drawing words a prompt asks for, after removing negated lists ("no print, no logo or writing")."""
    s = " " + prompt.lower() + " "
    t = "(?:%s)" % "|".join(re.escape(w) for w in DRAW_TEXT)
    s = re.sub(r"\b%s\s+(?:\w+[\s,]+){0,4}?%s\b(?:(?:\s*,\s*|\s+(?:or|and|nor)\s+)(?:\w+\s+){0,2}?%s\b)*"
               % (NEGATION, t, t), " ", s)
    return [w for w in DRAW_TEXT if re.search(r"\b%s\b" % re.escape(w), s)]


@check("prompts_no_text")
def prompts_no_text(ctx, file=SCREENPLAY):
    """No live shot's keyframe prompt, motion or bibles asks the model to draw text, a logo, an emblem or a plate."""
    doc = _doc(ctx, file)
    bib = bibles(doc)
    hits = []
    for s in doc.get("shots", []):
        if s.get("kind") != "live":
            continue
        parts = [s.get("keyframe_prompt", ""), s.get("motion", "")] + \
            [(bib.get(b) or {}).get("text", "") for b in shot_bible_ids(s)]
        found = _asks_for_text(" . ".join(parts))
        if found:
            hits.append("%s: %s" % (s.get("id"), ", ".join(found)))
    if hits:
        return "no", "asks for text or marks: " + "; ".join(hits[:6])
    return "yes", "no live shot asks for text, a logo, an emblem or a number plate"


@check("live_shots_complete")
def live_shots_complete(ctx, file=SCREENPLAY):
    """Every live shot has a keyframe prompt, a motion, a camera and at least one character, location or prop that
    exists in the bibles (references first, never a text-only frame)."""
    doc = _doc(ctx, file)
    bib = bibles(doc)
    bad = []
    for s in doc.get("shots", []):
        if s.get("kind") != "live":
            continue
        for k in ("keyframe_prompt", "motion", "camera"):
            if not str(s.get(k, "")).strip():
                bad.append("%s has no %s" % (s.get("id"), k))
        ids = shot_bible_ids(s)
        unknown = [b for b in ids if b not in bib]
        if unknown:
            bad.append("%s names unknown bibles %s" % (s.get("id"), unknown))
        elif not ids:
            bad.append("%s names no character, location or prop" % s.get("id"))
    if bad:
        return "no", "; ".join(bad[:6])
    return "yes", "every live shot has prompt, motion, camera and existing bibles"


GRAPHIC_TEXT = ("title", "subtitle", "number", "label", "cta", "text")


def _on_screen_texts(doc):
    for r in doc.get("rows", []):
        yield "row %s caption" % r.get("t"), r.get("caption", ""), False
    for ln in doc.get("lines", []):
        yield "line %s" % ln.get("id"), ln.get("text", ""), bool(ln.get("sample"))
    for s in doc.get("shots", []):
        g = s.get("graphic") if isinstance(s.get("graphic"), dict) else {}
        for k in GRAPHIC_TEXT:
            vals = g.get(k) if isinstance(g.get(k), list) else [g.get(k)]
            for t in vals:
                if t:
                    yield "shot %s %s" % (s.get("id"), k), str(t), bool(g.get("sample") or s.get("sample"))
        if s.get("overlay"):
            yield "shot %s overlay" % s.get("id"), str(s["overlay"]), bool(s.get("sample"))
    for o in doc.get("overlays", []):
        yield "overlay", o.get("text", ""), bool(o.get("sample"))


@check("numbers_sourced")
def numbers_sourced(ctx, file=SCREENPLAY, sources=("research.md", "brief.md")):
    """Every number shown or captioned appears in research.md / brief.md, or is marked "sample": true / "Sample"."""
    doc = _doc(ctx, file)
    allowed = set()
    for f in sources:
        allowed.update(re.findall(r"\d+(?:[.,]\d+)*", ctx.read(f)))
    bad = []
    for where, text, sample in _on_screen_texts(doc):
        if sample or "sample" in text.lower():
            continue
        for n in re.findall(r"\d+(?:[.,]\d+)*", text):
            if n not in allowed:
                bad.append("%s: %s" % (where, n))
    if bad:
        return "no", "numbers not in %s and not marked Sample: %s" % ("/".join(sources), "; ".join(bad[:8]))
    return "yes", "every number on screen is in %s or marked Sample" % "/".join(sources)


@check("bibles_verbatim")
def bibles_verbatim(ctx, file=SCREENPLAY, md="screenplay.md"):
    """Every bible text in screenplay.json appears word for word in screenplay.md (one bible, two files)."""
    bib = bibles(_doc(ctx, file))
    text = re.sub(r"\s+", " ", ctx.read(md))
    if not bib:
        return "no", "no bibles in %s" % file
    missing = [k for k, b in bib.items() if not b["text"].strip() or re.sub(r"\s+", " ", b["text"]).strip() not in text]
    if missing:
        return "no", "not verbatim in %s: %s" % (md, ", ".join(missing))
    return "yes", "%d bibles verbatim in %s" % (len(bib), md)


@check("bible_blocks_match")
def bible_blocks_match(ctx, file=SCREENPLAY, bible="characters/bible.md"):
    """Every character and location block of screenplay.json appears verbatim in characters/bible.md."""
    doc = _doc(ctx, file)
    text = re.sub(r"\s+", " ", ctx.read(bible))
    if not text.strip():
        return "no", "%s is missing" % bible
    want = {k: b for k, b in bibles(doc).items() if b["group"] in ("characters", "locations")}
    missing = [k for k, b in want.items() if re.sub(r"\s+", " ", b["text"]).strip() not in text]
    if missing:
        return "no", "blocks not verbatim in %s: %s" % (bible, ", ".join(missing))
    return "yes", "%d blocks verbatim in %s" % (len(want), bible)


@check("consent_for_real_faces")
def consent_for_real_faces(ctx, file=SCREENPLAY, consent="CONSENT.md"):
    """A character marked real_person (or with photos) has a CONSENT.md naming them, with the film, channels,
    duration and a date."""
    doc = _doc(ctx, file)
    real = [b["name"] for b in bibles(doc).values()
            if b["group"] == "characters" and (b["real_person"] or b["photos"])]
    if not real:
        return "yes", "no real person: every face is AI-made"
    text = ctx.read(consent)
    if not text.strip():
        return "no", "real person(s) %s but no %s" % (", ".join(real), consent)
    low = text.lower()
    lacks = [n for n in real if n.lower() not in low]
    if lacks:
        return "no", "%s does not name %s" % (consent, ", ".join(lacks))
    need = [k for k in ("film", "channel", "how long") if k not in low]
    if not re.search(r"\d{4}-\d{2}-\d{2}", text):
        need.append("a date (YYYY-MM-DD)")
    if need:
        return "no", "%s lacks: %s" % (consent, ", ".join(need))
    return "yes", "%s names %s with film, channels, duration and date" % (consent, ", ".join(real))


@check("shot_files_exist")
def shot_files_exist(ctx, folder="keyframes", ext=".png", kinds=("live",), file=SCREENPLAY):
    """Every shot of the given kinds has <folder>/<shot id><ext> in the project."""
    doc = _doc(ctx, file)
    want = [s["id"] for s in doc.get("shots", []) if s.get("kind") in kinds]
    missing = [i for i in want if not os.path.isfile(os.path.join(ctx.root, folder, i + ext))]
    if not want:
        return "yes", "no %s shots" % "/".join(kinds)
    if missing:      # a layer with a missing file is not finished: never "partly"
        return "no", "missing %s/<id>%s for %s" % (folder, ext, ", ".join(missing))
    return "yes", "all %d %s shots have %s/<id>%s" % (len(want), "/".join(kinds), folder, ext)
