"""Cheap local checks for media layers (spec section 6.3), run before the paid media judge: aspect, duration,
loudness, audio present, black frames, formats. They use ffprobe / ffmpeg and never call a model."""
import glob
import json
import os
import re
import shutil
import subprocess

from ..gate import check

VIDEO = (".mp4", ".mov", ".webm")
AUDIO = (".wav", ".mp3", ".m4a", ".aac")
IMAGE = (".png", ".jpg", ".jpeg", ".webp")
ASPECTS = {"9:16": 9 / 16.0, "16:9": 16 / 9.0, "1:1": 1.0, "4:5": 4 / 5.0}


def tool(name):
    """Path to ffmpeg / ffprobe, or None."""
    p = shutil.which(name)
    if not p and os.path.exists("/opt/homebrew/bin/" + name):
        p = "/opt/homebrew/bin/" + name
    return p


def _need(name):
    p = tool(name)
    if not p:
        raise RuntimeError("%s is not installed (bb doctor prints the install command)" % name)
    return p


def probe(path):
    """{width, height, duration, has_audio, has_video} of a media file (ffprobe)."""
    r = subprocess.run([_need("ffprobe"), "-v", "error", "-show_entries",
                        "stream=codec_type,width,height:format=duration", "-of", "json", path],
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError("ffprobe could not read %s" % os.path.basename(path))
    data = json.loads(r.stdout or "{}")
    streams = data.get("streams", [])
    vid = [s for s in streams if s.get("codec_type") == "video"]
    dur = (data.get("format") or {}).get("duration")
    return {"width": int(vid[0].get("width", 0)) if vid else 0, "height": int(vid[0].get("height", 0)) if vid else 0,
            "duration": float(dur) if dur not in (None, "N/A") else 0.0,
            "has_audio": any(s.get("codec_type") == "audio" for s in streams), "has_video": bool(vid)}


def _files(ctx, files, exts):
    pats = files or ctx.rubric["layer"]["files"]
    pats = [pats] if isinstance(pats, str) else pats
    out = []
    for p in pats:
        for h in sorted(glob.glob(os.path.join(ctx.root, p))):
            if os.path.isfile(h) and h.lower().endswith(exts) and h not in out:
                out.append(h)
    return out


def _screenplay(ctx):
    doc = ctx.json("screenplay.json")
    return doc if isinstance(doc, dict) else {}


def _target_aspect(ctx, path):
    m = re.search(r"(\d+)x(\d+)", os.path.basename(path))
    if m and m.group(1) + ":" + m.group(2) in ASPECTS:
        return m.group(1) + ":" + m.group(2)
    # project.json first, as the generators use it (media/screenplay.load); screenplay.json only as a fallback
    return ctx.state.get("aspect") or _screenplay(ctx).get("aspect") or "9:16"


@check("media_aspect")
def media_aspect(ctx, files=None, tolerance=0.03):
    """Every image / video is in its aspect: the NxM in its file name, else the project's master aspect."""
    paths = _files(ctx, files, VIDEO + IMAGE)
    if not paths:
        return "no", "no image or video files to check"
    bad = []
    for p in paths:
        info = probe(p)
        want = _target_aspect(ctx, p)
        if not info["height"]:
            bad.append("%s has no picture" % ctx.rel(p))
            continue
        got = info["width"] / float(info["height"])
        if abs(got - ASPECTS[want]) / ASPECTS[want] > tolerance:
            bad.append("%s is %dx%d, not %s" % (ctx.rel(p), info["width"], info["height"], want))
    if bad:
        return "no", "; ".join(bad[:5])
    return "yes", "%d file(s) in aspect" % len(paths)


@check("media_duration")
def media_duration(ctx, files=None, seconds=None, tolerance=0.6):
    """Every video / audio file lasts the screenplay's duration (or `seconds`) within `tolerance` seconds."""
    want = float(seconds or _screenplay(ctx).get("duration") or 0)
    if not want:
        return "no", "no duration in screenplay.json"
    paths = _files(ctx, files, VIDEO + AUDIO)
    if not paths:
        return "no", "no video or audio files to check"
    bad = []
    for p in paths:
        d = probe(p)["duration"]
        if abs(d - want) > tolerance:
            bad.append("%s is %.2f s" % (ctx.rel(p), d))
    if bad:
        return "no", "want %.1f s: %s" % (want, "; ".join(bad[:5]))
    return "yes", "%d file(s) last %.1f s (+-%.1f)" % (len(paths), want, tolerance)


@check("shot_media_long_enough")
def shot_media_long_enough(ctx, folder="clips", ext=".mp4", kinds=("live",)):
    """Every shot of `kinds` has <folder>/<id><ext> at least as long as the shot."""
    shots = [s for s in _screenplay(ctx).get("shots", []) if s.get("kind") in kinds]
    if not shots:
        return "yes", "no %s shots" % "/".join(kinds)
    bad = []
    for s in shots:
        p = os.path.join(ctx.root, folder, s["id"] + ext)
        need = float(s.get("end", 0)) - float(s.get("start", 0))
        if not os.path.isfile(p):
            bad.append("%s missing" % s["id"])
        elif probe(p)["duration"] + 0.05 < need:
            bad.append("%s shorter than %.1f s" % (s["id"], need))
    if bad:      # a missing or short clip leaves a hole in the film: never "partly"
        return "no", "; ".join(bad[:6])
    return "yes", "all %d shots have a long enough %s/<id>%s" % (len(shots), folder, ext)


def loudness(path):
    """(integrated LUFS, true peak dBTP), measured with the same ebur128 meter `bb mix` normalises and reports
    with (media/ff.py), so a mix that bb mix calls OK is read the same way by the gate."""
    from ..media import ff
    m = ff.loudness(path)
    if m.get("I") is None or m.get("TP") is None:
        raise RuntimeError("ffmpeg ebur128 gave no reading for %s (silent?)" % os.path.basename(path))
    return float(m["I"]), float(m["TP"])


@check("audio_loudness")
def audio_loudness(ctx, files=None, target=-14.0, tolerance=1.0, max_true_peak=-1.0):
    """Every mix / final file measures target LUFS (+-tolerance) with a true peak at or below max_true_peak."""
    paths = _files(ctx, files, AUDIO + VIDEO)
    if not paths:
        return "no", "no audio to measure"
    bad, seen = [], []
    for p in paths:
        i, tp = loudness(p)
        seen.append("%s %.1f LUFS %.1f dBTP" % (ctx.rel(p), i, tp))
        if abs(i - target) > tolerance or tp > max_true_peak + 0.05:
            bad.append(seen[-1])
    if bad:
        return "no", "want %.0f LUFS, peak <= %.0f dBTP: %s" % (target, max_true_peak, "; ".join(bad[:4]))
    return "yes", "; ".join(seen[:4])


@check("has_audio_stream")
def has_audio_stream(ctx, files=None):
    """Every video file carries an audio track (the VO and music mix)."""
    paths = _files(ctx, files, VIDEO)
    if not paths:
        return "no", "no video files"
    silent = [ctx.rel(p) for p in paths if not probe(p)["has_audio"]]
    if silent:
        return "no", "no audio track: " + ", ".join(silent[:5])
    return "yes", "%d video(s) with audio" % len(paths)


@check("no_black_frames")
def no_black_frames(ctx, files=None, min_seconds=0.5):
    """No video has a black stretch of min_seconds or more (ffmpeg blackdetect)."""
    paths = _files(ctx, files, VIDEO)
    if not paths:
        return "no", "no video files"
    bad = []
    for p in paths:
        r = subprocess.run([_need("ffmpeg"), "-hide_banner", "-nostats", "-i", p, "-vf",
                            "blackdetect=d=%s:pix_th=0.10" % min_seconds, "-an", "-f", "null", "-"],
                           capture_output=True, text=True, timeout=300)
        spans = re.findall(r"black_start:([\d.]+)", r.stderr or "")
        if spans:
            bad.append("%s black from %s s" % (ctx.rel(p), ", ".join(spans[:3])))
    if bad:
        return "no", "; ".join(bad[:4])
    return "yes", "no black stretch of %.1f s in %d video(s)" % (min_seconds, len(paths))


@check("formats_present")
def formats_present(ctx, folders=("out/A", "out/B"), formats=("9x16", "1x1", "16x9"), max_share_mb=25.0):
    """Each folder that has videos holds <slug>_<X>_<format>.mp4 for every format and a _share.mp4 under
    max_share_mb. A folder with no video at all (Version A skipped) is reported, not failed."""
    bad, ok, skipped = [], [], []
    for folder in folders:
        vids = glob.glob(os.path.join(ctx.root, folder, "*.mp4"))
        if not vids:
            skipped.append(folder)
            continue
        names = [os.path.basename(v) for v in vids]
        for f in formats:
            if not [n for n in names if n.endswith("_%s.mp4" % f)]:
                bad.append("%s has no *_%s.mp4" % (folder, f))
        share = [v for v in vids if v.endswith("_share.mp4")]
        if not share:
            bad.append("%s has no *_share.mp4" % folder)
        elif os.path.getsize(share[0]) > max_share_mb * 1024 * 1024:
            bad.append("%s share copy is over %.0f MB" % (folder, max_share_mb))
        ok.append(folder)
    if not ok:
        return "no", "no rendered versions in %s" % ", ".join(folders)
    if bad:
        return "no", "; ".join(bad[:6])
    note = (" (no video in %s)" % ", ".join(skipped)) if skipped else ""
    return "yes", "%s: %s and a share copy%s" % (", ".join(ok), ", ".join(formats), note)
