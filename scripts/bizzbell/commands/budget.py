"""bb budget show | estimate | set <inr> | raise <inr>: the INR cap. set/raise only on the user's word; estimate
prices the whole film per stage (free) for the budget question."""
from .. import estimate, hidrogen, ledger, project
from ..cli import add_project_arg

NAME = "budget"
HELP = "show the spend, or set/raise the INR cap (only after the user said yes)"


def register(p):
    add_project_arg(p)
    p.add_argument("action", choices=["show", "estimate", "set", "raise"], nargs="?", default="show")
    p.add_argument("amount", nargs="?", type=float, help="INR (set: the new cap; raise: how much to add)")
    p.add_argument("--seconds", type=float, default=None,
                   help="estimate: the film's length when there is no screenplay.json yet (default 30)")
    p.add_argument("--no-quote", action="store_true", help="estimate: use the bizzbell.json rates only")
    p.add_argument("--note", default="", help="why (for example: 'user approved 500 in chat')")
    p.add_argument("--wallet", action="store_true", help="also show the Hidrogen wallet balance (free call)")


def run(args):
    root = project.find_project(args.project)
    if args.action == "estimate":
        print(estimate.format_estimate(estimate.estimate(root, seconds=args.seconds, quote=not args.no_quote)))
        return 0
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
