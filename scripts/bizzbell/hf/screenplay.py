"""screenplay.json (+ audio/words.json) -> the plan Version B is built from. Tolerant of field names.

Read from screenplay.json (all optional except some timing):
  duration, fps, title
  shots: [{id, start, end | duration, kind ("image"|"graphic"|"card"|"number"|"endcard"), image | keyframe,
           camera | motion, overlay, captions (false = none over this shot), sample,
           graphic: {type, title, subtitle, number, label, cta, icon, sample}}]
  rows:  [{t, shot, caption, vo, ...}]   one row per second; used for shot spans when "shots" is missing and
                                          for caption timing when there is no audio/words.json
  lines: [{id, shot, at, end, text}]      the VO lines ("text" = the Roman caption spelling)
  overlays: [{start, end | shot, text}]  extra on-screen words (shown as a chip at the top of the safe zone)
Caption words, first source found: audio/words.json ([{word, start, end}], Roman only); audio/vo_timing.json
(the placed VO lines, {lines: [{start, end, text}]}); the rows' "caption" column; the screenplay's "lines"
(at/end); the rows' "vo". Line-level text is spread over its span, longer words getting more time.
Audio: audio/mix.wav (already mixed) wins; else audio/vo*.wav plus audio/music*.wav (music_bed.wav)."""
import glob
import os
import re

from .. import util
from . import icons
from ..errors import UsageError

IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp")
DEVANAGARI = re.compile(u"[\u0900-\u097F]")
GRAPHIC_KINDS = {"graphic": "card", "card": "card", "title": "card", "text": "card", "number": "number",
                 "stat": "number", "endcard": "endcard", "end_card": "endcard", "end": "endcard", "cta": "endcard"}
CAMERAS = (("push", ("push", "zoom in", "dolly in", "slow in", "move in")),
           ("pull", ("pull", "zoom out", "dolly out", "move out", "reveal")),
           ("pan_left", ("pan left", "pans left", "move left", "truck left", "slide left", "track left")),
           ("pan_right", ("pan right", "pans right", "move right", "truck right", "slide right", "track right")),
           ("tilt_up", ("tilt up", "tilts up", "crane up", "rise")),
           ("tilt_down", ("tilt down", "tilts down", "crane down")),
           ("still", ("static", "locked", "still", "hold", "fixed")))
DEFAULT_MOVES = ("push", "pan_right", "pull", "pan_left")


