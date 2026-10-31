"""bb music: an instrumental bed, judged voice-free on every pass, edited to the film (stage 7)."""
import json

from .. import project
from ..cli import add_project_arg
from ..media import cmdutil, music

NAME = "music"
HELP = "music bed: instrumental, judged voice-free every pass, edited to the film length (Hidrogen music), gate"


def register(p):
    p.add_argument("action", choices=["make", "show", "gate", "restructure"],
                   help="make (paid) | show | gate | restructure")
    add_project_arg(p)
    cmdutil.add_make_args(p)
    cmdutil.add_gate_args(p)
    p.add_argument("--seconds", type=int, default=None, help="make: seconds to generate (default film + 2)")


def run(args):
    root = project.find_project(args.project)
    if args.action == "make":
        it = music.make(root, seconds=args.seconds, **cmdutil.make_kwargs(args))
        return cmdutil.finish(it if "plan" in it else {"bed": it}, "python3 scripts/bb.py mix build")
    if args.action == "show":
        items = music.status(root)
        if args.json:
            print(json.dumps(items, indent=2, ensure_ascii=False))
        else:
            cmdutil.print_items(items)
        return 0
    if args.action == "gate":
        return cmdutil.gate(root, "music", args)
    return cmdutil.restructure(root, "music", args, "python3 scripts/bb.py music make")
