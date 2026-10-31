"""Version B, for real: a 3-second example built, checked and rendered headless with the pinned HyperFrames.

Skipped cleanly when npx / the pinned HyperFrames / ffmpeg cannot run (offline, no Node), or when
BB_SKIP_RENDER_TESTS=1. Takes about two minutes. $HOME is left alone here on purpose: npx and HyperFrames keep
their caches (the package, its headless Chrome, fonts) under it. No Hidrogen call goes anywhere but the mock."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from helpers import BB, FAKE_KEY, TMP_ROOT
from test_hf import HAS_FFMPEG, make_project

from bizzbell import doctor, gate, hidrogen, ledger, util
from bizzbell.hf import audit, compose, formats, qa, render, repeat, runner
from bizzbell.mock_server import MockHidrogen

RATIOS = ["9x16", "1x1", "16x9"]


def _skip_reason():
    if os.environ.get("BB_SKIP_RENDER_TESTS"):
        return "BB_SKIP_RENDER_TESTS is set"
    if not HAS_FFMPEG:
        return "ffmpeg is not installed"
    ok, why = runner.available(None)
    return "" if ok else "HyperFrames cannot run here (offline or no Node): %s" % why


class RenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        why = _skip_reason()
        if why:
            raise unittest.SkipTest(why)
        os.makedirs(TMP_ROOT, exist_ok=True)
        cls.tmp = tempfile.mkdtemp(dir=TMP_ROOT)
        cls.root = make_project(cls.tmp, "render3s")
        env = dict(os.environ)
        env.pop("BB_PROJECT", None)
        cls.run_out = subprocess.run([sys.executable, BB, "version_b", "-p", cls.root, "--ratios", "9:16,1:1,16:9",
                                      "--quality", "draft", "--samples", "3"],
                                     capture_output=True, text=True, env=env, timeout=1800)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(getattr(cls, "tmp", ""), ignore_errors=True)

    def test_command_succeeded(self):
        self.assertEqual(self.run_out.returncode, 0, self.run_out.stdout + self.run_out.stderr)
        self.assertIn("next: python3 scripts/bb.py gate video_b", self.run_out.stdout)

    def test_videos(self):
        for r in RATIOS:
            path = render.output_path(self.root, r)
            self.assertTrue(os.path.isfile(path), path)
            info = render.probe(path)
            f = formats.FORMATS[r]
            self.assertEqual((info["width"], info["height"]), (f["w"], f["h"]))
            self.assertAlmostEqual(info["duration"], 3.0, delta=0.15)
            self.assertTrue(info["has_audio"], "the voice track is mixed in")
        self.assertFalse(os.path.exists(render.output_path(self.root, "4x5")))

    def test_qa_record(self):
        data = qa.load(self.root)
        self.assertEqual(data["pin"], runner.pin(self.root))
        for r in RATIOS:
            rec = data["ratios"][r]
            self.assertTrue(qa.fresh(self.root, r, data))
            self.assertTrue(rec["text_ok"], rec)
            self.assertFalse(rec["hf_check"]["browser_skipped"])
            self.assertGreater(rec["bounds"]["checked"], 0)
            self.assertTrue(rec["repeat_ok"], rec["repeat"])
            self.assertEqual(rec["repeat"]["order_b"], repeat.shuffled(rec["repeat"]["times"]))
            self.assertNotEqual(rec["repeat"]["order_b"], rec["repeat"]["times"])
            self.assertTrue(rec["video"]["path"].endswith("_B_%s.mp4" % r))

    def test_gate_uses_both_checks(self):
        saved = dict(os.environ)
        try:
            with MockHidrogen() as m:
                os.environ["HIDROGEN_API_URL"] = m.url
                os.environ["HIDROGEN_API_KEY"] = FAKE_KEY
                hidrogen.RETRY_BASE = 0.0
                doctor.run(self.root, write=True)
                ledger.set_cap(self.root, 50, "test")
                rec = gate.run(self.root, "video_b")
        finally:
            os.environ.clear()
            os.environ.update(saved)
        q = {x["id"]: x for x in rec["questions"]}
        self.assertEqual(q["VB15"]["value"], 1.0, q["VB15"]["evidence"])
        self.assertEqual(q["VB16"]["value"], 1.0, q["VB16"]["evidence"])
        self.assertEqual(q["VB15"]["source"], "check")
        self.assertEqual(q["VB14"]["value"], 1.0, q["VB14"]["evidence"])     # captions.ass is Roman

    def _copy(self, name):
        dst = os.path.join(self.tmp, name)
        shutil.copytree(os.path.join(self.root, "hf", "9x16"), dst)
        return dst

    def test_bounds_catches_text_outside_the_safe_zone(self):
        bad = self._copy("bad_bounds")
        page = util.read_text(os.path.join(bad, "index.html"))
        util.write_text(os.path.join(bad, "index.html"),
                        page.replace("</style>", ".bb-cap-row { bottom: 0 !important; }\n</style>", 1))
        res = audit.bounds(bad, "9x16")
        self.assertFalse(res["ok"])
        self.assertIn("outside_safe_zone", [i["code"] for i in res["issues"]])

    def test_repeat_catches_a_clock(self):
        bad = self._copy("bad_clock")
        page = util.read_text(os.path.join(bad, "index.html"))
        # 40 stripes of random grey: two page loads cannot come out alike (one random hue could, by luck)
        noise = ('<div id="bb-noise" style="position:absolute;left:0;top:0;width:100%;height:50%;z-index:9"></div>'
                 '\n<script>var n = document.getElementById("bb-noise");'
                 'for (var i = 0; i < 40; i++) { var d = document.createElement("div");'
                 'd.style.cssText = "height:2.5%;background:rgb(" + Array(3).join(String(Math.floor('
                 'Math.random() * 256)) + ",") + Math.floor(Math.random() * 256) + ")"; n.appendChild(d); }'
                 '</script>\n</body>')
        util.write_text(os.path.join(bad, "index.html"), page.replace("</body>", noise, 1))
        res = repeat.run(bad, os.path.join(self.tmp, "bad_clock_qa"), 3.0, n=2)
        self.assertFalse(res["ok"], res)
        self.assertTrue(res["differing"])


class OfflineBehaviourTests(unittest.TestCase):
    def test_unavailable_is_reported(self):
        saved = dict(os.environ)
        runner._CACHE.clear()
        try:
            os.environ["PATH"] = "/nonexistent"
            orig = runner.npx
            runner.npx = lambda: None
            ok, why = runner.available(None)
            self.assertFalse(ok)
            self.assertIn("npx", why)
            with self.assertRaises(runner.Unavailable):
                runner.run(["--version"])
        finally:
            runner.npx = orig
            runner._CACHE.clear()
            os.environ.clear()
            os.environ.update(saved)

    def test_compose_needs_no_node(self):
        tmp = tempfile.mkdtemp(dir=TMP_ROOT)
        try:
            root = make_project(tmp)
            self.assertIn("9x16", compose.build(root, "9:16")["ratios"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
