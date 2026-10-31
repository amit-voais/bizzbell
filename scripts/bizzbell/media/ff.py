"""ffmpeg / ffprobe helpers. No API calls, no network; every function shells out to the system ffmpeg.

probe(path)                    -> {duration, width, height, fps, has_video, has_audio}
black_spans / freeze_spans / silence_spans(path, ...) -> [(start, end)]
loudness(path)                 -> {"I": LUFS, "TP": dBTP, "LRA": LU}   (ebur128, true peak)
loudnorm(src, dst, ...)        two-pass EBU R128 normalisation, then verified
master_size(aspect)            (w, h) of the master for an aspect ("9:16" -> 1080x1920)"""
import json
import os
import re
import shutil
import subprocess

from ..errors import BBError

SIZES = {"9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1080, 1080), "4:5": (1080, 1350)}
ASPECT_TAG = {"9:16": "9x16", "16:9": "16x9", "1:1": "1x1", "4:5": "4x5"}
_FILTERS = {}


def _tool(name):
    p = shutil.which(name)
    if p:
        return p
    for d in ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"):
        if os.path.exists(os.path.join(d, name)):
            return os.path.join(d, name)
    raise BBError("%s is not installed. Install it (macOS: brew install ffmpeg; Debian/Ubuntu: sudo apt-get "
                  "install ffmpeg) and run python3 scripts/bb.py doctor." % name)


def ffmpeg():
    return _tool("ffmpeg")


def ffprobe():
    return _tool("ffprobe")


def run(args, cwd=None, timeout=900):
    """Run ffmpeg with `args` (without the program name). Returns stderr text. Raises BBError on failure."""
    cmd = [ffmpeg(), "-hide_banner", "-nostdin", "-y"] + list(args)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise BBError("ffmpeg took longer than %ds and was stopped" % timeout)
    if r.returncode != 0:
        tail = "\n".join((r.stderr or "").strip().splitlines()[-6:])
        raise BBError("ffmpeg failed: %s" % tail[-800:])
    return r.stderr or ""


def has_filter(name):
    """True when this ffmpeg build has the filter (subtitles needs libass, drawtext needs freetype)."""
    if os.environ.get("BB_NO_%s" % name.upper()):
        return False
    if name not in _FILTERS:
        try:
            out = subprocess.run([ffmpeg(), "-hide_banner", "-filters"], capture_output=True, text=True,
                                 timeout=60).stdout
        except (OSError, subprocess.TimeoutExpired):
            out = ""
        _FILTERS[name] = bool(re.search(r"^\s*\S+\s+%s\s" % re.escape(name), out, re.M))
    return _FILTERS[name]


def amix_normalize_supported():
    if "amix:normalize" not in _FILTERS:
        try:
            out = subprocess.run([ffmpeg(), "-hide_banner", "-h", "filter=amix"], capture_output=True, text=True,
                                 timeout=60).stdout
        except (OSError, subprocess.TimeoutExpired):
            out = ""
        _FILTERS["amix:normalize"] = "normalize" in out
    return _FILTERS["amix:normalize"]


def amix(n, duration="first"):
    """An amix filter for n inputs that does not scale the inputs down."""
    if amix_normalize_supported():
        return "amix=inputs=%d:duration=%s:dropout_transition=0:normalize=0" % (n, duration)
    return "amix=inputs=%d:duration=%s:dropout_transition=0,volume=%d" % (n, duration, n)


# ---------------------------------------------------------------- probing
def probe(path):
    """Basic facts of a media file. Raises BBError when ffprobe cannot read it."""
    if not os.path.exists(path):
        raise BBError("no such file: %s" % path)
    r = subprocess.run([ffprobe(), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise BBError("ffprobe cannot read %s: %s" % (os.path.basename(path), (r.stderr or "").strip()[-300:]))
    d = json.loads(r.stdout or "{}")
    out = {"duration": 0.0, "width": 0, "height": 0, "fps": 0.0, "has_video": False, "has_audio": False}
    try:
        out["duration"] = float(d.get("format", {}).get("duration") or 0)
    except ValueError:
        pass
    for s in d.get("streams", []):
        if s.get("codec_type") == "video" and not out["has_video"]:
            out["has_video"] = True
            out["width"], out["height"] = int(s.get("width") or 0), int(s.get("height") or 0)
            num, _, den = str(s.get("avg_frame_rate") or s.get("r_frame_rate") or "0/1").partition("/")
            try:
                out["fps"] = round(float(num) / float(den or 1), 3) if float(den or 1) else 0.0
            except ValueError:
                pass
            if not out["duration"]:
                try:
                    out["duration"] = float(s.get("duration") or 0)
                except ValueError:
                    pass
        elif s.get("codec_type") == "audio":
            out["has_audio"] = True
            if not out["duration"]:
                try:
                    out["duration"] = float(s.get("duration") or 0)
                except ValueError:
                    pass
    return out


def duration(path):
    return probe(path)["duration"]


def _window(start, dur):
    a = []
    if start:
        a += ["-ss", "%.3f" % start]
    return a, (["-t", "%.3f" % dur] if dur else [])


def _spans(text, start_key, end_key, offset=0.0):
    starts = [float(x) for x in re.findall(r"%s[:=]\s*(-?[\d.]+)" % start_key, text)]
    ends = [float(x) for x in re.findall(r"%s[:=]\s*(-?[\d.]+)" % end_key, text)]
    out = []
    for i, s in enumerate(starts):
        e = ends[i] if i < len(ends) else None
        out.append((round(s + offset, 3), round(e + offset, 3) if e is not None else None))
    return out


def black_spans(path, start=0.0, dur=None, min_dur=0.2, pix_th=0.10):
    """[(start, end)] of (almost) black stretches at least `min_dur` long, in file time."""
    pre, post = _window(start, dur)
    err = run(pre + ["-i", path] + post + ["-an", "-vf", "blackdetect=d=%.2f:pix_th=%.2f" % (min_dur, pix_th),
                                           "-f", "null", "-"])
    return _spans(err, "black_start", "black_end", start)


def freeze_spans(path, start=0.0, dur=None, min_dur=1.0, noise=0.003):
    """[(start, end)] where the picture does not change for at least `min_dur` seconds, in file time."""
    pre, post = _window(start, dur)
    err = run(pre + ["-i", path] + post + ["-an", "-vf", "freezedetect=n=%g:d=%.2f" % (noise, min_dur),
                                           "-f", "null", "-"])
    starts = [float(x) for x in re.findall(r"freeze_start:\s*([\d.]+)", err)]
    ends = [float(x) for x in re.findall(r"freeze_end:\s*([\d.]+)", err)]
    out = []
    for i, s in enumerate(starts):
        e = ends[i] if i < len(ends) else (dur if dur else None)
        out.append((round(s + start, 3), round(e + start, 3) if e is not None else None))
    return out


def silence_spans(path, noise_db=-50.0, min_dur=0.5):
    """[(start, end)] of silence (below `noise_db` for at least `min_dur` s). end None = silent to the end."""
    err = run(["-i", path, "-vn", "-af", "silencedetect=n=%gdB:d=%.2f" % (noise_db, min_dur), "-f", "null", "-"])
    return _spans(err, "silence_start", "silence_end")


def max_volume(path):
    """Peak sample level in dBFS (volumedetect); -91 for digital silence."""
    err = run(["-i", path, "-vn", "-af", "volumedetect", "-f", "null", "-"])
    m = re.search(r"max_volume:\s*(-?[\d.]+|-inf)", err)
    if not m or m.group(1) == "-inf":
        return -91.0
    return float(m.group(1))


def mean_luma(path):
    """Average luma (0-255) of an image or the first frame of a video (signalstats)."""
    err = run(["-i", path, "-frames:v", "1", "-vf", "signalstats,metadata=print:key=lavfi.signalstats.YAVG",
               "-f", "null", "-"])
    m = re.search(r"YAVG=([\d.]+)", err)
    return float(m.group(1)) if m else 0.0


def loudness(path):
    """{"I": integrated LUFS, "TP": true peak dBTP, "LRA": LU} measured with ebur128 (peak=true)."""
    err = run(["-i", path, "-vn", "-af", "ebur128=peak=true:framelog=quiet", "-f", "null", "-"])
    summary = err[err.rfind("Summary:"):] if "Summary:" in err else err

    def grab(pat):
        m = re.search(pat, summary, re.S)
        if not m or m.group(1) in ("-inf", "inf", "nan"):
            return None
        return float(m.group(1))
    return {"I": grab(r"Integrated loudness:.*?I:\s*(-?[\d.]+|-inf)"),
            "LRA": grab(r"Loudness range:.*?LRA:\s*(-?[\d.]+|-inf)"),
            "TP": grab(r"True peak:.*?Peak:\s*(-?[\d.]+|-inf)")}


def loudnorm(src, dst, target_i=-14.0, target_tp=-1.5, lra=11.0, rate=48000, channels=2):
    """Two-pass loudnorm (measure, then apply with the measured values, linear) to a WAV; then verify with
    ebur128 and, if needed, one corrective gain pass. Returns {"measured", "result", "passes"}."""
    base = "loudnorm=I=%g:TP=%g:LRA=%g" % (target_i, target_tp, lra)
    err = run(["-i", src, "-vn", "-af", base + ":print_format=json", "-f", "null", "-"])
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", err, re.S)
    if not m:
        raise BBError("loudnorm did not report its measurement for %s" % os.path.basename(src))
    meas = json.loads(m.group(0))
    if meas.get("input_i") in ("-inf", None) or str(meas.get("input_i")).startswith("-inf"):
        raise BBError("%s is silent: nothing to normalise" % os.path.basename(src))
    second = ("%s:measured_I=%s:measured_TP=%s:measured_LRA=%s:measured_thresh=%s:offset=%s:linear=true"
              % (base, meas["input_i"], meas["input_tp"], meas["input_lra"], meas["input_thresh"],
                 meas["target_offset"]))
    run(["-i", src, "-vn", "-af", second, "-ar", str(rate), "-ac", str(channels), "-c:a", "pcm_s16le", dst])
    res = loudness(dst)
    passes = 2
    if res["I"] is not None and res["TP"] is not None and (abs(res["I"] - target_i) > 0.5 or res["TP"] > -1.0):
        gain = target_i - res["I"]
        if res["TP"] + gain > target_tp:
            gain = target_tp - res["TP"]
        tmp = dst + ".fix.wav"
        run(["-i", dst, "-af", "volume=%.2fdB" % gain, "-ar", str(rate), "-ac", str(channels), "-c:a", "pcm_s16le",
             tmp])
        os.replace(tmp, dst)
        res = loudness(dst)
        passes = 3
    return {"measured": {k: meas.get(k) for k in ("input_i", "input_tp", "input_lra", "input_thresh")},
            "result": res, "passes": passes}


# ---------------------------------------------------------------- sizes + encoding
def master_size(aspect, settings=None):
    """(w, h) of the master: bizzbell.json media.width overrides the default width (height follows the aspect)."""
    w, h = SIZES.get(aspect, SIZES["9:16"])
    want = ((settings or {}).get("media") or {}).get("width")
    if want:
        want = int(want) // 2 * 2
        h = int(round(want * h / float(w))) // 2 * 2
        w = want
    return w, h


def cover_filter(w, h):
    """Scale to cover w x h and centre-crop (no letterbox)."""
    return ("scale=%d:%d:force_original_aspect_ratio=increase:flags=lanczos,crop=%d:%d,setsar=1" % (w, h, w, h))


def fill_filter(w, h, src_aspect):
    """Fill w x h from pictures made for `src_aspect`: crop when the shapes are close (within 1.35x), else show the
    whole picture over a blurred, darkened copy of itself (no black bars, nothing important cropped away)."""
    aw, ah = [float(x) for x in src_aspect.split(":")]
    ratio = (aw / ah) / (w / float(h))
    if 1 / 1.35 <= ratio <= 1.35:
        return cover_filter(w, h)
    r = max(2, min(20, min(w, h) // 8))
    return ("split=2[bbg][bfg];[bbg]scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,boxblur=%d:2,"
            "eq=brightness=-0.12[bbg2];[bfg]scale=%d:%d:force_original_aspect_ratio=decrease:flags=lanczos[bfg2];"
            "[bbg2][bfg2]overlay=(W-w)/2:(H-h)/2,setsar=1" % (w, h, w, h, r, w, h))


def video_encode_args(fps):
    return ["-r", str(fps), "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p"]


def crop_image_to_aspect(path, aspect):
    """Centre-crop an image file in place to the exact aspect (no-op when it is already within 0.5 %)."""
    p = probe(path)
    aw, ah = [float(x) for x in aspect.split(":")]
    w, h = p["width"], p["height"]
    if not w or not h or abs(w / float(h) - aw / ah) < 0.005:
        return False
    if w / float(h) > aw / ah:
        nw, nh = int(h * aw / ah) // 2 * 2, h // 2 * 2
    else:
        nw, nh = w // 2 * 2, int(w * ah / aw) // 2 * 2
    tmp = path + ".crop.png"
    run(["-i", path, "-vf", "crop=%d:%d" % (nw, nh), "-frames:v", "1", tmp])
    os.replace(tmp, path)
    return True
