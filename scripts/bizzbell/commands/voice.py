"""bb voice: audition voices, a judged take per VO line, place them on the timeline (stage 7)."""
import json

from .. import project
from ..cli import add_project_arg
from ..media import cmdutil, voice

NAME = "voice"
HELP = "voice-over: audition voices, judged takes per line, place on the timeline (Hidrogen TTS), gate"


def register(p):
    p.add_argument("action", choices=["list", "audition", "takes", "place", "show", "gate", "restructure"],
                   help="list (the stock voices) | audition [voice ...] (paid; default: voice.candidates, else "
                        "voice.name and two stock voices like it) | takes [line ...] (paid) | place (free) | show | "
                        "gate | restructure")
    p.add_argument("items", nargs="*", help="audition: voice names; takes: line ids")
    add_project_arg(p)
    cmdutil.add_make_args(p)
    cmdutil.add_gate_args(p)
    p.add_argument("--text", default=None, help="audition: the words to audition with")


def run(args):
    if args.action == "list":
        for g in sorted(voice.STOCK):
            print("%-7s %s" % (g, ", ".join(voice.STOCK[g])))
        print("audition some: python3 scripts/bb.py voice audition <name> <name> <name> -p <folder> "
              "(or set voice.candidates in screenplay.json)")
        return 0
    root = project.find_project(args.project)
    if args.action == "audition":
        names = [n.strip() for x in args.items for n in x.split(",") if n.strip()]
        res = voice.audition(root, names, text=args.text, dry_run=args.dry_run, judge=not args.no_judge,
                             redo=args.redo)
        if not args.dry_run:
            for name, score in res["ranking"]:
                print("  %-14s %.1f" % (name, score))
            print("chosen voice: %s. next: python3 scripts/bb.py voice takes" % res["chosen"] if res["chosen"]
                  else "no voice passed its local checks")
        return 0
    if args.action == "takes":
        return cmdutil.finish(voice.make_takes(root, args.items, **cmdutil.make_kwargs(args)),
                              "python3 scripts/bb.py voice place")
    if args.action == "place":
        t = voice.place(root)
        print("audio/vo.wav: %d lines on a %.2fs timeline%s. next: python3 scripts/bb.py music make"
              % (len(t["lines"]), t["duration"], (", %d warning(s)" % len(t["warnings"])) if t["warnings"] else ""))
        return 0
    if args.action == "show":
        reg = voice.status(root)
        if args.json:
            print(json.dumps(reg, indent=2, ensure_ascii=False))
        else:
            print("voice: %s" % voice.voice_name(root))
            cmdutil.print_items(reg["items"])
        return 0
    if args.action == "gate":
        return cmdutil.gate(root, "voice", args)
    return cmdutil.restructure(root, "voice", args, "python3 scripts/bb.py voice takes, then voice place")
