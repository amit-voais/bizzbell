"""Local gate checks for the media layers (deterministic, ffmpeg only, never a model, never spend).

Registered through scripts/bizzbell/checks/media_pipeline.py. They add to the generic media checks in
checks/media.py (media_aspect, media_duration, audio_loudness, has_audio_stream, no_black_frames, ...) and the
screenplay checks (shot_files_exist, consent_for_real_faces, ...). Use them in rubric questions with "check":

  sheets_cover_cast()                         every character has a sheet, every location a plate
  vo_covers_lines()                           every VO line has a chosen take on the timeline
  vo_fits_shots(tolerance=0.1)                no VO line runs past the end of its shot
  prompts_carry_bibles(file)                  every keyframe prompt carries its shot's bibles verbatim
  prompt_file_no_text(file)                   no prompt in a prompts.json asks for text, a logo or a number plate
  none_flagged(dir)                           no item of a layer is flagged (best take kept after max_takes)
  no_freeze_frames(files, min_dur=1.5)        no frozen picture (Version A: still/card shots are exempt)
  no_long_silence(file, max_silence=1.0)      for the music bed
  captions_roman(file="out/A/captions.ass")   no Devanagari on screen (it belongs in the voice text)
  voice_text_devanagari()                     Hindi/Hinglish: the text sent to the voice is Devanagari
  music_voice_free()                          the chosen bed was judged voice-free on every pass"""
import glob
import os
import re

from ..gate import check
from . import ff, screenplay, store
from .keyframes import bibles_for

NEGATION = re.compile(r"\b(no|not|never|without|nothing|none|avoid|don't|do not|free of)\b", re.I)
TEXT_ASK = re.compile(r"\b(logo|logos|text|caption|captions|subtitle|subtitles|lettering|letters|words|written|"
                      r"reads|reading|number plate|license plate|licence plate|brand name|watermark|signage|"
                      r"emblem|insignia)\b", re.I)


def _files(ctx, files):
    pats = [files] if isinstance(files, str) else list(files or ctx.rubric["layer"]["files"])
    out = []
    for p in pats:
        for h in sorted(glob.glob(os.path.join(ctx.root, p))):
            if os.path.isfile(h) and h not in out:
                out.append(h)
    return out


def _sp(ctx):
    return screenplay.load(ctx.root)


def _ratio(answer_parts, total):
    if not answer_parts:
        return "yes"
    return "partly" if len(answer_parts) < total else "no"


def _all(answer_parts):
    """Completeness checks: every item or nothing ("yes" / "no", never "partly")."""
    return "no" if answer_parts else "yes"


@check("sheets_cover_cast")
def sheets_cover_cast(ctx):
    from .characters import file_for
    sp = _sp(ctx)
    keys = ["sheet:" + c for c in sp.bibles["characters"]] + ["plate:" + l for l in sp.bibles["locations"]]
    if not keys:
        return "yes", "the screenplay has no character or location bibles"
    missing = [k for k in keys if not os.path.exists(os.path.join(ctx.root, file_for(k)))]
    return _all(missing), ("missing: " + ", ".join(missing)) if missing else \
        "all %d sheets/plates present" % len(keys)


def _timing(ctx):
    return ctx.json("audio/vo_timing.json", {}) or {}


@check("vo_covers_lines")
def vo_covers_lines(ctx):
    want = [l["id"] for l in _sp(ctx).lines]
    have = {l["id"] for l in _timing(ctx).get("lines", [])}
    missing = [l for l in want if l not in have]
    if not want:
        return "yes", "the screenplay has no VO lines"
    return _all(missing), ("not on the timeline: " + ", ".join(missing)) if missing else \
        "%d lines placed" % len(want)


@check("vo_fits_shots")
def vo_fits_shots(ctx, tolerance=0.1):
    t = _timing(ctx)
    if not t.get("lines"):
        return "no", "audio/vo_timing.json has no placed lines (bb voice place)"
    over = ["%s +%.2fs" % (l["id"], l["overrun"]) for l in t["lines"] if (l.get("overrun") or 0) > tolerance]
    late = [l["id"] for l in t["lines"] if l["end"] > t.get("duration", 1e9) + 0.01]
    if late:
        return "no", "ends after the film: " + ", ".join(late)
    if over:
        return "partly" if len(over) == 1 else "no", "runs past its shot: " + ", ".join(over)
    return "yes", "every line ends inside its shot"


def _prompts(ctx, file):
    data = ctx.json(file, None)
    if not isinstance(data, dict) or not data:
        raise ValueError("%s is missing or empty" % file)
    return {k: (v if isinstance(v, str) else " ".join(str(x) for x in v.values()) if isinstance(v, dict) else str(v))
            for k, v in data.items()}


@check("prompts_carry_bibles")
def prompts_carry_bibles(ctx, file="keyframes/prompts.json"):
    sp = _sp(ctx)
    prompts = _prompts(ctx, file)
    bad = []
    for s in sp.live_shots():
        p = prompts.get(s["id"])
        if p is None:
            bad.append("%s (no prompt)" % s["id"])
            continue
        lost = [b[:30] for b in bibles_for(sp, s) if b not in p]
        if lost:
            bad.append("%s lacks \"%s...\"" % (s["id"], lost[0]))
    return _ratio(bad, max(1, len(sp.live_shots()))), "; ".join(bad) if bad else \
        "every keyframe prompt carries its bibles verbatim"


