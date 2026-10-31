"""Version B's two deterministic checks per ratio, saved to out/B/qa.json and tied to the composition's hash.

qa.json: {pin, ratios: {<ratio>: {hash, time, hf_check{...}, bounds{...}, text_ok, repeat{...}|null, repeat_ok,
                                  video{path, width, height, duration, has_audio}|null, skipped}}}
A record counts only while its hash matches the composition on disk (fresh()); `bb version_b check` refreshes it.
The gate's local checks (bizzbell/checks/version_b.py) read this file."""
import os

from .. import util
from ..errors import BBError
from . import audit, compose, formats, repeat, runner


def qa_path(root):
    return os.path.join(root, "out", "B", "qa.json")


def load(root):
    return util.read_json(qa_path(root), {}) or {}


def _update(root, fn):
    p = qa_path(root)
    with util.locked(p):
        d = util.read_json(p, {}) or {}
        d.setdefault("ratios", {})
        fn(d)
        util.write_json(p, d)
    return d


def current_hash(root, ratio):
    folder = os.path.join(root, "hf", formats.name(ratio))
    if not os.path.isfile(os.path.join(folder, "index.html")):
        return None
    return compose.composition_hash(folder)


def built_from_latest(root, ratio):
    """True when hf/<ratio>/ came from the latest build (not left over from an older screenplay or brand)."""
    b = util.read_json(os.path.join(root, "hf", "build.json"), {}) or {}
    rec = (b.get("ratios") or {}).get(formats.name(ratio)) or {}
    return bool(b.get("plan")) and rec.get("plan") == b.get("plan")


def fresh(root, ratio, data=None):
    """True when qa.json holds a record for `ratio` made from the composition now on disk, and that composition
    came from the latest build."""
    rec = ((data or load(root)).get("ratios") or {}).get(formats.name(ratio)) or {}
    h = current_hash(root, ratio)
    return bool(h) and rec.get("hash") == h and built_from_latest(root, ratio)


def check_ratio(root, ratio, samples=6, with_repeat=True, hf_samples=12):
    """Run the cut-off text checks (and the repeatability check) for one ratio; save and return the record."""
    ratio = formats.name(ratio)
    folder = os.path.join(root, "hf", ratio)
    build = util.read_json(os.path.join(root, "hf", "build.json"), {}) or {}
    if not os.path.isfile(os.path.join(folder, "index.html")) or not build:
        raise BBError("no Version B composition for %s yet (run: bb version_b build)" % ratio)
    h = compose.composition_hash(folder)
    rec = {"hash": h, "time": util.now(), "pin": runner.pin(root)}
    rec["hf_check"] = audit.hf_check(folder, root=root, samples=hf_samples)
    rec["bounds"] = audit.bounds(folder, ratio)
    rec["text_ok"] = bool(rec["hf_check"]["ok"] and rec["bounds"]["ok"])
    if with_repeat:
        shots = [{"start": a, "end": b} for a, b in build.get("shot_times", [])]
        rec["repeat"] = repeat.run(folder, os.path.join(root, "hf", "_qa", ratio), float(build["duration"]),
                                   shots, n=samples, root=root)
        rec["repeat_ok"] = rec["repeat"]["ok"]
    else:
        rec["repeat"], rec["repeat_ok"] = None, None
    old = (load(root).get("ratios") or {}).get(ratio) or {}
    rec["video"] = old.get("video") if old.get("hash") == h else None

    def f(d):
        d["pin"] = rec["pin"]
        d["ratios"][ratio] = rec
    _update(root, f)
    return rec


def record_video(root, ratio, info=None, skipped=""):
    """Store the rendered video's facts (or why the ratio was skipped) on its qa record."""
    ratio = formats.name(ratio)

    def f(d):
        rec = d["ratios"].setdefault(ratio, {})
        rec["video"] = info
        rec["skipped"] = skipped
    _update(root, f)


def summary(rec):
    """One line per ratio for the CLI."""
    def yn(v):
        return "n/a" if v is None else ("ok" if v else "FAIL")
    hc, bd = rec.get("hf_check") or {}, rec.get("bounds") or {}
    parts = ["text %s (hyperframes %d text, %d errors; safe zone %d issues of %d boxes)"
             % (yn(rec.get("text_ok")), len(hc.get("text", [])), len(hc.get("errors", [])),
                len(bd.get("issues", [])), bd.get("checked", 0)),
             "repeat %s" % yn(rec.get("repeat_ok"))]
    if rec.get("repeat") and rec["repeat"].get("differing"):
        parts.append("frames that differ at %s s" % ", ".join("%g" % t for t in rec["repeat"]["differing"]))
    if hc.get("contrast"):
        parts.append("%d contrast notes" % len(hc["contrast"]))
    return "; ".join(parts)
