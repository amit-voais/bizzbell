"""bb key: save the Hidrogen key from a hidden prompt to ~/.config/hidrogen/key.env (chmod 600)."""
import getpass
import sys

from .. import hidrogen

NAME = "key"
HELP = "save your Hidrogen API key (hidden prompt; never echoed)"


def register(p):
    p.add_argument("--stdin", action="store_true", help="read the key from stdin (for a password manager pipe)")
    p.add_argument("--check", action="store_true", help="only say whether a key is present")


def run(args):
    if args.check:
        print("key: present (not shown)" if hidrogen.has_key() else "key: missing")
        return 0 if hidrogen.has_key() else 1
    value = sys.stdin.readline() if args.stdin else getpass.getpass("Hidrogen API key (hidden): ")
    path = hidrogen.save_key(value)
    print("key saved to %s (mode 600). It is never shown." % path)
    return 0
