"""bb gate <stage>: score one layer against its rubric. Exit 0 on pass, 3 on fail."""
import json

from .. import gate, project, restructure
from ..cli import add_project_arg

NAME = "gate"
HELP = "score a layer with its rubric questions (exit 0 pass, 3 fail)"


def register(p):
    p.add_argument("stage", choices=[s["id"] for s in project.STAGES])
    add_project_arg(p)
    p.add_argument("--passes", type=int, default=None, help="judge passes (default from bizzbell.json, 2)")
    p.add_argument("--json", action="store_true", help="print the saved record as JSON")


def run(args):
    root = project.find_project(args.project)
    rec = gate.run(root, args.stage, passes=args.passes)
    if args.json:
        print(json.dumps(rec, indent=2, ensure_ascii=False))
    else:
        used, allowed = restructure.rounds(root, args.stage)
        print(gate.format_result(rec, max_rounds=allowed, rounds_used=used))
    return 0 if rec["passed"] else 3
