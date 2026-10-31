"""bb key: save the Hidrogen key from a hidden prompt to ~/.config/hidrogen/key.env (chmod 600)."""
import getpass
import sys

from .. import hidrogen

NAME = "key"
HELP = "save your Hidrogen API key (hidden prompt; never echoed)"


def register(p):
    p.add_argument("--stdin", action="store_true", help="read the key from stdin (a password manager pipe); also "
                   "used on its own when stdin is not a terminal")
    p.add_argument("--check", action="store_true", help="only say whether a key is present")


def run(args):
    if args.check:
        print("key: present (not shown)" if hidrogen.has_key() else "key: missing")
        return 0 if hidrogen.has_key() else 1
    piped = args.stdin or not sys.stdin.isatty()     # a pipe has no echo to hide: read it without getpass's warning
    value = sys.stdin.readline() if piped else getpass.getpass("Hidrogen API key (hidden): ")
    path = hidrogen.save_key(value)
    print("key saved to %s (mode 600). It is never shown." % path)
    return 0