def _num(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _first(d, keys, default=None):
    for k in keys:
        v = d.get(k)
        if v not in (None, "", []):
            return v
    return default


def _row_time(row):
    return _num(_first(row, ("t", "second", "time", "start", "at")), None)


def camera_move(text, index=0):
    """A camera/motion description -> one of push, pull, pan_left, pan_right, tilt_up, tilt_down, still."""
    t = str(text or "").lower()
    for move, words in CAMERAS:
        if any(w in t for w in words):
            return move
    return DEFAULT_MOVES[index % len(DEFAULT_MOVES)]


def _image_for(root, shot):
    for k in ("image", "keyframe", "still", "src", "source", "frame", "sheet"):
        v = shot.get(k)
        if isinstance(v, str) and v.lower().endswith(IMAGE_EXT):
            p = v if os.path.isabs(v) else os.path.join(root, v)
            if os.path.isfile(p):
                return os.path.abspath(p)
    sid = str(shot.get("id", ""))
    for ext in IMAGE_EXT:
        p = os.path.join(root, "keyframes", sid + ext)
        if sid and os.path.isfile(p):
            return p
    return None


def _graphic(shot, kind):
    g = shot.get("graphic") if isinstance(shot.get("graphic"), dict) else {}
    src = dict(shot)
    src.update(g)
    gtype = GRAPHIC_KINDS.get(str(g.get("type", "")).lower()) or GRAPHIC_KINDS.get(kind, "card")
    return {
        "type": gtype,
        "title": str(_first(src, ("title", "headline", "heading", "text", "line"), "")),
        "subtitle": str(_first(src, ("subtitle", "sub", "body", "line2", "support"), "")),
        "number": str(_first(src, ("number", "stat", "value", "figure"), "")),
        "label": str(_first(src, ("label", "unit", "caption_small"), "")),
        "cta": str(_first(src, ("cta", "button", "call_to_action"), "")),
        "icon": str(_first(src, ("icon",), "")),
        "sample": bool(src.get("sample", False)),
    }


def _shots_from_rows(rows):
    """Group consecutive rows by their shot id: [{id, start, end, ...first row fields}]."""
    out = []
    for r in sorted((r for r in rows if _row_time(r) is not None), key=_row_time):
        t = _row_time(r)
        end = _num(r.get("end"), None) or t + (_num(r.get("duration"), 1.0) or 1.0)
        sid = str(_first(r, ("shot", "shot_id", "id"), "S%02d" % (len(out) + 1)))
        if out and out[-1]["id"] == sid:
            out[-1]["end"] = max(out[-1]["end"], end)
            continue
        s = {k: v for k, v in r.items() if k not in ("t", "second", "time", "start", "at", "end", "duration")}
        s.update({"id": sid, "start": t, "end": end})
        out.append(s)
    return out


def _segments_from_rows(rows, keys):
    """Consecutive rows with the same text -> [(start, end, text)]."""
    segs = []
    for r in sorted((r for r in rows if _row_time(r) is not None), key=_row_time):
        t = _row_time(r)
        end = _num(r.get("end"), None) or t + (_num(r.get("duration"), 1.0) or 1.0)
        text = str(_first(r, keys, "") or "").strip()
        if not text:
            continue
        if segs and segs[-1][2] == text and abs(segs[-1][1] - t) < 1e-6:
            segs[-1][1] = end
        else:
            segs.append([t, end, text])
    return [tuple(s) for s in segs]


def spread_words(start, end, text, line=0):
    """Time the words of `text` across [start, end): longer words get more time; the last 15 % holds."""
    words = text.split()
    if not words:
        return []
    span = max(0.2, (end - start) * 0.85)
    weights = [len(w) + 2 for w in words]
    total = float(sum(weights))
    out, t = [], start
    for w, wt in zip(words, weights):
        d = span * wt / total
        out.append({"text": w, "start": round(t, 3), "end": round(t + d, 3), "line": line})
        t += d
    return out


def _words_file(root):
    data = util.read_json(os.path.join(root, "audio", "words.json"), None)
    if isinstance(data, dict):
        data = data.get("words")
    if not isinstance(data, list):
        return None
    out = []
    for w in data:
        if not isinstance(w, dict):
            continue
        text = str(_first(w, ("word", "text"), "")).strip()
        s, e = _num(w.get("start")), _num(w.get("end"))
        if text and s is not None:
            out.append({"text": text, "start": s, "end": e if e is not None else s + 0.3,
                        "line": w.get("line", 0)})
    return out or None


def _audio(root):
    def pick(patterns):
        for pat in patterns:
            hits = sorted(glob.glob(os.path.join(root, "audio", pat)))
            if hits:
                return hits[0]
        return None
    mix = pick(["mix.wav", "final.wav", "mix*.wav"])
    if mix:
        return {"mix": mix, "vo": None, "music": None}
    return {"mix": None, "vo": pick(["vo.wav", "voice.wav", "vo*.wav", "voice*.wav"]),
            "music": pick(["music.wav", "bed.wav", "music*.wav"])}


def _caption_segments(root, sp, rows, shots, raw):
    """(source name, [(start, end, text)]) from the first caption source that has any text."""
    timing = util.read_json(os.path.join(root, "audio", "vo_timing.json"), {}) or {}
    segs = [(_num(l.get("start"), 0.0), _num(l.get("end"), 0.0), str(l.get("text") or "").strip())
            for l in (timing.get("lines") or []) if isinstance(l, dict)]
    segs = [x for x in segs if x[2] and x[1] > x[0]]
    if segs:
        return "audio/vo_timing.json", segs
    segs = _segments_from_rows(rows, ("caption", "captions", "on_screen_caption"))
    if segs:
        return "screenplay rows (caption)", segs
    slots = {s["id"]: (s["start"], s["end"]) for s in shots}
    segs = []
    for l in (sp.get("lines") or []):
        if not isinstance(l, dict) or not str(l.get("text") or "").strip():
            continue
        a = _num(_first(l, ("at", "start")), None)
        slot = slots.get(str(l.get("shot", "")))
        if a is None and slot:
            a = slot[0] + 0.15
        if a is None:
            continue
        b = _num(l.get("end"), None) or (slot[1] if slot else a + 2.0)
        if b > a:
            segs.append((a, b, str(l["text"]).strip()))
    if segs:
        return "screenplay lines", sorted(segs)
    segs = _segments_from_rows(rows, ("vo", "voice", "voiceover", "vo_words", "spoken"))
    if segs:
        return "screenplay rows (vo)", segs
    segs = [(s["start"], s["end"], str(_first(r, ("caption", "vo"), ""))) for s, r in zip(shots, raw)
            if isinstance(_first(r, ("caption", "vo"), ""), str) and _first(r, ("caption", "vo"), "")]
    return "screenplay shots", segs


def _overlays(sp, shots):
    slots = {s["id"]: (s["start"], s["end"]) for s in shots}
    out = []
    for i, o in enumerate(sp.get("overlays") or []):
        if not isinstance(o, dict) or not str(o.get("text") or "").strip():
            continue
        slot = slots.get(str(o.get("shot", "")), (None, None))
        a = _num(_first(o, ("start", "at")), slot[0])
        b = _num(o.get("end"), slot[1])
        if a is None or b is None or b <= a:
            continue
        out.append({"id": "ov%02d" % (i + 1), "start": round(a, 3), "end": round(b, 3),
                    "text": str(o["text"]).strip()})
    return out


def load(root):
    """The normalised plan for Version B. Raises UsageError when screenplay.json is missing or has no timing."""
    path = os.path.join(root, "screenplay.json")
    try:
        sp = util.read_json(path, None)
    except ValueError as e:
        raise UsageError("screenplay.json is not valid JSON: %s" % e)
    if not isinstance(sp, dict):
        raise UsageError("screenplay.json is missing: Version B is built from it (stage 4)")
    rows = [r for r in (sp.get("rows") or sp.get("seconds") or sp.get("timeline") or []) if isinstance(r, dict)]
    raw = [s for s in (sp.get("shots") or []) if isinstance(s, dict)] or _shots_from_rows(rows)
    if not raw:
        raise UsageError("screenplay.json has no shots and no rows with times")
    warnings, shots, t = [], [], 0.0
    for i, s in enumerate(raw):
        start = _num(s.get("start"), t)
        end = _num(s.get("end"), None)
        if end is None:
            end = start + (_num(s.get("duration"), None) or 2.0)
        if end <= start:
            raise UsageError("shot %s ends before it starts" % s.get("id", i + 1))
        t = end
        kind = str(_first(s, ("kind", "type"), "image")).lower()
        sid = re.sub(r"[^A-Za-z0-9_-]", "", str(s.get("id", "S%02d" % (i + 1)))) or "S%02d" % (i + 1)
        is_graphic = kind in GRAPHIC_KINDS or isinstance(s.get("graphic"), dict)
        shot = {"id": sid, "start": round(start, 3), "end": round(end, 3),
                "kind": "graphic" if is_graphic else "image", "image": None, "graphic": None,
                "camera": camera_move(_first(s, ("camera", "motion", "move"), ""), i),
                "overlay": str(_first(s, ("overlay", "on_screen_text"), "") or ""),
                "captions": s.get("captions", True) is not False, "sample": bool(s.get("sample", False))}
        if is_graphic:
            shot["graphic"] = _graphic(s, kind)
            for name in icons.unknown([shot["graphic"]["icon"]]):
                warnings.append("shot %s asks for the icon \"%s\", which does not exist; it shows no icon" % (sid, name))
            shot["image"] = _image_for(root, s) if any(isinstance(s.get(k), str) for k in ("image", "keyframe")) \
                else None
            if shot["graphic"]["type"] == "endcard":
                shot["captions"] = s.get("captions", False) is True
        else:
            shot["image"] = _image_for(root, dict(s, id=sid))
            if not shot["image"]:
                warnings.append("shot %s has no keyframe image (looked for keyframes/%s.png); a plain backdrop "
                                "stands in" % (sid, sid))
        shots.append(shot)
    shots.sort(key=lambda x: x["start"])
    duration = _num(sp.get("duration"), None) or max(s["end"] for s in shots)
    duration = round(max(duration, max(s["end"] for s in shots)), 3)

    words, source = _words_file(root), "audio/words.json"
    if words and any(DEVANAGARI.search(w["text"]) for w in words):
        words = None                      # word timings of the Devanagari voice text: captions stay Roman
    if not words:
        source, segs = _caption_segments(root, sp, rows, shots, raw)
        words = [w for i, seg in enumerate(segs) for w in spread_words(seg[0], seg[1], seg[2], i)]
    no_caps = [(s["start"], s["end"]) for s in shots if not s["captions"]]
    words = [w for w in words if w["start"] < duration and not any(a <= w["start"] < b for a, b in no_caps)]
    for w in words:
        w["end"] = round(min(w["end"], duration), 3)
    return {"title": str(sp.get("title", "")), "duration": duration, "fps": int(_num(sp.get("fps"), 30) or 30),
            "shots": shots, "words": words, "caption_source": source if words else "none",
            "overlays": [o for o in _overlays(sp, shots) if o["start"] < duration],
            "audio": _audio(root), "warnings": warnings}


def chunk(words, max_words=3, max_chars=18):
    """Caption chunks: [{start, end, words:[{text, start, end}]}]. A chunk breaks at a new line, at , . ? ! or a
    pause > 0.35 s,
    after max_words words, or before max_chars characters. A chunk stays on until the next one starts
    (or 0.5 s after its last word)."""
    chunks, cur = [], []
    for i, w in enumerate(words):
        if cur:
            txt = " ".join(x["text"] for x in cur + [w])
            gap = w["start"] - cur[-1]["end"]
            if len(cur) >= max_words or len(txt) > max_chars or gap > 0.35 or \
                    w.get("line", 0) != cur[-1].get("line", 0):
                chunks.append(cur)
                cur = []
        cur.append(w)
        if re.search(r"([,.?!।]|\.\.\.)$", w["text"]):
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    out = []
    for k, c in enumerate(chunks):
        start = c[0]["start"]
        nxt = chunks[k + 1][0]["start"] if k + 1 < len(chunks) else None
        end = c[-1]["end"] + 0.5
        if nxt is not None:
            end = min(end, nxt) if nxt - c[-1]["end"] > 0.5 else nxt
        out.append({"start": round(start, 3), "end": round(max(end, start + 0.2), 3), "words": c})
    return out
