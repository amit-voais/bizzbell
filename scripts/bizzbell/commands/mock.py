"""bb mock: run the offline mock Hidrogen server (no key, no spend)."""
from .. import mock_server
from ..errors import UsageError

NAME = "mock"
HELP = "run the offline mock Hidrogen server for tests and demos"


def register(p):
    p.add_argument("--port", type=int, default=0, help="port (0 = any free port)")
    p.add_argument("--behaviour", default="", help="comma list: " + ", ".join(sorted(mock_server.BEHAVIOURS)))


def run(args):
    wanted = [b for b in args.behaviour.split(",") if b]
    unknown = [b for b in wanted if b not in mock_server.BEHAVIOURS]
    if unknown:
        raise UsageError("unknown mock behaviour(s): %s (known: %s)" % (", ".join(unknown),
                                                                          ", ".join(sorted(mock_server.BEHAVIOURS))))
    mock_server.serve_forever(args.port, wanted)
    return 0
