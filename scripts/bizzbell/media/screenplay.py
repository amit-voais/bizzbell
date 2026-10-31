"""Read screenplay.json into what the media stages need: shots, VO lines, bibles, captions.

The agent writes screenplay.json (stage 4). The reader accepts this shape (every key optional except rows or shots):

  {"duration": 20, "aspect": "9:16", "lang": "hinglish",
   "continuity": ["rule", ...],
   "bibles": {"characters": {"BAKER": "verbatim text" | {"bible": "...", "real_person": false, "photos": [...]}},
              "locations": {"SHOP": "..."}, "props": {"BOX": "..."}},
   "shots": [{"id": "S01", "start": 0, "end": 2, "kind": "live|still|graphic", "keyframe": "what the still shows",
              "motion": "one small action", "camera": "...", "characters": ["BAKER"], "location": "SHOP",
              "props": ["BOX"], "say": "exact spoken line (talking shots)", "image": "refs/product.png"}],
   "rows": [{"t": 0, "shot": "S01", "screen": "...", "image": {"source": "keyframe|reference|graphic",
             "prompt": "...", "ref": "refs/x.png"}, "camera": "...", "motion": "...", "vo": "words this second",
             "vo_tts": "Devanagari for the voice", "caption": "Roman caption", "sfx": "...", "music": "..."}],
   "lines": [{"id": "L01", "shot": "S01", "text": "Roman caption spelling", "tts": "what the voice reads",
              "at": 0.2, "hint": "delivery"}],
   "voice": {"name": "...", "candidates": ["a", "b"], "style": "...", "audition_text": "..."},
   "music": {"prompt": "warm acoustic bed, 92 bpm", "level_db": -14}}

Missing shots are built from rows (grouped by shot id); missing lines are built from the rows' VO words (one line
per run of seconds in the same shot). Bibles may also sit at the top level ("characters", "locations", "props")
as objects or lists of {id, bible|text|description}."""
import os
import re

from .. import project, util
from ..errors import UsageError

KINDS = ("live", "still", "graphic")
DEVANAGARI = re.compile(u"[ऀ-ॿ]")


def _num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _bible_group(raw):
    """{id: {"id", "text", "name", "real_person", "photos"}} from a dict or a list."""
    out = {}
    if isinstance(raw, dict):
        items = []
        for k, v in raw.items():
            if isinstance(v, dict):
                items.append(dict(v, id=v.get("id", k)))
            else:
                items.append({"id": k, "bible": v})
    elif isinstance(raw, list):
        items = [x for x in raw if isinstance(x, dict)]
    else:
        items = []
    for it in items:
        bid = str(it.get("id") or it.get("name") or "").strip()
        if not bid:
            continue
        text = it.get("bible") or it.get("text") or it.get("description") or ""
        out[bid] = {"id": bid, "text": str(text).strip(), "name": str(it.get("name") or bid),
                    "real_person": bool(it.get("real_person")), "photos": list(it.get("photos") or []),
                    "refs": list(it.get("refs") or [])}
    return out


