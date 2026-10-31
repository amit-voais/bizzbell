"""Stage 9: gather both versions, make the missing sizes and the phone-share copies, gate each version against
the screenplay with the final rubric, and write out/report.md.

Version A (out/A) gets 9:16, 1:1 and 16:9 from the same shots (and 4:5 when captions are burned with libass,
which wraps them inside the frame). Version B (out/B) is rendered by HyperFrames in every size already; when one
of its required sizes is missing, `bb version_b` is run again for all sizes. Each made version gets
<slug>_<A|B>_share.mp4: H.264 + AAC, at most 720 px on the short side, under 25 MB.

The final gate runs once per version (gate ids final_a, final_b) with a rubric derived from rubrics/final.json
(project override first) that names only that version's files; the derived rubrics are written to
<project>/rubrics/final_a.json and final_b.json and rewritten on every run."""
import glob
import json
import os

from . import gate, project, util
from .errors import BBError, UsageError
from .media import ff

VERSIONS = ("A", "B")
REQUIRED = ("9:16", "1:1", "16:9")
SHARE_MAX_MB = 25.0
SHARE_SHORT_SIDE = 720


def slug(root):
    return project.load_state(root).get("slug") or "film"


def video_path(root, version, tag):
    return os.path.join(root, "out", version, "%s_%s_%s.mp4" % (slug(root), version, tag))


def sizes_present(root, version):
    """{aspect: relative path} of the sizes on disk for a version."""
    out = {}
    for aspect, tag in ff.ASPECT_TAG.items():
        p = video_path(root, version, tag)
        if os.path.isfile(p):
            out[aspect] = os.path.relpath(p, root)
    return out


def skipped(root, version):
    """The note when Version A (video_a) or B (video_b) was marked skipped, else ''."""
    st = project.stage_state(root, "video_a" if version == "A" else "video_b")
    return (st.get("note") or "skipped") if st.get("status") == "skipped" else ""


def made(root, version):
    return bool(sizes_present(root, version)) and not skipped(root, version)


def master_aspect(root):
    return project.load_state(root).get("aspect") or "9:16"


# ---------------------------------------------------------------- sizes
def make_sizes_a(root, log=print):
    """Build every missing Version A size from the same shots. Returns the aspects made now."""
    from .media import version_a
    want = list(REQUIRED) + (["4:5"] if ff.has_filter("subtitles") else [])
    have = sizes_present(root, "A")
    done = []
    for aspect in want:
        if aspect in have:
            continue
        log("Version A %s: building from the same shots" % aspect)
        version_a.build(root, log=lambda *_: None, aspect=aspect)
        done.append(aspect)
    return done


def make_sizes_b(root, quality="draft", log=print):
    """Render Version B again in every size when a required one is missing. Returns the aspects made now."""
    have = sizes_present(root, "B")
    missing = [a for a in REQUIRED if a not in have]
    if not missing:
        return []
    from .hf import compose, formats, qa, render, runner
    ok, why = runner.available(root)
    if not ok:
        raise runner.Unavailable("Version B is missing %s and HyperFrames is not available: %s"
                                 % (", ".join(missing), why))
    log("Version B is missing %s: building and rendering every size again" % ", ".join(missing))
    ratios = list(formats.ORDER)
    compose.build(root, ratios)
    fps = int((util.read_json(os.path.join(root, "hf", "build.json"), {}) or {}).get("fps", 30))
    done = []
    for r in ratios:
        rec = qa.check_ratio(root, r, with_repeat=False)
        if r not in formats.REQUIRED and not rec.get("text_ok"):
            qa.record_video(root, r, None, skipped="its text does not fit the 4:5 safe zone")
            continue
        info = render.render(root, r, quality=quality, fps=fps)
        qa.record_video(root, r, info)
        done.append(formats.FORMATS[r]["ratio"])
    project.mark_stage(root, "video_b", "made", note="rendered again by bb final; gate it: bb gate video_b")
    return done


