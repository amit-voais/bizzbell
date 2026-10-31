"""bb mark <stage> <status>: record a stage status by hand (for example skipped when /v1/videos is not live)."""
from .. import project
from ..cli import add_project_arg

NAME = "mark"
HELP = "set a stage's status by hand (todo, made, skipped, ...)"


def register(p):
    p.add_argument("stage", choices=[s["id"] for s in project.STAGES])
    p.add_argument("status", choices=["todo", "made", "skipped", "passed", "failed"])
    add_project_arg(p)
    p.add_argument("--note", default="", help="why (shown in bb status)")


def run(args):
    root = project.find_project(args.project)
    project.mark_stage(root, args.stage, args.status, note=args.note)
    nxt = project.next_stage(root)
    print("%s: %s%s" % (args.stage, args.status, ("; next: %s" % nxt) if nxt else "; all stages done"))
    return 0
