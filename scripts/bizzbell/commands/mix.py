"""bb mix: VO over the ducked music bed, two-pass loudnorm to -14 LUFS / <= -1 dBTP, verified (ffmpeg only)."""
import json
import os

from .. import project, util
from ..cli import add_project_arg
from ..media import cmdutil, mix

NAME = "mix"
HELP = "mix VO + music (ducking, two-pass loudnorm to -14 LUFS, <= -1 dBTP, verified), gate"


def register(p):
    p.add_argument("action", choices=["build", "show", "gate"], nargs="?", default="build",
                   help="build (free, ffmpeg) | show (the loudness report) | gate")
    add_project_arg(p)
    cmdutil.add_gate_args(p)


def run(args):
    root = project.find_project(args.project)
    if args.action == "build":
        rep = mix.build(root)
        print("report: audio/mix_report.json. next: python3 scripts/bb.py mix gate")
        return 0 if rep["ok"] else 1
    if args.action == "show":
        rep = util.read_json(os.path.join(root, "audio", "mix_report.json"), None)
        print(json.dumps(rep, indent=2, ensure_ascii=False) if rep else "no mix yet: python3 scripts/bb.py mix")
        return 0
    return cmdutil.gate(root, "mix", args)
