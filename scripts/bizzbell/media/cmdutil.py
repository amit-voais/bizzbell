"""Shared argument and output helpers for the media commands (characters, keyframes, clips, voice, music, mix,
version_a). Every paid action takes --dry-run; gate and restructure go through media.layers."""
import json

from . import layers, store


def add_make_args(p):
    p.add_argument("--dry-run", action="store_true",
                   help="print every request that would be sent and the ledger check; send nothing")
    p.add_argument("--no-judge", action="store_true",
                   help="keep takes on their local checks alone (no paid per-take judge)")
    p.add_argument("--fix", default="", help="a correction added to the prompt of every take made now")
    p.add_argument("--redo", action="store_true", help="make them again even when they are in place")
    p.add_argument("--rebuild-prompts", action="store_true",
                   help="rebuild prompts.json from screenplay.json (drops hand edits and restructured prompts)")
    p.add_argument("--extra-take", type=int, default=0, metavar="N",
                   help="N takes past budget.max_takes - ONLY after the user said yes")


def add_gate_args(p):
    p.add_argument("--passes", type=int, default=None, help="gate: judge passes (default from bizzbell.json)")
    p.add_argument("--extra", action="store_true",
                   help="restructure: one more round past the limit - ONLY after the user said yes")
    p.add_argument("--note", default="", help="a note (restructure --extra, reject, approve, import)")
    p.add_argument("--json", action="store_true", help="print JSON")


def make_kwargs(args):
    return {"dry_run": args.dry_run, "rebuild_prompts": args.rebuild_prompts, "redo": args.redo, "fix": args.fix,
            "extra": args.extra_take, "judge": not args.no_judge}


def gate(root, layer, args):
    """Run the gate for a layer and print it. Exit code 0 pass, 3 fail."""
    rec, rolled = layers.run_gate(root, layer, passes=args.passes)
    if args.json:
        print(json.dumps(rec, indent=2, ensure_ascii=False))
    else:
        print(layers.format_gate(root, rec, rolled))
    return 0 if rec["passed"] else 3


def restructure(root, layer, args, then):
    from .. import restructure as rs
    res = layers.run_restructure(root, layer, extra=args.extra, note=args.note)
    print(rs.format_result(res).replace("next: python3 scripts/bb.py gate %s" % layer,
                                        "next: %s, then python3 scripts/bb.py gate %s" % (then, layer)))
    return 0


def print_items(items, out=print):
    """One line per registry item: id, status, file, score, note."""
    if not items:
        out("  (nothing yet)")
    for k, it in sorted(items.items()):
        score = it.get("score")
        out("  %-16s %-9s %-34s %s%s" % (k, it.get("status", "todo"), it.get("file") or "-",
                                       ("score %.1f  " % score) if isinstance(score, (int, float)) else "",
                                       (it.get("note") or "")[:90]))


def finish(items, next_hint):
    """Print a status count and the next step. Exit code 8 when an item is blocked (rephrase, then run again)."""
    if not isinstance(items, dict) or "plan" in items:
        return 0
    counts = {}
    for k, it in items.items():
        if isinstance(it, dict):
            counts[it.get("status", "todo")] = counts.get(it.get("status", "todo"), 0) + 1
    print("status: " + ", ".join("%d %s" % (n, st) for st, n in sorted(counts.items())))
    if counts.get("blocked"):
        print("some items were blocked by the safety filter (charged 0): rephrase their prompts as plain visible "
              "behaviour in prompts.json and run make once more")
        return 8
    if counts.get("flagged") or counts.get("rejected"):
        print("some items did not pass within max_takes: show the user, then accept, edit by hand, or allow "
              "another take (--extra-take 1)")
    print("next: " + next_hint)
    return 0


def summary(root, d):
    reg = store.load_registry(root, d)
    return {k: v.get("status") for k, v in reg["items"].items()}