class Screenplay(object):
    """A normalised screenplay. Attributes: data, duration, aspect, lang, rows, shots, lines, bibles, continuity."""

    def __init__(self, data, aspect=None, lang=None):
        if not isinstance(data, dict):
            raise UsageError("screenplay.json must be a JSON object")
        self.data = data
        self.aspect = aspect or data.get("aspect") or "9:16"
        self.lang = (lang or data.get("lang") or "en").lower()
        self.rows = sorted([r for r in data.get("rows", []) if isinstance(r, dict)], key=lambda r: _num(r.get("t")))
        b = data.get("bibles") or {}
        self.bibles = {
            "characters": _bible_group(b.get("characters", data.get("characters"))),
            "locations": _bible_group(b.get("locations", data.get("locations"))),
            "props": _bible_group(b.get("props", data.get("props"))),
        }
        cont = data.get("continuity") or []
        self.continuity = [cont] if isinstance(cont, str) else [str(c) for c in cont]
        self.shots = self._shots()
        if not self.shots:
            raise UsageError("screenplay.json has no shots and no rows")
        dur = _num(data.get("duration"), 0.0)
        if not dur:
            dur = max([s["end"] for s in self.shots] + [_num(r.get("t")) + 1 for r in self.rows])
        self.duration = round(dur, 3)
        self.lines = self._lines()

    # -- shots
    def _shots(self):
        by_id = {}
        order = []
        for r in self.rows:
            sid = str(r.get("shot") or r.get("shot_id") or "").strip()
            if not sid:
                continue
            if sid not in by_id:
                by_id[sid] = []
                order.append(sid)
            by_id[sid].append(r)
        given = [s for s in self.data.get("shots", []) if isinstance(s, dict) and s.get("id")]
        shots = []
        if given:
            for s in given:
                shots.append(self._shot(dict(s), by_id.get(str(s["id"]), [])))
        else:
            for sid in order:
                shots.append(self._shot({"id": sid}, by_id[sid]))
        shots.sort(key=lambda s: s["start"])
        return shots

    def _shot(self, s, rows):
        sid = str(s["id"])
        img = {}
        for r in rows:
            if isinstance(r.get("image"), dict):
                img = r["image"]
                break
            if isinstance(r.get("image"), str) and r["image"].strip():
                img = {"prompt": r["image"]}
                break
        ts = [_num(r.get("t")) for r in rows]
        start = _num(s.get("start"), min(ts) if ts else 0.0)
        end = _num(s.get("end"), (max(ts) + 1) if ts else start + 2)
        kind = s.get("kind")
        if not kind:
            src = str(img.get("source", "keyframe")).lower()
            kind = "graphic" if src.startswith("graph") else "still" if src in ("reference", "ref", "still",
                                                                               "photo") else "live"
        kind = kind if kind in KINDS else "live"

        def first(*keys):
            for k in keys:
                if s.get(k):
                    return str(s[k]).strip()
            for r in rows:
                for k in keys:
                    if r.get(k) and isinstance(r[k], str):
                        return r[k].strip()
            return ""
        keyframe = first("keyframe", "kf", "keyframe_prompt") or str(img.get("prompt") or "").strip() or \
            first("screen", "on_screen")
        motion = first("motion")
        text_for_cast = " ".join([keyframe, first("screen", "on_screen"), motion])
        chars = s.get("characters")
        if chars is None:
            chars = self._mentioned("characters", text_for_cast)
        loc = s.get("location")
        if loc is None:
            hits = self._mentioned("locations", text_for_cast)
            loc = hits[0] if hits else None
        props = s.get("props")
        if props is None:
            props = self._mentioned("props", text_for_cast)
        image = s.get("image") if isinstance(s.get("image"), str) else (img.get("ref") or img.get("path") or "")
        return {"id": sid, "start": round(start, 3), "end": round(end, 3), "kind": kind, "keyframe": keyframe,
                "motion": motion, "camera": first("camera"), "characters": [str(c) for c in chars or []],
                "location": loc, "props": [str(p) for p in props or []], "say": str(s.get("say") or ""),
                "image": image or "", "refs": list(s.get("refs") or []), "rows": rows,
                "lines": [str(x) for x in s.get("lines") or []],
                "card": s.get("graphic") if isinstance(s.get("graphic"), dict) else {},
                "graphic": s.get("desc") or first("screen", "on_screen")}

    def _mentioned(self, group, text):
        low = (text or "").lower()
        out = []
        for bid, b in self.bibles[group].items():
            for name in {bid, b["name"]}:
                if name and re.search(r"(?<!\w)%s(?!\w)" % re.escape(name.lower()), low):
                    out.append(bid)
                    break
        return out

    def shot(self, sid):
        for s in self.shots:
            if s["id"] == sid:
                return s
        raise UsageError("no shot %r in screenplay.json (shots: %s)" % (sid, ", ".join(x["id"] for x in self.shots)))

    def live_shots(self):
        return [s for s in self.shots if s["kind"] == "live"]

    def slot(self, sid):
        """(start, end) a shot fills on the timeline: up to the next shot's start (the last one: the end)."""
        idx = [s["id"] for s in self.shots].index(sid)
        s = self.shots[idx]
        end = self.shots[idx + 1]["start"] if idx + 1 < len(self.shots) else self.duration
        return s["start"], max(s["start"] + 0.1, end)

    # -- lines
    def _lines(self):
        given = [l for l in self.data.get("lines", []) if isinstance(l, dict)]
        out = []
        if given:
            for i, l in enumerate(given):
                text = str(l.get("text") or l.get("caption") or l.get("vo") or "").strip()
                if not text and not l.get("tts"):
                    continue
                out.append({"id": str(l.get("id") or "L%02d" % (i + 1)), "shot": l.get("shot"), "text": text,
                            "tts": str(l.get("tts") or text).strip(), "at": l.get("at", l.get("start")),
                            "end": l.get("end"), "hint": str(l.get("hint") or "")})
            return out
        cur = None
        for r in self.rows:
            vo = str(r.get("vo") or "").strip()
            sid = r.get("shot")
            if not vo:
                cur = None
                continue
            if cur and cur["shot"] == sid:
                cur["text"] += " " + vo
                cur["tts"] += " " + str(r.get("vo_tts") or r.get("tts") or vo).strip()
                continue
            cur = {"id": "L%02d" % (len(out) + 1), "shot": sid, "text": vo,
                   "tts": str(r.get("vo_tts") or r.get("tts") or vo).strip(), "at": _num(r.get("t")), "end": None,
                   "hint": ""}
            out.append(cur)
        return out

    def line_slot_end(self, l):
        """When a line must be over: its own "end", else the end of the last shot that lists it, else its shot's."""
        if l.get("end") is not None:
            return _num(l["end"])
        ends = [self.slot(s["id"])[1] for s in self.shots if l["id"] in s["lines"]]
        if ends:
            return max(ends)
        if l.get("shot"):
            try:
                return self.slot(l["shot"])[1]
            except (UsageError, ValueError):
                return None
        return None

    def line(self, lid):
        for l in self.lines:
            if l["id"] == lid:
                return l
        raise UsageError("no VO line %r (lines: %s)" % (lid, ", ".join(x["id"] for x in self.lines)))

    # -- captions + text
    def row_captions(self):
        """[(start, end, text)] from the rows' caption column (consecutive equal captions merged)."""
        out = []
        for r in self.rows:
            cap = str(r.get("caption") or "").strip()
            t = _num(r.get("t"))
            if out and cap and out[-1][2] == cap and abs(out[-1][1] - t) < 1e-6:
                out[-1] = (out[-1][0], t + 1, cap)
            elif cap:
                out.append((t, t + 1, cap))
        return [(a, min(b, self.duration), c) for a, b, c in out]

    def rows_text(self, sid):
        """The screenplay rows of a shot as compact text (for judge notes)."""
        s = self.shot(sid)
        parts = ["Shot %s (%s, %.1f-%.1f s)." % (sid, s["kind"], s["start"], s["end"])]
        for k in ("keyframe", "motion", "camera", "say"):
            if s.get(k):
                parts.append("%s: %s" % (k, s[k]))
        for r in s["rows"]:
            bits = ["t=%s" % r.get("t")]
            for k in ("screen", "on_screen", "vo", "caption", "sfx"):
                if r.get(k):
                    bits.append("%s: %s" % (k, r[k]))
            parts.append("; ".join(bits))
        return "\n".join(parts)

    def voice(self):
        return dict(self.data.get("voice") or {})

    def music(self):
        m = self.data.get("music")
        if isinstance(m, str):
            return {"prompt": m}
        m = dict(m or {})
        if not m.get("prompt"):
            cues = []
            for r in self.rows:
                c = str(r.get("music") or "").strip()
                if c and c not in cues:
                    cues.append(c)
            if cues:
                m["prompt"] = "; ".join(cues)
        return m


def load(root):
    """The project's screenplay.json as a Screenplay (aspect and language from project.json)."""
    p = os.path.join(root, "screenplay.json")
    if not os.path.exists(p):
        raise UsageError("screenplay.json is missing: write and gate the screenplay first (bb gate screenplay)")
    try:
        data = util.read_json(p)
    except ValueError as e:
        raise UsageError("screenplay.json is not valid JSON: %s" % e)
    st = project.load_state(root)
    return Screenplay(data, aspect=st.get("aspect"), lang=st.get("lang"))


def has_devanagari(text):
    return bool(DEVANAGARI.search(text or ""))


def hindi(lang):
    return (lang or "").lower() in ("hi", "hindi", "hinglish", "hi-en", "hi_en")
