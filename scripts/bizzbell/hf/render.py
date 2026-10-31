"""Render one ratio's HyperFrames project to out/B/<slug>_B_<ratio>.mp4 and verify it with ffprobe."""
import json
import os
import shutil
import subprocess

from .. import project
from ..errors import BBError
from . import formats, runner

QUALITIES = ("draft", "looks", "delivery")


def ffprobe():
    p = shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe"
    if not os.path.exists(p):
        raise BBError("ffprobe was not found (it comes with ffmpeg)")
    return p


def probe(path):
    """{width, height, duration, has_audio} of a video file."""
    r = subprocess.run([ffprobe(), "-v", "error", "-show_entries", "stream=codec_type,width,height:format=duration",
                        "-of", "json", path], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise BBError("ffprobe could not read %s" % os.path.basename(path))
    d = json.loads(r.stdout or "{}")
    v = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), {})
    return {"width": v.get("width"), "height": v.get("height"),
            "duration": round(float((d.get("format") or {}).get("duration") or 0), 3),
            "has_audio": any(s.get("codec_type") == "audio" for s in d.get("streams", []))}


def output_path(root, ratio):
    slug = project.load_state(root).get("slug") or "film"
    return os.path.join(root, "out", "B", "%s_B_%s.mp4" % (slug, formats.name(ratio)))


def render(root, ratio, quality="looks", fps=30, timeout=1800):
    """Render hf/<ratio>/ to out/B/. Returns {path, width, height, duration, has_audio, quality}."""
    ratio = formats.name(ratio)
    if quality not in QUALITIES:
        raise BBError("quality must be one of %s" % ", ".join(QUALITIES))
    folder = os.path.join(root, "hf", ratio)
    if not os.path.isfile(os.path.join(folder, "index.html")):
        raise BBError("hf/%s/index.html is missing (run: bb version_b build)" % ratio)
    out = output_path(root, ratio)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    tmp = os.path.join(root, "hf", "_render", os.path.basename(out))
    os.makedirs(os.path.dirname(tmp), exist_ok=True)
    if os.path.exists(tmp):
        os.remove(tmp)
    fps = fps if fps in (24, 30, 60) else 30
    runner.run(["render", os.path.abspath(folder), "--output", tmp, "--quality", quality, "--fps", str(fps),
                "--quiet"], root=root, timeout=timeout)
    if not os.path.isfile(tmp) or os.path.getsize(tmp) == 0:
        raise BBError("HyperFrames reported success but wrote no video for %s" % ratio)
    os.replace(tmp, out)
    info = probe(out)
    f = formats.FORMATS[ratio]
    if (info["width"], info["height"]) != (f["w"], f["h"]):
        raise BBError("%s rendered at %sx%s, expected %dx%d" % (ratio, info["width"], info["height"], f["w"], f["h"]))
    info.update({"path": os.path.relpath(out, root), "quality": quality, "fps": fps})
    return info
