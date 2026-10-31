"""bb keyframes: one keyframe per live shot (stage 6), reject/approve by hand, gate."""
import json

from .. import project
from ..cli import add_project_arg
from ..errors import UsageError
from ..media import cmdutil, keyframes, screenplay, store

NAME = "keyframes"
HELP = "make one keyframe per live shot (Hidrogen image, refs = sheets + plates + previous keyframe), gate"


def register(p):
    p.add_argument("action", choices=["plan", "make", "reject", "approve", "show", "gate", "restructure"],
                   help="plan: write keyframes/prompts.json | make (paid) | reject <shot> | approve <shot> | show | "
                        "gate | restructure")
    p.add_argument("items", nargs="*", help="shot ids (default: every live shot)")
    add_project_arg(p)
    cmdutil.add_make_args(p)
    cmdutil.add_gate_args(p)


def run(args):
    root = project.find_project(args.project)
    if args.action == "plan":
        sp = screenplay.load(root)
        prompts = store.sync_prompts(root, keyframes.D, keyframes.build_prompts(sp), rebuild=args.rebuild_prompts)
        for s in sp.live_shots():
            print("  %-6s %4.1f-%4.1f s  chars %-14s loc %-10s (%d chars)"
                  % (s["id"], s["start"], s["end"], ",".join(s["characters"]) or "-", s["location"] or "-",
                     len(prompts.get(s["id"], ""))))
        print("prompts: keyframes/prompts.json. next: python3 scripts/bb.py keyframes make --dry-run")
        return 0
    if args.action == "make":
        return cmdutil.finish(keyframes.make(root, args.items, **cmdutil.make_kwargs(args)),
                              "look at the keyframes, then python3 scripts/bb.py keyframes gate")
    if args.action in ("reject", "approve"):
        if not args.items:
            raise UsageError("usage: bb keyframes %s <shot> [--note TEXT]" % args.action)
        for sid in args.items:
            if args.action == "reject":
                moved = keyframes.reject(root, sid, args.note)
                print("%s rejected%s; the next make uses the note as a correction"
                      % (sid, (" (moved to %s)" % moved) if moved else ""))
            else:
                print("%s approved: %s" % (sid, keyframes.approve(root, sid, args.note)))
        return 0
    if args.action == "show":
        items = keyframes.status(root)
        if args.json:
            print(json.dumps(items, indent=2, ensure_ascii=False))
        else:
            cmdutil.print_items(items)
        return 0
    if args.action == "gate":
        return cmdutil.gate(root, "keyframes", args)
    return cmdutil.restructure(root, "keyframes", args, "python3 scripts/bb.py keyframes make")