# ---------------------------------------------------------------- share copy
def share_copy(src, dst, max_mb=SHARE_MAX_MB, short_side=SHARE_SHORT_SIDE):
    """A phone-share copy: H.264 (high, yuv420p) + AAC 128k, short side at most `short_side`, under `max_mb`.
    Returns {path, mb, width, height, duration}."""
    p = ff.probe(src)
    if not p["has_video"]:
        raise BBError("%s has no picture" % os.path.basename(src))
    dur = max(p["duration"], 0.5)
    w, h = p["width"], p["height"]
    if min(w, h) > short_side:
        scale = "scale=%d:-2:flags=lanczos" % short_side if w <= h else "scale=-2:%d:flags=lanczos" % short_side
    else:
        scale = "scale=trunc(iw/2)*2:trunc(ih/2)*2"
    kbps = int(max_mb * 0.9 * 8192 / dur) - 160
    tmp = dst + ".tmp.mp4"
    for crf, cap in ((23, min(4000, kbps)), (28, min(2000, int(kbps * 0.6)))):
        cap = max(200, cap)
        args = ["-i", src, "-map", "0:v:0", "-map", "0:a:0?", "-vf", scale + ",format=yuv420p",
                "-c:v", "libx264", "-profile:v", "high", "-preset", "medium", "-crf", str(crf),
                "-maxrate", "%dk" % cap, "-bufsize", "%dk" % (2 * cap), "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
                "-ac", "2", "-movflags", "+faststart", tmp]
        ff.run(args)
        if os.path.getsize(tmp) <= max_mb * 1024 * 1024:
            break
    os.replace(tmp, dst)
    mb = os.path.getsize(dst) / 1048576.0
    if mb > max_mb:
        raise BBError("the share copy %s is %.1f MB, over %.0f MB" % (os.path.basename(dst), mb, max_mb))
    q = ff.probe(dst)
    return {"path": dst, "mb": round(mb, 2), "width": q["width"], "height": q["height"],
            "duration": round(q["duration"], 2)}


def make_share(root, version, log=print):
    """<slug>_<V>_share.mp4 from the master size (else the first size there is)."""
    have = sizes_present(root, version)
    src = have.get(master_aspect(root)) or have.get("9:16") or sorted(have.values())[0]
    dst = video_path(root, version, "share")
    info = share_copy(os.path.join(root, src), dst)
    log("Version %s share copy: %s (%.1f MB, %dx%d)" % (version, os.path.relpath(dst, root), info["mb"],
                                                        info["width"], info["height"]))
    return info


# ---------------------------------------------------------------- per-version final gate
def gate_id(version):
    return "final_%s" % version.lower()


def _only(obj, other):
    """Copy of a rubric value without any path of the other version's folder."""
    if isinstance(obj, list):
        return [_only(x, other) for x in obj
                if not (isinstance(x, str) and (x.startswith("out/%s/" % other) or x == "out/%s" % other))]
    if isinstance(obj, dict):
        return {k: _only(v, other) for k, v in obj.items()}
    return obj


def version_rubric(root, version):
    """Write <project>/rubrics/final_<v>.json from the final rubric, naming only this version's files."""
    base = util.read_json(gate.rubric_path(root, "final"))
    other = "B" if version == "A" else "A"
    r = _only(base, other)
    r["stage"] = gate_id(version)
    r["derived_from"] = "final"
    r["title"] = "%s (Version %s)" % (base.get("title", "Final"), version)
    r["judge_notes"] = ("This run judges Version %s only (%s). The attached video is its 9:16 master; out/report.md "
                        "is pasted below it and covers both versions. Nothing is published by the skill."
                        % (version, "Hidrogen video" if version == "A" else "HyperFrames"))
    for q in r["questions"]:
        if q.get("check") == "formats_present":
            q.setdefault("args", {})["folders"] = ["out/%s" % version]
    gate.validate_rubric(r, "rubrics/%s.json" % gate_id(version))
    util.write_json(os.path.join(root, "rubrics", "%s.json" % gate_id(version)), r)
    return r


def run_gates(root, versions, passes=None, log=print):
    """{version: gate record | {"error": message, "exit_code": n}} for each made version."""
    out = {}
    for v in versions:
        version_rubric(root, v)
        try:
            out[v] = gate.run(root, gate_id(v), passes=passes)
        except BBError as e:
            out[v] = {"error": str(e), "exit_code": e.exit_code}
            log("final gate of Version %s not run: %s" % (v, e))
    return out


