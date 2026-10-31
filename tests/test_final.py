"""Stage 9 (bb final, report.md, share copies, per-version final rubric) and bb demo --mock."""
import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest

from helpers import TMP_ROOT, MockCase

from bizzbell import cli, final, report, util
from bizzbell.errors import UsageError
from bizzbell.media import ff
from bizzbell.mock_server import mp4


class FinalUnitTests(MockCase):
    def test_no_version_yet_is_a_usage_error(self):
        root = self.make_project("empty")
        with self.assertRaises(UsageError):
            final.run(root)

    def test_version_rubric_names_only_its_own_files(self):
        root = self.make_project("rub")
        r = final.version_rubric(root, "B")
        text = json.dumps(r)
        self.assertNotIn("out/A", text)
        self.assertIn("out/B/*_9x16.mp4", r["layer"]["files"])
        fq = [q for q in r["questions"] if q.get("check") == "formats_present"][0]
        self.assertEqual(fq["args"]["folders"], ["out/B"])
        self.assertEqual(r["stage"], "final_b")
        self.assertTrue(os.path.isfile(os.path.join(root, "rubrics", "final_b.json")))

    def test_share_copy_is_h264_aac_and_under_the_limit(self):
        src = self.write(self.tmp, "src.mp4", "")
        with open(src, "wb") as f:
            f.write(mp4(seconds=2.0, width=144, height=256))
        info = final.share_copy(src, os.path.join(self.tmp, "x_share.mp4"), max_mb=1.0)
        self.assertLess(info["mb"], 1.0)
        self.assertEqual((info["width"], info["height"]), (144, 256))
        self.assertTrue(ff.probe(info["path"])["has_audio"])

    def test_final_gate_rolls_up_into_the_final_stage(self):
        from bizzbell import project
        from bizzbell.media import layers
        root = self.make_project("roll")
        slug = util.read_json(os.path.join(root, "project.json"))["slug"]
        self.write(root, "out/B/%s_B_9x16.mp4" % slug, "x")
        self.assertIsNone(layers.rollup(root, "final_b"))             # no final_b gate yet
        self.write(root, "gates/final_b.1.json", {"stage": "final_b", "run": 1, "score": 80.0, "passed": False})
        self.assertIsNone(layers.rollup(root, "final_b"))
        self.assertEqual(project.stage_state(root, "final")["status"], "failed")
        self.write(root, "gates/final_b.2.json", {"stage": "final_b", "run": 2, "score": 97.0, "passed": True})
        self.assertEqual(layers.rollup(root, "final_b"), "final")
        self.assertEqual(project.stage_state(root, "final")["status"], "passed")
        self.assertIn("B 97.0", project.stage_state(root, "final")["note"])

    def test_report_flags_a_claim_missing_from_research(self):
        root = self.make_project("claims")
        self.write(root, "research.md", "## Claims allowed\n\n- C1: Fresh every morning. [S1]\n\n## Sources\n\n"
                                        "- S1: https://example.org/a read 2026-10-01\n")
        self.write(root, "screenplay.json", {"claims": [{"text": "Fresh daily", "source": "research.md C1"},
                                                        {"text": "Best in town", "source": "nowhere"}]})
        text = report.build(root)
        for h in ("## Files", "## Scores", "## Flaws", "## Claims", "## Spend", "## AI label"):
            self.assertIn(h, text)
        self.assertIn("C1: Fresh every morning.", text)
        self.assertIn("S1 https://example.org/a", text)
        self.assertIn("NOT FOUND", text)


class DemoTests(unittest.TestCase):
    """The whole pipeline through the CLI against the in-process mock (Version B skipped to stay quick)."""

    def setUp(self):
        os.makedirs(TMP_ROOT, exist_ok=True)
        self.tmp = tempfile.mkdtemp(dir=TMP_ROOT)
        self._env = dict(os.environ)
        os.environ["HOME"] = os.path.join(self.tmp, "home")
        for k in list(os.environ):
            if k.startswith("BB_") or k.startswith("HIDROGEN_"):
                del os.environ[k]

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_demo_needs_mock_flag(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(cli.main(["demo"]), 2)
        self.assertIn("--mock", err.getvalue())

    def test_demo_runs_stages_0_to_9(self):
        root = os.path.join(self.tmp, "demo")
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(["demo", "--mock", "--no-b", "--width", "180", "--out", root])
        log = out.getvalue()
        self.assertEqual(code, 0, log[-3000:])
        self.assertNotIn("HIDROGEN_API_URL", os.environ)            # the mock URL does not leak out of the demo
        self.assertNotIn("HIDROGEN_API_KEY", os.environ)
        slug = util.read_json(os.path.join(root, "project.json"))["slug"]
        for tag in ("9x16", "1x1", "16x9", "share"):
            p = os.path.join(root, "out", "A", "%s_A_%s.mp4" % (slug, tag))
            self.assertTrue(os.path.isfile(p), p)
        self.assertEqual(ff.probe(os.path.join(root, "out", "A", "%s_A_16x9.mp4" % slug))["width"], 180)
        self.assertTrue(os.path.isfile(os.path.join(root, "gates", "research.r1.json")))   # one restructure round
        state = util.read_json(os.path.join(root, "project.json"))
        self.assertEqual(state["status"], "done")
        self.assertEqual(state["stages"]["final"]["status"], "passed")
        self.assertEqual(state["stages"]["video_b"]["status"], "skipped")
        rep = util.read_text(os.path.join(root, "out", "report.md"))
        self.assertIn("| research | 2 (", rep)
        self.assertIn("final_a", rep)
        self.assertIn("Version B was skipped", rep)
        self.assertIn("Demo finished", log)
        self.assertIn(os.path.join(root, "out", "report.md"), log)


if __name__ == "__main__":
    unittest.main()
