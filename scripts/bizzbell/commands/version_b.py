"""bb version_b [build|check|render|all]: Version B (stage 8B), made with HyperFrames from screenplay.json.

build   hf/<ratio>/index.html for 9:16, 1:1, 16:9 and 4:5 (each laid out again, never cropped)
check   cut-off text (HyperFrames check + DOM safe-zone bounds) and frame repeatability -> out/B/qa.json
render  out/B/<slug>_B_<ratio>.mp4; 4:5 only when its text fits
all     build, check, render (the default)
Exit 0 when everything passed, 3 when a check failed (the videos are still made), 1 on an error.
Free: no Hidrogen call. Needs Node 22+ (npx) and ffmpeg."""
import os

from .. import project, util
from ..cli import add_project_arg
from ..errors import BBError
from ..hf import compose, formats, qa, render, runner

NAME = "version_b"
HELP = "Version B with HyperFrames: build, check (cut-off text, repeatability), render (free, local)"


def register(p):
    add_project_arg(p)
    p.add_argument("action", nargs="?", default="all", choices=["build", "check", "render", "all"])
    p.add_argument("--ratios", default="", help="comma list, e.g. 9:16,1:1 (default: 9:16, 1:1, 16:9, 4:5)")
    p.add_argument("--quality", default="looks", choices=list(render.QUALITIES), help="render quality")
    p.add_argument("--samples", type=int, default=6, help="frames sampled by the repeatability check")
    p.add_argument("--no-repeat", action="store_true", help="skip the repeatability check (faster)")


def _need_hyperframes(root):
    ok, why = runner.available(root)
    if not ok:
        raise runner.Unavailable("HyperFrames is not available: %s" % why)


def _build(root, ratios):
    b = compose.build(root, ratios)
    print("built Version B (%s s, %d shots, %d caption words from %s) for %s"
          % (b["duration"], b["shots"], b["words"], b["caption_source"], ", ".join(ratios)))
    for w in b["warnings"]:
        print("  note: %s" % w)
    return b


def _check(root, ratios, args):
    bad = False
    for r in ratios:
        rec = qa.check_ratio(root, r, samples=args.samples, with_repeat=not args.no_repeat)
        print("  %-5s %s" % (formats.FORMATS[r]["ratio"], qa.summary(rec)))
        for i in (rec["bounds"].get("issues") or [])[:4] + (rec["hf_check"].get("text") or [])[:4]:
            print("        - %s %s at %ss" % (i.get("code"), i.get("el") or i.get("selector"),
                                             i.get("t", i.get("time"))))
        if r in formats.REQUIRED and (not rec["text_ok"] or rec["repeat_ok"] is False):
            bad = True
    return bad


def _render(root, ratios, args):
    data = qa.load(root)
    made = []
    fps = int((util.read_json(os.path.join(root, "hf", "build.json"), {}) or {}).get("fps", 30))
    for r in ratios:
        rec = (data.get("ratios") or {}).get(r) or {}
        if r not in formats.REQUIRED and not (qa.fresh(root, r, data) and rec.get("text_ok")):
            why = "its text does not fit the 4:5 safe zone" if qa.fresh(root, r, data) else \
                "not checked yet (run: bb version_b check --ratios 4:5)"
            qa.record_video(root, r, None, skipped=why)
            print("  %-5s skipped: %s" % (formats.FORMATS[r]["ratio"], why))
            continue
        info = render.render(root, r, quality=args.quality, fps=fps)
        qa.record_video(root, r, info)
        made.append(info["path"])
        print("  %-5s %s (%sx%s, %.2f s%s)" % (formats.FORMATS[r]["ratio"], info["path"], info["width"],
                                               info["height"], info["duration"], ", audio" if info["has_audio"] else ""))
    if made:
        project.mark_stage(root, "video_b", "made", note="rendered %s; gate it: bb gate video_b" % ", ".join(
            os.path.basename(m) for m in made))
    return made


def run(args):
    root = project.find_project(args.project)
    ratios = formats.parse_list(args.ratios)
    if args.action in ("build", "all"):
        _build(root, ratios)
    if args.action == "build":
        return 0
    _need_hyperframes(root)
    bad = False
    if args.action in ("check", "all"):
        print("checking with hyperframes@%s:" % runner.pin(root))
        bad = _check(root, ratios, args)
    if args.action in ("render", "all"):
        print("rendering:")
        made = _render(root, ratios, args)
        if not made:
            raise BBError("nothing was rendered")
    if bad:
        print("a check failed: see out/B/qa.json; fix the screenplay text or brand, then: bb version_b")
        return 3
    if args.action in ("render", "all"):
        print("next: python3 scripts/bb.py gate video_b")
    return 0