@check("prompt_file_no_text")
def prompt_file_no_text(ctx, file="keyframes/prompts.json"):
    hits = []
    for k, p in _prompts(ctx, file).items():
        for sentence in re.split(r"(?<=[.!?;])\s+|\n", p):
            if NEGATION.search(sentence):
                continue
            m = TEXT_ASK.search(sentence)
            if m:
                hits.append("%s: \"%s\"" % (k, sentence.strip()[:80]))
                break
    return ("no" if hits else "yes"), ("; ".join(hits[:5]) if hits else "no prompt asks for text, a logo or a plate")


@check("none_flagged")
def none_flagged(ctx, dir="keyframes"):
    reg = store.load_registry(ctx.root, dir)
    items = {k: v for k, v in reg["items"].items() if not k.startswith("audition:")}
    flagged = [k for k, v in items.items() if v.get("status") == "flagged"]
    if not items:
        return "no", "%s/registry.json has no items yet" % dir
    if flagged:      # no take passed its own judge: the user decides (bb keyframes approve, bb clips pick)
        return "no", ("flagged, no take passed its judge: %s. Show the user; they accept it (bb keyframes approve "
                      "<id> / bb clips pick <id> --take N) or it is made again" % ", ".join(flagged))
    return "yes", "%d items, none flagged" % len(items)


@check("no_freeze_frames")
def no_freeze_frames(ctx, files=None, min_dur=1.5):
    paths = [p for p in _files(ctx, files) if p.endswith((".mp4", ".mov", ".webm"))]
    if not paths:
        return "no", "no video to check"
    static = []
    rep = ctx.json("out/A/version_a.json", {}) or {}
    for s in rep.get("shots", []):
        if s.get("used") != "clip":
            static.append((s["start"], s["start"] + s["dur"]))
    bad = []
    for p in paths:
        spans = ff.freeze_spans(p, min_dur=min_dur)
        if p.startswith(os.path.join(ctx.root, "out")):
            spans = [(a, b) for a, b in spans if not any(a < e - 0.05 and (b or a + min_dur) > s + 0.05
                                                         for s, e in static)]
        if spans:
            bad.append("%s at %s" % (ctx.rel(p), ", ".join("%.2f-%s" % s for s in spans[:3])))
    return _ratio(bad, len(paths)), ("frozen: " + "; ".join(bad)) if bad else "no frozen picture in %d file(s)" % \
        len(paths)


@check("no_long_silence")
def no_long_silence(ctx, file="audio/music_bed.wav", max_silence=1.0, noise_db=-50.0):
    paths = _files(ctx, file)
    if not paths:
        return "no", "%s is missing" % file
    bad = []
    for p in paths:
        d = ff.duration(p)
        spans = [(a, b if b is not None else d) for a, b in ff.silence_spans(p, noise_db, max_silence)]
        spans = [(a, b) for a, b in spans if a > 0.05 and b < d - 0.9]      # fades at the ends are fine
        if spans:
            bad.append("%s at %s" % (ctx.rel(p), ", ".join("%.2f-%.2f" % s for s in spans[:3])))
    return ("no" if bad else "yes"), ("silent: " + "; ".join(bad)) if bad else "no silence longer than %.1fs" % \
        max_silence


@check("captions_roman")
def captions_roman(ctx, file="out/A/captions.ass"):
    text = ctx.read(file)
    if not text:
        caps = " ".join(c[2] for c in _sp(ctx).row_captions()) or " ".join(l["text"] for l in _sp(ctx).lines)
        text = caps
    hits = re.findall(u"[ऀ-ॿ]+", text)
    return ("no", "Devanagari on screen: " + " ".join(hits[:5])) if hits else ("yes", "captions are Roman")


@check("voice_text_devanagari")
def voice_text_devanagari(ctx):
    sp = _sp(ctx)
    if not screenplay.hindi(sp.lang):
        return "yes", "language %s: no Devanagari needed" % sp.lang
    prompts = ctx.json("audio/voice/prompts.json", {}) or {}
    bad = []
    for l in sp.lines:
        p = prompts.get(l["id"])
        tts = (p.get("tts") if isinstance(p, dict) else p) or l["tts"]
        if not screenplay.has_devanagari(tts):
            bad.append(l["id"])
    return _ratio(bad, max(1, len(sp.lines))), ("not Devanagari: " + ", ".join(bad)) if bad else \
        "every voice line is Devanagari"


@check("music_voice_free")
def music_voice_free(ctx):
    it = store.load_registry(ctx.root, os.path.join("audio", "music"))["items"].get("bed", {})
    if not it.get("file"):
        return "no", "no music bed chosen yet"
    vf = it.get("voice_free")
    if vf is True:
        return "yes", "take %s was judged voice-free on every pass" % it.get("take")
    if vf is False:
        return "no", "a judge pass heard a voice in take %s" % it.get("take")
    return "partly", "take %s was not judged for vocals (no per-take judge)" % it.get("take")
