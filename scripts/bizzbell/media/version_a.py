"""Stage 8A, assembly (ffmpeg only, no API call): Version A from the picked clip windows.

Every shot fills its slot on the timeline, in screenplay order:
  live shot  -> clips/cut/<shot>.mp4 (the picked early window); without a clip, its keyframe with a slow push-in
                (reported as a flaw);
  still shot -> its image with a slow push-in;  graphic shot -> its image, else a plain dark card (the words are
                the captions).
Then audio/mix.wav underneath and the captions burned in: ASS through the subtitles filter (libass), or drawtext
when this ffmpeg has no libass. Output out/A/<slug>_A_<9x16|16x9|1x1|4x5>.mp4 plus out/A/captions.ass and
out/A/version_a.json (shots, fallbacks, loudness after encoding)."""
import os
import re
import shutil

from .. import project, util
from ..errors import UsageError
from . import ff, screenplay, store

CARD = "0x26364A"          # deep slate: graphic shots without an image (light enough for blackdetect)
FONT_FILES = ("/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/System/Library/Fonts/Supplemental/Arial.ttf",
              "/Library/Fonts/Arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "C:/Windows/Fonts/arialbd.ttf")


def output_name(root, aspect=None):
    """out/A/<slug>_A_<tag>.mp4 for `aspect` (default: the project's master aspect)."""
    st = project.load_state(root)
    tag = ff.ASPECT_TAG.get(aspect or st.get("aspect", "9:16"), "9x16")
    return os.path.join("out", "A", "%s_A_%s.mp4" % (st.get("slug") or "film", tag))


# ---------------------------------------------------------------- captions
def chunk(text, max_chars):
    """Split a caption into pieces of at most max_chars, at word boundaries."""
    words, out, cur = text.split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > max_chars:
            out.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        out.append(cur)
    return out or [text]


def captions(root, sp, max_chars=42):
    """[(start, end, text)]: the screenplay's caption column, else the placed VO lines (Roman spelling)."""
    raw = sp.row_captions()
    if not raw:
        timing = util.read_json(os.path.join(root, "audio", "vo_timing.json"), {}) or {}
        raw = [(l["start"], max(l["end"], l["start"] + 0.8), l["text"]) for l in timing.get("lines", [])
               if l.get("text")]
    out = []
    for a, b, text in raw:
        parts = chunk(text, max_chars)
        total = float(sum(len(p) for p in parts)) or 1.0
        t = a
        for p in parts:
            dt = (b - a) * len(p) / total
            out.append((round(t, 3), round(min(t + dt, sp.duration), 3), p))
            t += dt
    return [c for c in out if c[1] > c[0]]


def card_texts(sp):
    """[(start, end, [lines])] for graphic shots that name a title / subtitle / call to action."""
    out = []
    for s in sp.shots:
        g = s.get("card") or {}
        lines = [str(g[k]).strip() for k in ("title", "number", "subtitle", "cta") if g.get(k)]
        if s["kind"] == "graphic" and lines:
            if g.get("sample"):
                lines.append("Sample")
            a, b = sp.slot(s["id"])
            out.append((a, b, lines))
    return out


def _ass_time(t):
    cs = int(round(t * 100))
    return "%d:%02d:%02d.%02d" % (cs // 360000, (cs // 6000) % 60, (cs // 100) % 60, cs % 100)


def _ass_text(s):
    return s.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", "\\N")


def layout(w, h):
    """Font size, outline and bottom margin: captions sit above the platform UI band."""
    tall = h > w
    fs = int(round(h * (0.042 if tall else 0.06)))
    mv = int(round(h * (0.20 if tall else 0.08)))
    return fs, max(2, fs // 14), mv, int(round(w * 0.08))


def write_ass(path, caps, w, h, cards=()):
    fs, outline, mv, ml = layout(w, h)
    lines = ["[Script Info]", "ScriptType: v4.00+", "PlayResX: %d" % w, "PlayResY: %d" % h, "WrapStyle: 0",
             "ScaledBorderAndShadow: yes", "", "[V4+ Styles]",
             "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
             "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
             "MarginL, MarginR, MarginV, Encoding",
             "Style: Default,Arial,%d,&H00FFFFFF,&H000000FF,&H00101010,&H78000000,-1,0,0,0,100,100,0,0,1,%d,1,2,"
             "%d,%d,%d,1" % (fs, outline, ml, ml, mv),
             "Style: Card,Arial,%d,&H00FFFFFF,&H000000FF,&H00101010,&H00000000,-1,0,0,0,100,100,0,0,1,%d,0,5,"
             "%d,%d,0,1" % (int(fs * 1.6), outline, ml, ml), "", "[Events]",
             "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    for a, b, rows in cards:
        body = _ass_text(rows[0]) + "".join("\\N{\\fs%d}%s" % (fs, _ass_text(r)) for r in rows[1:])
        lines.append("Dialogue: 1,%s,%s,Card,,0,0,0,,%s" % (_ass_time(a), _ass_time(b), body))
    for a, b, text in caps:
        lines.append("Dialogue: 0,%s,%s,Default,,0,0,0,,%s" % (_ass_time(a), _ass_time(b), _ass_text(text)))
    util.write_text(path, "\n".join(lines) + "\n")


def _font():
    for f in FONT_FILES:
        if os.path.exists(f):
            return f
    return None


def drawtext_filter(caps, w, h, workdir, cards=()):
    """A drawtext chain (one filter per caption / card line, text read from files in workdir)."""
    fs, outline, mv, _ml = layout(w, h)
    font = _font()
    items = [(a, b, t, fs, "h-%d-text_h" % mv) for a, b, t in caps]
    for a, b, rows in cards:
        y0 = h // 2 - int(fs * 1.6)
        for j, t in enumerate(rows):
            size = int(fs * 1.6) if j == 0 else fs
            items.append((a, b, t, size, "%d" % (y0 + j * int(fs * 1.9))))
    parts = []
    for i, (a, b, text, size, y) in enumerate(items):
        name = "cap_%03d.txt" % i
        util.write_text(os.path.join(workdir, name), text)
        opt = ["textfile=%s" % name, "fontsize=%d" % size, "fontcolor=white", "borderw=%d" % outline,
               "bordercolor=black", "x=(w-text_w)/2", "y=%s" % y, "enable='between(t,%.3f,%.3f)'" % (a, b)]
        if font:
            opt.insert(0, "fontfile='%s'" % font.replace(":", "\\:"))
        parts.append("drawtext=" + ":".join(opt))
    return ",".join(parts) or "null"


# ---------------------------------------------------------------- segments
def _still(root, img, out, dur, w, h, fps, fill=None):
    frames = max(1, int(round(dur * fps)))
    vf = "%s,zoompan=z='min(zoom+0.0009,1.08)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=%d:s=%dx%d:fps=%s," \
         "format=yuv420p" % (fill or ff.cover_filter(w, h), frames, w, h, fps)
    ff.run(["-loop", "1", "-i", img, "-vf", vf, "-frames:v", str(frames), "-t", "%.3f" % dur, "-an"] +
           ff.video_encode_args(fps) + [out])


def _card(out, dur, w, h, fps):
    ff.run(["-f", "lavfi", "-i", "color=c=%s:s=%dx%d:r=%s:d=%.3f" % (CARD, w, h, fps, dur), "-an"] +
           ff.video_encode_args(fps) + [out])


def _fit(root, src, out, dur, w, h, fps, fill=None):
    vf = "%s,fps=%s,format=yuv420p,tpad=stop_mode=clone:stop_duration=3" % (fill or ff.cover_filter(w, h), fps)
    ff.run(["-i", src, "-an", "-vf", vf, "-t", "%.3f" % dur] + ff.video_encode_args(fps) + [out])


def plan(root, sp):
    """[(shot id, kind used, source, start, dur, flaw)] for every shot."""
    reg = store.load_registry(root, "clips")
    rows = []
    for s in sp.shots:
        a, b = sp.slot(s["id"])
        dur = round(b - a, 3)
        flaw = ""
        if s["kind"] == "live":
            it = reg["items"].get(s["id"], {})
            cut = it.get("file") or os.path.join("clips", "cut", "%s.mp4" % s["id"])
            kf = os.path.join("keyframes", "%s.png" % s["id"])
            if it.get("status") in store.GOOD + ("flagged",) and os.path.exists(os.path.join(root, cut)):
                rows.append((s["id"], "clip", cut, a, dur, "flagged clip" if it.get("status") == "flagged" else ""))
                continue
            if os.path.exists(os.path.join(root, kf)):
                rows.append((s["id"], "still", kf, a, dur, "no usable clip: the keyframe is shown with a push-in"))
                continue
            rows.append((s["id"], "card", None, a, dur, "no clip and no keyframe: a plain card"))
            continue
        img = s.get("image")
        if img and os.path.exists(os.path.join(root, img)):
            rows.append((s["id"], "still", img, a, dur, flaw))
        else:
            rows.append((s["id"], "card", None, a, dur,
                         "" if s["kind"] == "graphic" else "the still image is missing: a plain card"))
    return rows


def build(root, dry_run=False, log=print, aspect=None):
    """Assemble Version A. Returns the report dict (also saved as out/A/version_a.json).

    `aspect` makes another size from the same shots (bb final): pictures far from that shape are shown whole over
    a blurred copy instead of being cropped, and its report and captions go to version_a_<tag>.json and
    captions_<tag>.ass so the master's files stay as they are."""
    sp = screenplay.load(root)
    st = project.load_state(root)
    if (st.get("stages", {}).get("video_a", {}) or {}).get("status") == "skipped":
        raise UsageError("Version A is marked skipped (%s). Version B is the delivery."
                         % st["stages"]["video_a"].get("note", ""))
    ms = store.media_settings(root)
    size_aspect = aspect or sp.aspect
    if size_aspect not in ff.SIZES:
        raise UsageError("unknown aspect %r (use one of %s)" % (size_aspect, ", ".join(sorted(ff.SIZES))))
    master = size_aspect == sp.aspect
    w, h = ff.master_size(size_aspect, project.load_settings(root))
    fill = None if master else ff.fill_filter(w, h, sp.aspect)
    tag = "" if master else "_" + ff.ASPECT_TAG[size_aspect]
    fps = ms["fps"]
    rows = plan(root, sp)
    mix = os.path.join(root, "audio", "mix.wav")
    caps = captions(root, sp, int(ms["caption_chars"]))
    cards = card_texts(sp)
    out_rel = output_name(root, size_aspect)
    if dry_run:
        for r in rows:
            log("  %-6s %5.2f-%5.2f  %-5s %s%s" % (r[0], r[3], r[3] + r[4], r[1], r[2] or "-",
                                                    ("   (" + r[5] + ")") if r[5] else ""))
        log("  audio: %s | captions: %d | -> %s (%dx%d, %s fps)"
            % ("audio/mix.wav" if os.path.exists(mix) else "MISSING audio/mix.wav", len(caps), out_rel, w, h, fps))
        log("dry run: nothing was made (Version A assembly is local ffmpeg work and costs nothing)")
        return {"plan": rows, "output": out_rel}
    if not os.path.exists(mix):
        raise UsageError("audio/mix.wav is missing: python3 scripts/bb.py mix build")
    live = [r for r in rows if sp.shot(r[0])["kind"] == "live"]
    if live and not [r for r in live if r[1] == "clip"]:
        raise UsageError("no live shot has a clip yet: python3 scripts/bb.py clips make (or mark Version A skipped)")
    work = os.path.join(root, "out", "A", "_work" + tag)
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    listing = []
    for i, (sid, kind, src, _a, dur, _flaw) in enumerate(rows):
        seg = os.path.join(work, "seg_%03d.mp4" % i)
        if kind == "clip":
            _fit(root, os.path.join(root, src), seg, dur, w, h, fps, fill)
        elif kind == "still":
            _still(root, os.path.join(root, src), seg, dur, w, h, fps, fill)
        else:
            _card(seg, dur, w, h, fps)
        listing.append("file '%s'" % os.path.basename(seg))
    util.write_text(os.path.join(work, "list.txt"), "\n".join(listing) + "\n")
    ass = os.path.join(root, "out", "A", "captions%s.ass" % tag)
    write_ass(ass, caps, w, h, cards)
    method = "none"
    if (caps or cards) and ff.has_filter("subtitles"):
        shutil.copy2(ass, os.path.join(work, "captions.ass"))
        vf, method = "subtitles=filename=captions.ass", "ass"
    elif caps or cards:
        vf, method = drawtext_filter(caps, w, h, work, cards), "drawtext"
    else:
        vf = "null"
    out = os.path.join(root, out_rel)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    cmd = ["-f", "concat", "-safe", "0", "-i", "list.txt", "-i", mix, "-filter_complex",
           "[0:v]%s,format=yuv420p[v];[1:a]apad[a]" % vf, "-map", "[v]", "-map", "[a]", "-t", "%.3f" % sp.duration] + \
        ff.video_encode_args(fps) + ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", out]
    try:
        ff.run(cmd, cwd=work)
    except Exception:
        if method != "ass":
            raise
        log("  subtitles (libass) failed; burning the captions with drawtext instead")
        vf, method = drawtext_filter(caps, w, h, work, cards), "drawtext"
        cmd[cmd.index("-filter_complex") + 1] = "[0:v]%s,format=yuv420p[v];[1:a]apad[a]" % vf
        ff.run(cmd, cwd=work)
    p = ff.probe(out)
    loud = ff.loudness(out)
    report = {"file": out_rel, "duration": round(p["duration"], 3), "film_duration": sp.duration,
              "size": [p["width"], p["height"]], "fps": fps, "has_audio": p["has_audio"], "captions": len(caps),
              "cards": len(cards),
              "caption_method": method, "loudness": loud,
              "shots": [{"id": r[0], "used": r[1], "source": r[2], "start": r[3], "dur": r[4], "flaw": r[5]}
                        for r in rows],
              "flaws": ["%s: %s" % (r[0], r[5]) for r in rows if r[5]], "time": util.now()}
    util.write_json(os.path.join(root, "out", "A", "version_a%s.json" % tag), report)
    shutil.rmtree(work, ignore_errors=True)
    nan = float("nan")
    log("Version A: %s  %.2fs  %dx%d  captions %d (%s)  %.1f LUFS / %.1f dBTP"
        % (out_rel, report["duration"], p["width"], p["height"], len(caps), method,
           nan if loud["I"] is None else loud["I"], nan if loud["TP"] is None else loud["TP"]))
    for f in report["flaws"]:
        log("  flaw: " + f)
    return report


def caption_problems(caps):
    """Captions that are not Roman script (Devanagari belongs in the voice text, not on screen)."""
    return [c for c in caps if re.search(u"[\u0900-\u097F]", c[2])]
