"""bb version_a: assemble Version A (picked clip windows + mix + burned captions) into out/A/, then gate it."""
import json

from .. import project
from ..cli import add_project_arg
from ..media import cmdutil, layers, version_a

NAME = "version_a"
HELP = "assemble Version A: clip windows, VO + music mix, burned captions -> out/A/<slug>_A_<aspect>.mp4; gate"


def register(p):
    p.add_argument("action", choices=["build", "gate", "restructure"], nargs="?", default="build",
                   help="build (free, ffmpeg) | gate | restructure (rewrites clips/prompts.json)")
    add_project_arg(p)
    p.add_argument("--dry-run", action="store_true", help="build: print the shot plan; make nothing")
    p.add_argument("--aspect", default=None, choices=["9:16", "16:9", "1:1", "4:5"],
                   help="build another size from the same shots (default: the master aspect; bb final makes them all)")
    cmdutil.add_gate_args(p)


def run(args):
    root = project.find_project(args.project)
    if args.action == "build":
        rep = version_a.build(root, dry_run=args.dry_run, aspect=args.aspect)
        if args.json:
            print(json.dumps(rep, indent=2, ensure_ascii=False))
        elif not args.dry_run:
            print("next: python3 scripts/bb.py version_a gate")
        return 0
    layer = layers.version_a_rubric(root)
    if args.action == "gate":
        return cmdutil.gate(root, layer, args)
    return cmdutil.restructure(root, layer, args, "python3 scripts/bb.py clips make, then version_a build")
