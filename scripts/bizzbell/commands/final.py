"""bb final: stage 9. Every size of each made version, the phone-share copies, the final gate of each version
against the screenplay, and out/report.md; prints both versions' scores and the file paths."""
from .. import final, project
from ..cli import add_project_arg

NAME = "final"
HELP = "stage 9: all sizes, share copies (<25 MB), final gate per version, out/report.md"


def register(p):
    add_project_arg(p)
    p.add_argument("--quality", default="draft", choices=["draft", "looks", "delivery"],
                   help="HyperFrames quality if Version B sizes must be rendered again")
    p.add_argument("--no-gate", action="store_true", help="make the files and the report; skip the paid final gate")
    p.add_argument("--passes", type=int, default=None, help="judge passes for the final gate")
    p.add_argument("--json", action="store_true", help="print the result as JSON")


def run(args):
    root = project.find_project(args.project)
    res = final.run(root, quality=args.quality, do_gate=not args.no_gate, passes=args.passes)
    print(final.summary_json(res) if args.json else final.format_result(root, res))
    return final.exit_code(res)
