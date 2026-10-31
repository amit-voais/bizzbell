"""bb characters: character sheets and location plates (stage 5), or register an image the user approved."""
import json

from .. import project
from ..cli import add_project_arg
from ..errors import UsageError
from ..media import characters, cmdutil, screenplay, store

NAME = "characters"
HELP = "make character sheets + location plates (Hidrogen image), import an approved image, gate"


def register(p):
    p.add_argument("action", choices=["plan", "make", "import", "show", "gate", "restructure"],
                   help="plan: write characters/prompts.json | make: sheets and plates (paid) | import <file>: an "
                        "image the user approved | show | gate | restructure")
    p.add_argument("items", nargs="*", help="make: ids (BAKER, sheet:BAKER, plate:SHOP); import: the image file")
    add_project_arg(p)
    cmdutil.add_make_args(p)
    cmdutil.add_gate_args(p)
    p.add_argument("--character", default=None, help="import: the character id the image is the sheet of")
    p.add_argument("--location", default=None, help="import: the location id the image is the plate of")
    p.add_argument("--source", default="chatgpt", help="import: where the image was made (default chatgpt)")


def run(args):
    root = project.find_project(args.project)
    if args.action == "plan":
        sp = screenplay.load(root)
        prompts = store.sync_prompts(root, characters.D, characters.build_prompts(root, sp),
                                     rebuild=args.rebuild_prompts)
        for k in characters.resolve(sp, []):
            print("  %-20s -> %s  (%d chars)" % (k, characters.file_for(k), len(prompts.get(k, ""))))
        print("prompts: characters/prompts.json. next: python3 scripts/bb.py characters make --dry-run")
        return 0
    if args.action == "make":
        return cmdutil.finish(characters.make(root, args.items, **cmdutil.make_kwargs(args)),
                              "python3 scripts/bb.py characters gate")
    if args.action == "import":
        if len(args.items) != 1:
            raise UsageError("usage: bb characters import <image file> --character <ID> (or --location <ID>)")
        res = characters.import_image(root, args.items[0], character=args.character, location=args.location,
                                      source=args.source, note=args.note)
        print("registered %s -> %s (source %s; %s)" % (res["key"], res["file"], res["source"], res["checks"]))
        return 0
    if args.action == "show":
        items = characters.status(root)
        if args.json:
            print(json.dumps(items, indent=2, ensure_ascii=False))
        else:
            cmdutil.print_items(items)
        return 0
    if args.action == "gate":
        return cmdutil.gate(root, "characters", args)
    return cmdutil.restructure(root, "characters", args, "python3 scripts/bb.py characters make")
