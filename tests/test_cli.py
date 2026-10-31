"""The bb CLI end to end (subprocess against the mock), command discovery, friendly errors, doctor, key."""
import contextlib
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest

from helpers import BB, FAKE_KEY, STORY, STORY_RUBRIC, MockCase

from bizzbell import cli, doctor


def bb(*args, **kw):
    env = kw.pop("env", None)
    inp = kw.pop("input", None)
    r = subprocess.run([sys.executable, BB] + list(args), capture_output=True, text=True, env=env, input=inp,
                       timeout=120)
    return r.returncode, r.stdout, r.stderr


class CliTests(MockCase):
    def test_help_lists_commands(self):
        code, out, _ = bb("--help", env=self.env())
        self.assertEqual(code, 0)
        for c in ("init", "status", "budget", "gate", "restructure", "doctor", "key", "mark", "mock"):
            self.assertIn(c, out)

    def test_full_flow(self):
        p = os.path.join(self.tmp, "gym")
        code, out, err = bb("init", p, "--brief", "15 s reel for a gym's new year offer", "--lang", "en",
                            env=self.env())
        self.assertEqual(code, 0, err)
        code, out, err = bb("doctor", "-p", p, env=self.env())
        self.assertEqual(code, 0, out + err)
        self.assertIn("claude-opus-4-5", out)
        self.assertNotIn(FAKE_KEY, out + err)
        settings = json.load(open(os.path.join(p, "bizzbell.json")))
        self.assertEqual(settings["models_chosen"]["restructure"]["id"], "claude-opus-4-5")
        self.assertEqual(settings["endpoints"]["videos"], "live")
        code, out, _ = bb("status", "-p", p, env=self.env())
        self.assertIn("next: brief", out)
        bb("budget", "set", "100", "-p", p, "--note", "user said 100", env=self.env())
        os.makedirs(os.path.join(p, "rubrics"), exist_ok=True)
        with open(os.path.join(p, "rubrics", "story.json"), "w") as f:
            json.dump(STORY_RUBRIC, f)
        with open(os.path.join(p, "story.md"), "w") as f:
            f.write(STORY)
        self.mock.set_behaviours(["judge_low_then_high"])
        code, out, _ = bb("gate", "story", "-p", p, env=self.env())
        self.assertEqual(code, 3, out)
        self.assertIn("FAIL", out)
        code, out, err = bb("restructure", "story", "-p", p, env=self.env())
        self.assertEqual(code, 0, err)
        code, out, _ = bb("gate", "story", "-p", p, env=self.env())
        self.assertEqual(code, 0, out)
        self.assertIn("PASS", out)
        code, out, _ = bb("status", "--json", "-p", p, env=self.env())
        rep = json.loads(out)
        self.assertEqual([r for r in rep["stages"] if r["id"] == "story"][0]["status"], "passed")
        self.assertGreater(rep["spend"]["spent_inr"], 0)
        code, out, _ = bb("mark", "video_a", "skipped", "--note", "videos not live", "-p", p, env=self.env())
        self.assertEqual(code, 0)
        code, out, _ = bb("budget", "-p", p, "--wallet", env=self.env())
        self.assertIn("wallet: INR 1000.0", out)

    def test_friendly_errors(self):
        code, out, err = bb("status", "-p", os.path.join(self.tmp, "nope"), env=self.env())
        self.assertEqual(code, 2)
        self.assertIn("bizzbell:", err)
        self.assertNotIn("Traceback", err)
        code, out, err = bb("status", "-p", os.path.join(self.tmp, "nope"), "--debug", env=self.env())
        self.assertIn("Traceback", err)

    def test_budget_refusal_exit_code(self):
        p = os.path.join(self.tmp, "p")
        bb("init", p, "--brief", "x", env=self.env())
        bb("doctor", "-p", p, env=self.env())
        with open(os.path.join(p, "rubrics", "story.json"), "w") as f:
            json.dump(STORY_RUBRIC, f)
        with open(os.path.join(p, "story.md"), "w") as f:
            f.write(STORY)
        code, out, err = bb("gate", "story", "-p", p, env=self.env())
        self.assertEqual(code, 7)
        self.assertIn("no budget approved", err)

    def test_key_command(self):
        env = self.env()
        env.pop("HIDROGEN_API_KEY", None)
        code, out, err = bb("key", "--check", env=env)
        self.assertEqual(code, 1)
        code, out, err = bb("key", "--stdin", env=env, input=FAKE_KEY + "\n")
        self.assertEqual(code, 0, err)
        self.assertNotIn(FAKE_KEY, out + err)
        path = os.path.join(self.home, ".config", "hidrogen", "key.env")
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        code, out, err = bb("key", "--check", env=env)
        self.assertEqual((code, out.strip()), (0, "key: present (not shown)"))

    def test_doctor_without_key_and_without_project(self):
        env = self.env()
        env.pop("HIDROGEN_API_KEY", None)
        code, out, err = bb("doctor", env=env)
        self.assertEqual(code, 1)
        self.assertIn("missing", out)
        code, out, err = bb("doctor", env=self.env())
        self.assertEqual(code, 0, out)
        self.assertTrue(os.path.exists(os.path.join(self.home, ".config", "bizzbell", "settings.json")))


