"""bb analyse <retention|edit|outliers>: optional stage 10, after a video is published. Local only: no paid call,
no budget, no network. It does not change the stages or `bb status`; outputs go in <project>/analysis/."""
import json
import os
import sys

from .. import project, util
from ..analysis import edit, outliers, retention
from ..analysis.text import printable
from ..cli import add_project_arg
from ..errors import BBError, UsageError

NAME = "analyse"
HELP = "after publishing: read a retention export, a transcript or a collected video list (free, optional)"


def register(p):
    sub = p.add_subparsers(dest="tool", metavar="<retention|edit|outliers>", required=True)

    r = sub.add_parser("retention", help="where people left and what was being said then",
                       description="Read a retention export (CSV): a position and the percent still watching.")
    r.add_argument("file", help="the retention CSV")
    r.add_argument("--transcript", help="SRT, VTT or whisper JSON: names what was said at each drop")
    r.add_argument("--duration", type=float, help="the video's length in seconds")
    r.add_argument("--axis", choices=["percent", "seconds"], help="what the position column is, when it is misread")
    r.add_argument("--hook-seconds", type=float, help="length of the opening window (default, a rule of thumb: a "
                                                      "quarter of the video, at most 30 s)")
    r.add_argument("--min-drop", type=float, default=retention.DEFAULT_MIN_DROP,
                   help="points lost in one step to count as a drop (rule of thumb, default %(default)s)")
    r.add_argument("--top", type=int, default=retention.DEFAULT_TOP,
                   help="how many drops to show (default %(default)s)")
    r.set_defaults(_tool=_retention)

    e = sub.add_parser("edit", help="a transcript to an edit decision list",
                       description="Dead air, retakes and filler cues from SRT, VTT or whisper JSON. Touches no media.")
    e.add_argument("file", help="the transcript")
    e.add_argument("--floor", type=float, default=edit.DEFAULT_FLOOR,
                   help="gaps longer than this many seconds count as dead air (rule of thumb, default %(default)s)")
    e.add_argument("--filler", action="append", default=[], metavar="WORD",
                   help="one more filler word or phrase to list for review, in any language (repeatable)")
    e.set_defaults(_tool=_edit)

    o = sub.add_parser("outliers", help="videos ranked by the multiple over their own channel's median",
                       description="Read a collected JSON list of videos. Fetches nothing and needs no login.")
    o.add_argument("file", help="the collected JSON: [{\"channel\", \"title\", \"views\", \"url\"}, ...]")
    o.add_argument("--min", type=float, default=outliers.DEFAULT_MIN_MULTIPLE, dest="min_multiple",
                   help="smallest multiple to show (rule of thumb, default %(default)s)")
    o.add_argument("--min-videos", type=int, default=outliers.DEFAULT_MIN_VIDEOS,
                   help="fewest videos per channel for a median (rule of thumb, default %(default)s)")
    o.add_argument("--top", type=int, default=outliers.DEFAULT_TOP,
                   help="how many to show in the report (default %(default)s)")
    o.set_defaults(_tool=_outliers)

    for leaf in (r, e, o):
        add_project_arg(leaf)
        leaf.add_argument("--json", action="store_true", help="print the report as JSON")


def _positive(value, flag):
    if value is not None and not value > 0:
        raise UsageError("%s must be above 0" % flag)


def _retention(args):
    _positive(args.duration, "--duration")
    _positive(args.hook_seconds, "--hook-seconds")
    _positive(args.top, "--top")
    if not args.min_drop >= 0:
        raise UsageError("--min-drop cannot be negative")
    rep = retention.analyse(args.file, transcript=args.transcript, duration=args.duration, axis=args.axis,
                            hook_seconds=args.hook_seconds, min_drop=args.min_drop, top=args.top)
    return rep, retention.render(rep)


def _edit(args):
    if not args.floor >= 0:
        raise UsageError("--floor cannot be negative")
    rep = edit.analyse(args.file, floor=args.floor, extra_fillers=args.filler)
    return rep, edit.render(rep)


def _outliers(args):
    _positive(args.top, "--top")
    _positive(args.min_videos, "--min-videos")
    if not args.min_multiple >= 0:
        raise UsageError("--min cannot be negative")
    rep = outliers.analyse(args.file, min_multiple=args.min_multiple, min_videos=args.min_videos)
    return rep, outliers.render(rep, top=args.top)


def _project_or_none(arg):
    """The project folder. A wrong --project is an error; no project at all only means nothing is saved."""
    if arg or os.environ.get("BB_PROJECT"):
        return project.find_project(arg)
    try:
        return project.find_project(None)
    except UsageError:
        return None


def _save(root, tool, rep, report):
    folder = project.path(root, "analysis")
    try:
        data = printable(json.dumps(rep, ensure_ascii=False, indent=2))
        util.write_text(os.path.join(folder, tool + ".json"), data + "\n")
        util.write_text(os.path.join(folder, tool + ".md"), printable(report))
    except OSError as e:
        raise BBError("could not save to %s: %s" % (printable(folder), e.strerror or "write error"))
    return folder


def run(args):
    root = _project_or_none(args.project)
    rep, report = args._tool(args)
    if hasattr(sys.stdout, "reconfigure"):      # a terminal that cannot show Devanagari gets escapes, not a crash
        sys.stdout.reconfigure(errors="backslashreplace")
    print(json.dumps(rep, ensure_ascii=False, indent=2) if args.json else report, end="\n" if args.json else "")
    done = sys.stderr if args.json else sys.stdout
    if root:
        print("saved: %s" % printable(os.path.join(_save(root, args.tool, rep, report), args.tool + ".md")), file=done)
    else:
        print("no project here, so nothing was saved (pass --project <folder> to keep it)", file=done)
    return 0