# ---------------------------------------------------------------- the whole stage
def run(root, quality="draft", do_gate=True, passes=None, log=print):
    """Stage 9. Returns {versions{V: {made, skipped, sizes, share}}, gates{V: record|error}, report, made_now}."""
    from . import report
    versions = [v for v in VERSIONS if made(root, v)]
    if not versions:
        raise UsageError("no finished version yet: make Version B (bb version_b) and, if /v1/videos is live, "
                         "Version A (bb version_a)")
    made_now = {}
    if "A" in versions:
        made_now["A"] = make_sizes_a(root, log)
    if "B" in versions:
        made_now["B"] = make_sizes_b(root, quality, log)
    shares = {v: make_share(root, v, log) for v in versions}
    report.write(root)                                   # the draft the final gate reads
    gates = run_gates(root, versions, passes, log) if do_gate else {}
    path = report.write(root, final_gates=gates)         # again, with the final scores
    errors = [g for g in gates.values() if "error" in g]
    if gates and not errors and all(g["passed"] for g in gates.values()):
        status = "passed"
    elif gates and not errors:
        status = "failed"
    else:
        status = "made"
    note = ", ".join("%s %s" % (v, ("%.1f" % g["score"]) if "score" in g else "not gated")
                     for v, g in sorted(gates.items())) or "final gate not run"
    project.mark_stage(root, "final", status, note=note)
    info = {}
    for v in VERSIONS:
        info[v] = {"made": v in versions, "skipped": skipped(root, v), "sizes": sizes_present(root, v),
                   "share": os.path.relpath(shares[v]["path"], root) if v in shares else None}
    return {"versions": info, "gates": gates, "report": os.path.relpath(path, root), "made_now": made_now,
            "status": status}


def exit_code(res):
    """0 when every final gate passed, 3 when one failed, else the exit code of the error that stopped a gate."""
    gates = res["gates"]
    for g in gates.values():
        if "error" in g:
            return g.get("exit_code", 1)
    if gates and not all(g["passed"] for g in gates.values()):
        return 3
    return 0


def format_result(root, res):
    lines = ["Bizzbell final: %s" % root]
    for v in VERSIONS:
        i = res["versions"][v]
        name = "Version %s (%s)" % (v, "Hidrogen video" if v == "A" else "HyperFrames")
        if not i["made"]:
            lines.append("%s: not made%s" % (name, (" (skipped: %s)" % i["skipped"]) if i["skipped"] else ""))
            continue
        g = res["gates"].get(v)
        if g is None:
            score = "final gate not run"
        elif "error" in g:
            score = "final gate not run: %s" % g["error"]
        else:
            score = "final score %.1f / %g %s (gate %s #%d)" % (g["score"], g["pass_score"],
                                                                 "PASS" if g["passed"] else "FAIL", g["stage"],
                                                                 g["run"])
        lines.append("%s: %s" % (name, score))
        for aspect in ("9:16", "1:1", "16:9", "4:5"):
            if aspect in i["sizes"]:
                lines.append("  %-5s %s" % (aspect, os.path.join(root, i["sizes"][aspect])))
        if i["share"]:
            lines.append("  share %s" % os.path.join(root, i["share"]))
        if g and "questions" in g and not g["passed"]:
            for q in gate.failed_questions(g)[:5]:
                lines.append("    %s %s: %s" % ("!" if q["hard"] else "-", q["id"], q["text"][:90]))
    lines.append("report: %s" % os.path.join(root, res["report"]))
    lines.append("Nothing was published. Switch on the platform's AI label when you upload.")
    return "\n".join(lines)


def summary_json(res):
    slim = dict(res)
    slim["gates"] = {v: ({k: g.get(k) for k in ("stage", "run", "score", "pass_score", "passed", "hard_failed")}
                         if "score" in g else g) for v, g in res["gates"].items()}
    return json.dumps(slim, indent=2, ensure_ascii=False)


def latest_gates(root):
    """{gate id: latest record} for every gate id with a saved run (gates/<id>.<n>.json)."""
    ids = set()
    for p in glob.glob(os.path.join(root, "gates", "*.json")):
        base = os.path.basename(p)[:-5]
        name, _, n = base.rpartition(".")
        if name and n.isdigit():
            ids.add(name)
    return {i: gate.latest(root, i) for i in ids}
