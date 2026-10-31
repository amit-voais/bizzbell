"""The Hidrogen gateway down (HTTP 502/503): every paid media command exits 9 with a friendly line and spends
nothing; a stage is not "made" until its outputs exist; Idempotency-Keys follow the model and the request body."""
import contextlib
import io
import json
import os
import re
import unittest

from test_media_base import MediaCase

from bizzbell import cli, hidrogen, ledger, project
from bizzbell.media import characters, keyframes, store


class OutageCase(MediaCase):
    def bb(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def spend(self, root):
        s = ledger.Ledger(root).summary()
        return s["spent_inr"], s["reserved_inr"]


class OutageExitCodeTests(OutageCase):
    def assert_outage(self, root, *argv):
        before = self.spend(root)
        code, out, err = self.bb(*(list(argv) + ["-p", root]))
        self.assertEqual(code, 9, "%s: exit %d\n%s%s" % (" ".join(argv), code, out, err))
        self.assertIn("Hidrogen service is unavailable", err)
        self.assertIn("Nothing more was spent", err)
        self.assertIn("try again later", err.lower())
        self.assertNotIn("bad_gateway", err)              # the raw reply is not shown
        self.assertEqual(self.spend(root), before, "an outage must not count as spend")

    def test_every_paid_media_command_exits_9(self):
        root = self.make_media_project()
        lines, log = self.quiet()
        characters.make(root, judge=False, log=log)
        keyframes.make(root, judge=False, log=log)
        for b in ("down502", "down503"):
            self.mock.set_behaviours([b])
            self.assert_outage(root, "characters", "make", "--redo")
            self.assert_outage(root, "keyframes", "make", "--redo")
            self.assert_outage(root, "clips", "make")
            self.assert_outage(root, "voice", "audition", "priya", "arjun")
            self.assert_outage(root, "voice", "takes")
            self.assert_outage(root, "music", "make")

    def test_a_flaky_gateway_still_succeeds(self):
        root = self.make_media_project()
        self.mock.set_behaviours(["flaky"])
        code, out, err = self.bb("characters", "make", "-p", root, "--no-judge")
        self.assertEqual(code, 0, out + err)

    def test_client_raises_unavailable(self):
        self.mock.set_behaviours(["down502"])
        with self.assertRaises(hidrogen.Unavailable) as cm:
            hidrogen.image("a plate", model="image-pro", idem="bb-test")
        self.assertEqual(cm.exception.status, 502)
        self.assertEqual(cm.exception.exit_code, 9)

    def test_skill_documents_exit_9(self):
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "SKILL.md"),
                  encoding="utf-8") as f:
            self.assertTrue(re.search(r"\n\| 9 \|.*(502|503)", f.read()), "SKILL.md has no exit 9 row")


class MadeOnlyWithOutputsTests(OutageCase):
    def test_failed_characters_make_is_not_made(self):
        root = self.make_media_project()
        project.mark_stage(root, "characters", "todo")
        self.mock.set_behaviours(["down502"])
        code, _out, _err = self.bb("characters", "make", "-p", root)
        self.assertEqual(code, 9)
        self.assertEqual(project.stage_status(root, "characters"), "todo")
        code, out, _err = self.bb("status", "-p", root)
        row = [ln for ln in out.splitlines() if "Characters" in ln][0]
        self.assertNotIn("made", row)

    def test_characters_made_when_every_sheet_and_plate_exists(self):
        root = self.make_media_project()
        project.mark_stage(root, "characters", "todo")
        self.assertEqual(project.stage_status(root, "characters"), "todo")    # only the bible
        lines, log = self.quiet()
        characters.make(root, judge=False, log=log)
        self.assertEqual(project.stage_status(root, "characters"), "made")
        sp = characters.screenplay.load(root)
        os.remove(os.path.join(root, characters.file_for(characters.resolve(sp, [])[-1])))
        self.assertEqual(project.stage_status(root, "characters"), "todo")    # one plate missing

    def test_keyframes_made_only_when_every_live_shot_has_one(self):
        root = self.make_media_project()
        lines, log = self.quiet()
        characters.make(root, judge=False, log=log)
        project.mark_stage(root, "keyframes", "todo")
        keyframes.make(root, judge=False, log=log)
        self.assertEqual(project.stage_status(root, "keyframes"), "made")
        sid = characters.screenplay.load(root).live_shots()[0]["id"]
        os.remove(os.path.join(root, "keyframes", "%s.png" % sid))
        self.assertEqual(project.stage_status(root, "keyframes"), "todo")

    def test_audio_made_only_with_the_mix(self):
        root = self.make_media_project()
        project.mark_stage(root, "audio", "todo")
        self.write(root, "audio/vo.wav", "not really audio")
        self.assertEqual(project.stage_status(root, "audio"), "todo")
        self.write(root, "audio/mix.wav", "not really audio")
        self.assertEqual(project.stage_status(root, "audio"), "made")


