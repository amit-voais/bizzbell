"""bb init <folder> --brief "...": create a project."""
from .. import project

NAME = "init"
HELP = "create a project folder from a brief"


def register(p):
    p.add_argument("folder", help="the new project folder")
    p.add_argument("--brief", required=True, help="what the video is for, in one or two sentences")
    p.add_argument("--lang", default="en", help="language: en, hi, hinglish, ... (default en)")
    p.add_argument("--aspect", default="9:16", choices=["9:16", "16:9", "1:1", "4:5"], help="master aspect")
    p.add_argument("--slug", default=None, help="short name used in output file names")


def run(args):
    root = project.init(args.folder, args.brief, lang=args.lang, aspect=args.aspect, slug=args.slug)
    print("project ready: %s" % root)
    print("next: agree a budget with the user, then: python3 scripts/bb.py budget set <inr> --project %s" % root)
    return 0
