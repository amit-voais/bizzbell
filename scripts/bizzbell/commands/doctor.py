"""bb doctor: check tools, key, gateway, models and media endpoints (never a paid call)."""
import json

from .. import doctor, project
from ..cli import add_project_arg
from ..errors import UsageError

NAME = "doctor"
HELP = "check python, ffmpeg, node, the key, the gateway; pick the models"


def register(p):
    add_project_arg(p)
    p.add_argument("--no-write", action="store_true", help="do not save the model choice")
    p.add_argument("--json", action="store_true")


def run(args):
    try:
        root = project.find_project(args.project)
    except UsageError:
        if args.project:
            raise
        root = None
    res = doctor.run(root, write=not args.no_write)
    print(json.dumps(res, indent=2) if args.json else doctor.format_result(res))
    return 0 if all(c["ok"] for c in res["checks"]) else 1
