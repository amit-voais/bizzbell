"""bb clips: Version A clips, image-to-video per shot from its keyframe (stage 8A), pick a take, gate."""
import json

from .. import project
from ..cli import add_project_arg
from ..errors import UsageError
from ..media import clips, cmdutil

NAME = "clips"
HELP = "make Version A clips (Hidrogen image-to-video, keyframe as first frame, early window), pick, gate"


def register(p):
    p.add_argument("action", choices=["make", "pick", "show", "gate", "restructure"],
                   help="make (paid) | pick <shot> --take N [--start S] | show | gate | restructure")
    p.add_argument("items", nargs="*", help="shot ids (default: every live shot with a keyframe)")
    add_project_arg(p)
    cmdutil.add_make_args(p)
    cmdutil.add_gate_args(p)
    p.add_argument("--take", type=int, default=None, help="pick: the take number")
    p.add_argument("--start", type=float, default=None, help="pick: where the window starts in the take (s)")


def run(args):
    root = project.find_project(args.project)
    if args.action == "make":
        res = clips.make(root, args.items, **cmdutil.make_kwargs(args))
        if isinstance(res, dict) and res.get("skipped"):
            print("video_a: skipped. next: Version B (HyperFrames)")
            return 0
        return cmdutil.finish(res, "python3 scripts/bb.py clips gate")
    if args.action == "pick":
        if len(args.items) != 1 or args.take is None:
            raise UsageError("usage: bb clips pick <shot> --take N [--start S]")
        print("%s: take %d -> %s" % (args.items[0], args.take, clips.pick(root, args.items[0], args.take, args.start)))
        return 0
    if args.action == "show":
        items = clips.status(root)
        if args.json:
            print(json.dumps(items, indent=2, ensure_ascii=False))
        else:
            cmdutil.print_items(items)
        return 0
    if args.action == "gate":
        return cmdutil.gate(root, "clips", args)
    return cmdutil.restructure(root, "clips", args, "python3 scripts/bb.py clips make")
