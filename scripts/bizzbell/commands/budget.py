"""bb budget show | set <inr> | raise <inr>: the INR cap. set/raise only on the user's word."""
from .. import hidrogen, ledger, project
from ..cli import add_project_arg

NAME = "budget"
HELP = "show the spend, or set/raise the INR cap (only after the user said yes)"


def register(p):
    add_project_arg(p)
    p.add_argument("action", choices=["show", "set", "raise"], nargs="?", default="show")
    p.add_argument("amount", nargs="?", type=float, help="INR (set: the new cap; raise: how much to add)")
    p.add_argument("--note", default="", help="why (for example: 'user approved 500 in chat')")
    p.add_argument("--wallet", action="store_true", help="also show the Hidrogen wallet balance (free call)")


def run(args):
    root = project.find_project(args.project)
    if args.action in ("set", "raise"):
        if args.amount is None:
            print("usage: bb budget %s <inr>" % args.action)
            return 2
        s = ledger.set_cap(root, args.amount, args.note) if args.action == "set" else \
            ledger.raise_cap(root, args.amount, args.note)
        print("cap is now INR %.2f" % s["cap_inr"])
    s = ledger.Ledger(root).summary()
    print("cap INR %.2f%s | spent %.2f | reserved %.2f | left %.2f | %d calls"
          % (s["cap_inr"], "" if s["approved"] else " (not approved)", s["spent_inr"], s["reserved_inr"],
             s["remaining_inr"], s["calls"]))
    for k, v in sorted(s["by_kind"].items()):
        print("  %-6s INR %.2f" % (k, v))
    if args.wallet:
        print("wallet: INR %s" % hidrogen.balance_inr())
    return 0
