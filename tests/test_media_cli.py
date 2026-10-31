"""The media commands through bb.py (subprocess): dry run, exit codes, Version A skip, import, gate, and a run of
the skill's own media rubrics (when they exist) over a mock-made project."""
import glob
import os
import subprocess
import sys
import unittest

from helpers import BB, REPO
from test_media_base import MediaCase

from bizzbell import gate, project
from bizzbell.media import characters, clips, keyframes, layers, mix, music, store, version_a, voice


class CliTests(MediaCase):
    def bb(self, *args):
        r = subprocess.run([sys.executable, BB] + list(args), capture_output=True, text=True, env=self.env(),
                           timeout=300)
        return r.returncode, r.stdout, r.stderr

    def test_help_lists_media_commands(self):
        code, out, _err = self.bb("--help")
        self.assertEqual(code, 0)
        for name in ("characters", "keyframes", "clips", "voice", "music", "mix", "version_a"):
            self.assertIn(name, out)

    def test_dry_run_then_make_then_gate(self):
        root = self.make_media_project()
        n0 = len(self.mock.requests)
        code, out, err = self.bb("characters", "make", "-p", root, "--dry-run")
        self.assertEqual(code, 0, err)
        self.assertIn("POST /v1/images/generations", out)
        self.assertIn("dry run: nothing was sent", out)
        self.assertEqual(len(self.mock.requests), n0)
        code, out, err = self.bb("characters", "make", "-p", root)
        self.assertEqual(code, 0, err)
        self.assertIn("next: python3 scripts/bb.py characters gate", out)
        code, out, err = self.bb("characters", "gate", "-p", root)
        self.assertEqual(code, 0, out + err)
        self.assertIn("PASS", out)
        code, out, err = self.bb("gate", "keyframes", "-p", root)          # nothing made yet: friendly usage error
        self.assertEqual(code, 2)
        self.assertIn("nothing to gate", err)

    def test_blocked_exit_code(self):
        root = self.make_media_project()
        self.mock.set_behaviours(["block"])
        code, out, err = self.bb("characters", "make", "COACH", "-p", root)
        self.assertEqual(code, 8, out + err)
        self.assertIn("safety filter", out)

    def test_budget_refusal_exit_code(self):
        root = self.make_media_project(budget=0)
        code, out, err = self.bb("characters", "make", "-p", root)
        self.assertEqual(code, 7)
        self.assertIn("no budget approved", err)

    def test_clips_skip_when_videos_404(self):
        root = self.make_media_project()
        characters.make(root, judge=False, log=lambda *_: None)
        keyframes.make(root, judge=False, log=lambda *_: None)
        self.mock.set_behaviours(["media404"])
        code, out, err = self.bb("clips", "make", "-p", root)
        self.assertEqual(code, 0, err)
        self.assertIn("Version A skipped", out)
        code, out, err = self.bb("status", "-p", root)
        self.assertIn("skipped", out)
        code, out, err = self.bb("version_a", "build", "-p", root)
        self.assertEqual(code, 2)
        self.assertIn("skipped", err)

    def test_import_and_show(self):
        root = self.make_media_project()
        src = os.path.join(self.tmp, "approved.png")
        from bizzbell.media import ff
        ff.run(["-f", "lavfi", "-i", "color=c=0x8899aa:s=320x180", "-frames:v", "1", src])
        code, out, err = self.bb("characters", "import", src, "--character", "COACH", "--source", "chatgpt", "-p",
                                 root)
        self.assertEqual(code, 0, err)
        self.assertIn("sheet:COACH -> characters/sheets/COACH.png", out)
        code, out, err = self.bb("characters", "show", "-p", root)
        self.assertIn("approved", out)

    def test_keyframe_reject_and_approve(self):
        root = self.make_media_project()
        characters.make(root, judge=False, log=lambda *_: None)
        keyframes.make(root, judge=False, log=lambda *_: None)
        code, out, err = self.bb("keyframes", "reject", "S01", "--note", "his left hand has six fingers", "-p", root)
        self.assertEqual(code, 0, err)
        self.assertTrue(glob.glob(os.path.join(root, "keyframes/_rejected/S01*.png")))
        code, out, err = self.bb("keyframes", "make", "S01", "--no-judge", "-p", root)
        self.assertEqual(code, 0, err)
        self.assertIn("his left hand has six fingers", self.posts("/v1/images/generations")[-1]["body"]["prompt"])
        code, out, err = self.bb("keyframes", "approve", "S01", "-p", root)
        self.assertEqual(store.load_registry(root, "keyframes")["items"]["S01"]["status"], "approved")


@unittest.skipUnless(all(os.path.exists(os.path.join(REPO, "rubrics", "%s.json" % r))
                         for r in ("characters", "keyframes", "clips", "voice", "music", "mix")),
                     "the skill's media rubrics are not there yet")
class SkillRubricTests(MediaCase):
    """The skill's own rubrics validate and run over a mock-made project (paths match what the pipeline writes)."""

    def test_skill_rubrics_run(self):
        root = self.make_media_project(rubrics=False)
        log = lambda *_: None                                       # noqa: E731
        characters.make(root, log=log)
        keyframes.make(root, log=log)
        clips.make(root, log=log)
        voice.audition(root, log=log)
        voice.make_takes(root, log=log)
        voice.place(root, log=log)
        music.make(root, log=log)
        mix.build(root, log=log)
        version_a.build(root, log=log)
        for layer in ("characters", "keyframes", "clips", "voice", "music", "mix", layers.version_a_rubric(root)):
            rec, _rolled = layers.run_gate(root, layer)
            self.assertTrue(rec["layer_files"], layer)
            failed_checks = [q["id"] for q in rec["questions"] if q["source"] == "check" and q["value"] < 1 and
                             "not registered" in " ".join(q["evidence"])]
            self.assertEqual(failed_checks, [], layer)
        for layer in ("keyframes", "clips", "music", "mix"):
            self.assertTrue(gate.latest(root, layer)["passed"], layer)
        self.assertIn(project.stage_state(root, "keyframes")["status"], ("passed",))


if __name__ == "__main__":
    unittest.main()
