"""Repeatability check (spec section 9.1): render a sample of frames twice, the second time in shuffled order,
and compare. A frame that differs means the composition depends on wall-clock time or render order.

Frames come from HyperFrames' `snapshot --at` (the same seek-and-capture path as a render). Two frames are the
same when their PNG bytes hash the same, or when, decoded by ffmpeg to small grey images, fewer than
DIFF_FRACTION of the pixels differ by more than DIFF_LEVEL (PNG encoders may differ in a byte, not a pixel)."""
import glob
import hashlib
import os
import random
import re
import shutil
import subprocess

from ..errors import BBError
from . import runner

DIFF_LEVEL = 12          # grey levels (0-255) a pixel may move before it counts as changed
DIFF_FRACTION = 0.002    # more than 0.2 % changed pixels = the frame differs
COMPARE_W, COMPARE_H = 216, 384


def ffmpeg():
    p = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
    if not os.path.exists(p) and not shutil.which("ffmpeg"):
        raise BBError("ffmpeg was not found (install it: brew install ffmpeg / apt install ffmpeg)")
    return p


def sample_times(duration, shots=(), n=6):
    """Up to n times inside (0, duration): shot midpoints first, then evenly spaced; 2 decimals, sorted."""
    ts = []
    for s in shots:
        t = round((s["start"] + s["end"]) / 2.0, 2)
        if 0 < t < duration and t not in ts:
            ts.append(t)
    i = 0
    while len(ts) < n and i < n * 4:
        t = round(duration * (i + 0.5) / (n * 2), 2)
        if 0 < t < duration and all(abs(t - x) > 0.05 for x in ts):
            ts.append(t)
        i += 1
    return sorted(ts[:n])


def shuffled(times, seed=7):
    """The same times in a different order (never the original order when there are 2 or more)."""
    out = list(times)
    random.Random(seed).shuffle(out)
    if len(out) > 1 and out == sorted(out):
        out.reverse()
    return out


def _snapshot(folder, times, out_dir, root=None):
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir)
    runner.run(["snapshot", os.path.abspath(folder), "--at", ",".join("%g" % t for t in times), "--no-end",
                "--output", out_dir], root=root, timeout=900)
    got = {}
    for p in glob.glob(os.path.join(out_dir, "frame-*-at-*s.png")):
        m = re.search(r"-at-([0-9.]+)s\.png$", p)
        if m:
            t = min(times, key=lambda x: abs(x - float(m.group(1))))
            got[t] = p
    return got


def _grey(path):
    r = subprocess.run([ffmpeg(), "-v", "error", "-i", path, "-vf", "scale=%d:%d,format=gray" % (COMPARE_W, COMPARE_H),
                        "-f", "rawvideo", "-"], capture_output=True, timeout=120)
    if r.returncode != 0:
        raise BBError("ffmpeg could not read %s" % os.path.basename(path))
    return r.stdout


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def compare(a, b):
    """{same, identical, changed_fraction, max_diff} for two PNG files."""
    if _sha(a) == _sha(b):
        return {"same": True, "identical": True, "changed_fraction": 0.0, "max_diff": 0}
    x, y = _grey(a), _grey(b)
    if len(x) != len(y) or not x:
        return {"same": False, "identical": False, "changed_fraction": 1.0, "max_diff": 255}
    diffs = [abs(p - q) for p, q in zip(x, y)]
    changed = sum(1 for d in diffs if d > DIFF_LEVEL) / float(len(diffs))
    return {"same": changed <= DIFF_FRACTION, "identical": False, "changed_fraction": round(changed, 5),
            "max_diff": max(diffs)}


def run(folder, work_dir, duration, shots=(), n=6, root=None, seed=7):
    """Snapshot the sample in order, then again shuffled; compare per time.
    Returns {ok, times, order_b, frames:[{t, same, identical, changed_fraction, max_diff}], differing:[t]}."""
    times = sample_times(duration, shots, n)
    if not times:
        raise BBError("no frame times to sample (duration %s)" % duration)
    order_b = shuffled(times, seed)
    a = _snapshot(folder, times, os.path.join(work_dir, "pass_a"), root)
    b = _snapshot(folder, order_b, os.path.join(work_dir, "pass_b"), root)
    frames, differing = [], []
    for t in times:
        if t not in a or t not in b:
            frames.append({"t": t, "same": False, "identical": False, "missing": True})
            differing.append(t)
            continue
        c = compare(a[t], b[t])
        c["t"] = t
        frames.append(c)
        if not c["same"]:
            differing.append(t)
    return {"ok": not differing, "times": times, "order_b": order_b, "frames": frames, "differing": differing}