class DiscoveryTests(unittest.TestCase):
    def test_new_command_file_is_discovered(self):
        from bizzbell import commands
        d = tempfile.mkdtemp(dir=os.path.join(os.path.dirname(BB), "..", ".tmp"))
        with open(os.path.join(d, "hello.py"), "w") as f:
            f.write('NAME = "hello"\nHELP = "say hello"\n'
                    'def register(p):\n    p.add_argument("--who", default="world")\n'
                    'def run(args):\n    print("hello " + args.who)\n    return 0\n')
        with open(os.path.join(d, "broken.py"), "w") as f:
            f.write('NAME = "broken"\n')
        with open(os.path.join(d, "_private.py"), "w") as f:
            f.write("raise SystemExit('must not be imported')\n")
        commands.__path__.append(d)
        try:
            names = [m.NAME for m in cli.discover()]
            self.assertIn("hello", names)
            self.assertNotIn("broken", names)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(cli.main(["hello", "--who", "bakery"]), 0)
            self.assertEqual(buf.getvalue().strip(), "hello bakery")
        finally:
            commands.__path__.remove(d)
            import shutil
            shutil.rmtree(d, ignore_errors=True)


class DoctorPickTests(unittest.TestCase):
    def test_opus_preferred_highest_version(self):
        p = doctor.pick_models(["gpt-4o", "claude-opus-4-1", "claude-opus-4-5", "claude-sonnet-4-5", "image-pro"])
        self.assertEqual(p["restructure"][0], "claude-opus-4-5")
        self.assertNotEqual(p["judge"][0], p["writer"][0])
        self.assertNotEqual(p["judge"][0], p["restructure"][0])

    def test_no_opus_falls_back(self):
        p = doctor.pick_models(["gemini-2.5-flash", "gemini-2.5-pro", "video", "voice-studio"])
        self.assertEqual(p["restructure"][0], "gemini-2.5-pro")
        self.assertIn("no Opus", p["restructure"][1])

    def test_single_and_none(self):
        p = doctor.pick_models(["only-model"])
        self.assertEqual(p["judge"][0], "only-model")
        self.assertEqual(doctor.pick_models(["image-pro", "video"]), {})


class DoctorMockTests(MockCase):
    behaviours = ("media404", "no_opus")

    def test_records_missing_media_and_fallback_model(self):
        root = self.make_project(budget=0)
        from bizzbell import project
        s = project.load_settings(root)
        self.assertEqual(s["endpoints"]["videos"], "missing")
        self.assertNotIn("opus", s["models_chosen"]["restructure"]["id"])
        self.assertFalse([c for c in self.mock.charges])


if __name__ == "__main__":
    unittest.main()