class IdempotencyKeyTests(OutageCase):
    def test_key_follows_model_and_body(self):
        root = self.make_media_project()
        base = store.idem(root, "image", "sheet:COACH", "ph1", 1, "", model="image-pro", body={"prompt": "a"})
        self.assertEqual(base, store.idem(root, "image", "sheet:COACH", "ph1", 1, "", model="image-pro",
                                          body={"prompt": "a"}))                          # identical retry
        self.assertNotEqual(base, store.idem(root, "image", "sheet:COACH", "ph1", 1, "", model="image-fast",
                                             body={"prompt": "a"}))
        self.assertNotEqual(base, store.idem(root, "image", "sheet:COACH", "ph1", 1, "", model="image-pro",
                                             body={"prompt": "a", "image_size": "4K"}))
        self.assertTrue(base.startswith("bb-"))

    def _image_keys(self):
        return [r["idempotency_key"] for r in self.mock.requests
                if r["method"] == "POST" and r["path"] == "/v1/images/generations"]

    def test_identical_retry_reuses_the_key_and_a_new_model_gets_a_fresh_one(self):
        root = self.make_media_project()
        self.mock.set_behaviours(["down502", "cache_errors"])
        self.assertEqual(self.bb("characters", "make", "COACH", "-p", root, "--no-judge")[0], 9)
        first = set(self._image_keys())
        self.assertEqual(len(first), 1)                       # one key across the client's own retries
        self.mock.set_behaviours(["cache_errors"])            # back up, but the failure is cached by key
        self.assertEqual(self.bb("characters", "make", "COACH", "-p", root, "--no-judge")[0], 9)
        self.assertEqual(set(self._image_keys()), first)     # an identical retry stays idempotent
        with open(os.path.join(root, "bizzbell.json"), encoding="utf-8") as f:
            s = json.load(f)
        s["models"]["image"] = "image-fast"
        self.write(root, "bizzbell.json", s)
        code, out, err = self.bb("characters", "make", "COACH", "-p", root, "--no-judge")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(len(set(self._image_keys()) - first), 1)
        self.assertTrue(os.path.exists(os.path.join(root, characters.file_for("sheet:COACH"))))

    def test_changed_reference_gets_a_fresh_key(self):
        root = self.make_media_project()
        lines, log = self.quiet()
        characters.make(root, judge=False, log=log)
        self.mock.set_behaviours(["down502", "cache_errors"])
        sid = characters.screenplay.load(root).live_shots()[0]["id"]
        self.assertEqual(self.bb("keyframes", "make", sid, "-p", root, "--no-judge")[0], 9)
        first = set(self._image_keys())
        self.mock.set_behaviours(["cache_errors"])
        sheet = os.path.join(root, characters.file_for("sheet:COACH"))
        from bizzbell.media import ff
        ff.run(["-f", "lavfi", "-i", "color=c=0x445566:s=128x72", "-frames:v", "1", "-y", sheet])
        code, out, err = self.bb("keyframes", "make", sid, "-p", root, "--no-judge")
        self.assertEqual(code, 0, out + err)
        self.assertTrue(set(self._image_keys()) - first)


if __name__ == "__main__":
    unittest.main()
