"""bb status: what is done, what is next, last scores, spend."""
import json

from .. import project
from ..cli import add_project_arg

NAME = "status"
HELP = "show stages, scores, spend and what to do next"


def register(p):
    add_project_arg(p)
    p.add_argument("--json", action="store_true", help="print the status as JSON")


def run(args):
    rep = project.status_report(project.find_project(args.project))
    if args.json:
        print(json.dumps(rep, indent=2, ensure_ascii=False))
        return 0
    print("%s  (%s, %s)  %s" % (rep["slug"], rep["lang"], rep["aspect"], rep["project"]))
    for r in rep["stages"]:
        score = "" if r["score"] is None else "%.1f" % r["score"]
        extra = ("  rounds %d" % r["rounds"]) if r["rounds"] else ""
        note = ("  (%s)" % r["note"]) if r["note"] else ""
        print("  %-3s %-26s %-12s %6s%s%s" % (r["n"], r["title"], r["status"], score, extra, note))
    s = rep["spend"]
    print("spend: INR %.2f spent, %.2f reserved, cap %.2f%s"
          % (s["spent_inr"], s["reserved_inr"], s["cap_inr"], "" if s["approved"] else " (no budget approved yet)"))
    if rep["next"]:
        print("next: %s - %s" % (rep["next"], rep["hint"]))
    else:
        print("all stages done")
    return 0
