"""bb mark <stage|layer> <status>: record a status by hand (for example skipped when /v1/videos is not live, or
passed when the user accepts a layer after the restructure rounds are used up).

The media sub-layers voice, music, mix (stage audio) and clips, version_a (stage video_a) can be marked too; their
stage then follows them as it does after `bb gate <layer>`."""
from .. import gate, project
from ..cli import add_project_arg
from ..media.layers import rollup

NAME = "mark"
HELP = "set a stage's or a layer's status by hand (todo, made, skipped, passed, failed)"


def register(p):
    p.add_argument("stage", choices=[s["id"] for s in project.STAGES] + sorted(project.LAYER_PARENT),
                   help="a stage id, or a media layer: %s" % ", ".join(
                       "%s (stage %s)" % (k, v) for k, v in sorted(project.LAYER_PARENT.items())))
    p.add_argument("status", choices=["todo", "made", "skipped", "passed", "failed"])
    add_project_arg(p)
    p.add_argument("--note", default="", help="why (shown in bb status)")


def run(args):
    root = project.find_project(args.project)
    fields = {"note": args.note}
    if args.status == "passed":          # the user accepts the files as they are now
        snap = gate.snapshot(root, args.stage)
        if snap:
            fields["layer"] = snap
    project.mark_stage(root, args.stage, args.status, **fields)
    rollup(root, args.stage)
    parent = project.LAYER_PARENT.get(args.stage)
    nxt = project.next_stage(root)
    print("%s: %s%s%s" % (args.stage, args.status,
                          (" (stage %s: %s)" % (parent, project.stage_status(root, parent))) if parent else "",
                          ("; next: %s" % nxt) if nxt else "; all stages done"))
    return 0
