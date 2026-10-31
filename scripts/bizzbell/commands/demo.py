"""bb demo --mock: the whole pipeline, stages 0-9, against the offline mock gateway (no key, no network, no spend).

Starts the mock in this process, copies examples/bakery-diwali into a new project, approves a budget inside the
demo only, and runs every stage with the real commands: the four text gates (the mock judge fails the first one
until it is restructured, so one restructure round always runs), characters, keyframes, voice, music, mix,
clips, Version A, Version B (HyperFrames, real local render), and bb final. Prints where the files are."""
import glob
import os
import shutil
import sys
import time

from .. import hidrogen, project, util
from ..errors import BBError, UsageError

NAME = "demo"
HELP = "run stages 0-9 end to end against the offline mock (bb demo --mock); no key, no spend"

FAKE_KEY = "hi_test_0000000000000000fake"
EXAMPLE = os.path.join(util.ROOT_DIR, "examples", "bakery-diwali")
TEXT_LAYERS = ("research", "story", "humanize", "screenplay")


def register(p):
    p.add_argument("--mock", action="store_true", help="required: run against the offline mock gateway")
    p.add_argument("--out", default="", help="project folder to create (default: <skill>/.tmp/demo/<time>)")
    p.add_argument("--width", type=int, default=360, help="Version A frame width in px (small = fast)")
    p.add_argument("--no-b", action="store_true", help="skip Version B (HyperFrames) for a quick run")
    p.add_argument("--samples", type=int, default=2, help="frames for Version B's repeatability check")


class Demo(object):
    """Runs bb commands in-process against one project; stops on the first unexpected exit code."""

    def __init__(self, root, out=None):
        self.root = root
        self.out = out or (lambda s: sys.stdout.write(s + "\n"))
        self.steps = []

    def bb(self, *argv, **kw):
        from .. import cli
        ok = kw.get("ok", (0,))
        argv = list(argv)
        if kw.get("project", True):
            argv += ["-p", self.root]
        self.out("\n$ bb %s" % " ".join(a if a != self.root else "<demo>" for a in argv))
        sys.stdout.flush()
        code = cli.main(argv)
        sys.stdout.flush()
        self.steps.append((" ".join(argv[:2]), code))
        if code not in ok:
            raise BBError("demo stopped: bb %s exited %d (see above)" % (" ".join(argv[:2]), code))
        return code

    def gate_loop(self, layer, remake=None):
        """Gate; on a fail restructure (and remake), then gate again; at most 3 rounds."""
        for _ in range(4):
            if self.bb("gate", layer, ok=(0, 3)) == 0:
                return
            self.bb("restructure", layer)
            if remake:
                remake()
        raise BBError("demo stopped: %s did not pass after 3 restructure rounds" % layer)


def _prepare(root, width):
    """Copy the example's text layers into the new project and make the frames small."""
    names = [n for n in os.listdir(EXAMPLE) if n.endswith((".md", ".json")) and n != "README.md"]
    for n in names:
        shutil.copy2(os.path.join(EXAMPLE, n), os.path.join(root, n))
    for src in glob.glob(os.path.join(EXAMPLE, "characters", "*.md")):
        shutil.copy2(src, os.path.join(root, "characters", os.path.basename(src)))

    def f(s):
        s.setdefault("media", {})["width"] = int(width) // 2 * 2
    project.update_settings(root, f)


def _hyperframes(root):
    from ..hf import runner
    return runner.available(root)


def run(args):
    if not args.mock:
        raise UsageError("bb demo only runs against the offline mock gateway: python3 scripts/bb.py demo --mock")
    if not os.path.isfile(os.path.join(EXAMPLE, "screenplay.json")):
        raise UsageError("the example project is missing: %s" % EXAMPLE)
    from ..mock_server import MockHidrogen
    sp = util.read_json(os.path.join(EXAMPLE, "screenplay.json"), {}) or {}
    root = os.path.abspath(args.out or os.path.join(util.ROOT_DIR, ".tmp", "demo", time.strftime("%Y%m%d-%H%M%S")))
    if os.path.exists(root) and os.listdir(root):
        raise UsageError("%s already exists and is not empty: pick another --out" % root)
    saved = {k: os.environ.get(k) for k in ("HIDROGEN_API_URL", "HIDROGEN_API_KEY", "BB_PROJECT")}
    mock = MockHidrogen(["judge_low_then_high"])
    url = mock.start()
    try:
        os.environ["HIDROGEN_API_URL"] = url
        os.environ["HIDROGEN_API_KEY"] = FAKE_KEY
        os.environ.pop("BB_PROJECT", None)
        if not hidrogen.api_url().startswith("http://127.0.0.1:"):
            raise BBError("demo refused: the gateway URL is not the local mock")
        print("Bizzbell demo against the offline mock at %s (no key, no network, no money)" % url)
        d = Demo(root)
        # 0. brief + budget (the budget is approved here because this is the mock: a real run asks the user)
        d.bb("init", root, "--brief", "A %s s Hinglish reel for a neighbourhood bakery's Diwali box"
             % sp.get("duration", 20), "--lang", sp.get("lang", "hinglish"), "--aspect", sp.get("aspect", "9:16"),
             "--slug", sp.get("slug", "bakery-diwali"), project=False)
        _prepare(root, args.width)
        d.bb("doctor")
        d.bb("budget", "set", "500", "--note", "demo against the offline mock: no real money")
        # 1-4. text layers; the mock judge fails the first gate until a restructure round has run
        for layer in TEXT_LAYERS:
            d.gate_loop(layer)
        # 5-7. media through the mock
        d.bb("characters", "make")
        d.gate_loop("characters", lambda: d.bb("characters", "make"))
        d.bb("keyframes", "make")
        d.gate_loop("keyframes", lambda: d.bb("keyframes", "make"))
        d.bb("voice", "audition")
        d.bb("voice", "takes")
        d.bb("voice", "place")
        d.gate_loop("voice", lambda: (d.bb("voice", "takes"), d.bb("voice", "place")))
        d.bb("music", "make")
        d.gate_loop("music", lambda: d.bb("music", "make"))
        d.bb("mix", "build")
        d.gate_loop("mix", lambda: d.bb("mix", "build"))
        # 8A. Version A
        d.bb("clips", "make")
        d.gate_loop("clips", lambda: d.bb("clips", "make"))
        d.bb("version_a", "build")
        d.gate_loop("version_a", lambda: d.bb("version_a", "build"))
        # 8B. Version B (HyperFrames, local and free)
        ok, why = (False, "--no-b was given") if args.no_b else _hyperframes(root)
        if ok:
            d.bb("version_b", "--quality", "draft", "--samples", str(max(1, args.samples)))
            d.gate_loop("video_b", lambda: d.bb("version_b", "--quality", "draft", "--samples",
                                                str(max(1, args.samples))))
        else:
            print("\nVersion B skipped: %s" % why)
            d.bb("mark", "video_b", "skipped", "--note", "demo: %s" % why)
        # 9. final
        d.bb("final")
        d.bb("status")
        _where(root)
        return 0
    finally:
        mock.stop()
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _where(root):
    print("\nDemo finished. Everything is in %s" % root)
    for rel in sorted(glob.glob(os.path.join(root, "out", "*", "*.mp4"))):
        print("  %s  (%.1f MB)" % (rel, os.path.getsize(rel) / 1048576.0))
    print("  %s" % os.path.join(root, "out", "report.md"))
    print("No real gateway was called and no money was spent: every paid call went to the local mock, and the INR "
          "in the ledger and the report are the mock's play prices.")
