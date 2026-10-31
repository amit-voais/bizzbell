"""The `bb` command line: discovers subcommands in bizzbell/commands/ and runs one with friendly errors.

Command plugin contract (one file per command, never edit bb.py or this file):
    scripts/bizzbell/commands/<name>.py defines
        NAME = "name"                 the subcommand
        HELP = "one line"             shown in `bb --help`
        def register(p): ...          add arguments to the argparse subparser `p`
        def run(args): ...            do it; return an int exit code (None = 0)
Modules whose file name starts with "_" are skipped. Raise errors.BBError (or a subclass) for expected failures;
the CLI prints "bizzbell: <message>" (redacted) and exits with its exit_code. --debug anywhere shows tracebacks."""
import argparse
import importlib
import pkgutil
import sys
import traceback

from . import __version__, hidrogen
from .errors import BBError

REQUIRED = ("NAME", "HELP", "register", "run")


def discover():
    """[(module)] of valid command modules, sorted by NAME. Broken modules are reported to stderr and skipped."""
    from . import commands as pkg
    found = []
    for m in sorted(pkgutil.iter_modules(pkg.__path__), key=lambda x: x.name):
        if m.name.startswith("_"):
            continue
        try:
            mod = importlib.import_module("%s.%s" % (pkg.__name__, m.name))
        except Exception as e:
            sys.stderr.write("bizzbell: command module %s could not load: %s\n" % (m.name, hidrogen.redact(e)))
            continue
        if all(hasattr(mod, a) for a in REQUIRED):
            found.append(mod)
        else:
            sys.stderr.write("bizzbell: command module %s lacks one of %s; skipped\n" % (m.name, ", ".join(REQUIRED)))
    return sorted(found, key=lambda mod: mod.NAME)


def add_project_arg(p):
    """Standard --project option for commands that work on a project folder."""
    p.add_argument("--project", "-p", default=None,
                   help="project folder (default: $BB_PROJECT or the nearest folder with project.json)")


def build_parser():
    ap = argparse.ArgumentParser(prog="bb", description="Bizzbell: short AI videos and ads through one Hidrogen key.")
    ap.add_argument("--version", action="version", version="bizzbell " + __version__)
    ap.add_argument("--debug", action="store_true", help="show tracebacks for errors")
    sub = ap.add_subparsers(dest="command", metavar="<command>")
    for mod in discover():
        p = sub.add_parser(mod.NAME, help=mod.HELP, description=mod.HELP)
        mod.register(p)
        p.set_defaults(_run=mod.run)
    return ap


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    debug = "--debug" in argv
    argv = [a for a in argv if a != "--debug"]
    ap = build_parser()
    args = ap.parse_args(argv)
    args.debug = debug
    if not getattr(args, "_run", None):
        ap.print_help()
        return 2
    try:
        code = args._run(args)
        return 0 if code is None else int(code)
    except BBError as e:
        if debug:
            sys.stderr.write(hidrogen.redact(traceback.format_exc()))
        sys.stderr.write("bizzbell: %s\n" % hidrogen.redact(e))
        return e.exit_code
    except KeyboardInterrupt:
        sys.stderr.write("bizzbell: stopped\n")
        return 130
    except Exception as e:
        if debug:
            sys.stderr.write(hidrogen.redact(traceback.format_exc()))
            sys.stderr.write("bizzbell: unexpected error: %s\n" % hidrogen.redact(repr(e)))
        else:
            sys.stderr.write("bizzbell: unexpected error: %s. Run again with --debug for details.\n"
                             % hidrogen.redact(repr(e))[:300])
        return 1
