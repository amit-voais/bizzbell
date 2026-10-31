"""bb restructure <stage>: rewrite a failed layer with the restructure model (max 3 rounds)."""
from .. import project, restructure
from ..cli import add_project_arg
from ..media.layers import LAYERS

NAME = "restructure"
HELP = "rewrite a layer that failed its gate (max 3 rounds, then ask the user)"


def register(p):
    p.add_argument("stage", choices=project.STAGE_IDS + [x for x in LAYERS if x not in project.STAGE_IDS] +
                   ["final_a", "final_b"])
    add_project_arg(p)
    p.add_argument("--extra", action="store_true",
                   help="allow one more round past the limit - ONLY after the user said yes")
    p.add_argument("--note", default="", help="note logged with --extra")


def run(args):
    root = project.find_project(args.project)
    print(restructure.format_result(restructure.run(root, args.stage, extra=args.extra, note=args.note)))
    return 0
