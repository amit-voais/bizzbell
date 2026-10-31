"""Restructure loop: fail -> restructure -> pass, old versions kept, round limit, extra round, guards."""
import os
import unittest

from helpers import STORY, STORY_RUBRIC, MockCase

from bizzbell import gate, project, restructure
from bizzbell.errors import RoundsExhausted, UsageError


class RestructureTests(MockCase):
    def setUp(self):
        MockCase.setUp(self)
        self.root = self.make_project()
        self.write(self.root, "rubrics/story.json", STORY_RUBRIC)
        self.write(self.root, "story.md", STORY)

    def test_loop_low_then_high(self):
        self.mock.set_behaviours(["judge_low_then_high"])
        self.assertFalse(gate.run(self.root, "story")["passed"])
        res = restructure.run(self.root, "story")
        self.assertEqual(res["round"], 1)
        self.assertEqual(res["files"], ["story.md"])
        self.assertEqual(res["model"], project.model_for(self.root, "restructure"))
        self.assertIn("opus", res["model"])
        old = os.path.join(self.root, "story.md.r1")
        self.assertEqual(open(old).read(), STORY)
        self.assertIn("revised", open(os.path.join(self.root, "story.md")).read())
        self.assertTrue(os.path.exists(os.path.join(self.root, "gates", "story.r1.json")))
        self.assertEqual(project.stage_state(self.root, "story")["status"], "restructured")
        body = [q for q in self.mock.requests if q["path"] == "/v1/chat/completions"][-1]["body"]
        user = body["messages"][0]["content"]
        self.assertIn("<failed_questions>", user)
        self.assertIn("missing:", user)              # the judge's evidence is passed on
        rec = gate.run(self.root, "story")
        self.assertTrue(rec["passed"])
        self.assertIn("next:", restructure.format_result(res))

    def test_round_limit_then_extra(self):
        self.mock.set_behaviours(["judge_always_low"])
        for i in range(3):
            gate.run(self.root, "story")
            self.assertEqual(restructure.run(self.root, "story")["round"], i + 1)
        rec = gate.run(self.root, "story")
        self.assertIn("rounds used up", gate.format_result(rec, 3, 3))
        with self.assertRaises(RoundsExhausted) as cm:
            restructure.run(self.root, "story")
        self.assertIn("ask the user", str(cm.exception))
        self.assertEqual(cm.exception.exit_code, 4)
        res = restructure.run(self.root, "story", extra=True, note="user said one more")
        self.assertEqual((res["round"], res["allowed"]), (4, 4))
        self.assertTrue(os.path.exists(os.path.join(self.root, "story.md.r4")))

    def test_guards(self):
        with self.assertRaises(UsageError):
            restructure.run(self.root, "story")                       # no gate yet
        gate.run(self.root, "story")
        with self.assertRaises(UsageError):
            restructure.run(self.root, "story")                       # already passed
        self.mock.set_behaviours(["judge_always_low"])
        gate.run(self.root, "story")
        self.write(self.root, "story.md", STORY + "\nedited by hand\n")
        with self.assertRaises(UsageError) as cm:
            restructure.run(self.root, "story")                       # layer changed since the gate
        self.assertIn("changed", str(cm.exception))

    def test_targets_from_rubric(self):
        r = dict(STORY_RUBRIC, restructure={"targets": ["story.md", "notes.json"]})
        self.write(self.root, "rubrics/story.json", r)
        self.write(self.root, "notes.json", '{"a": 1}')
        self.mock.set_behaviours(["judge_always_low"])
        gate.run(self.root, "story")
        res = restructure.run(self.root, "story")
        self.assertEqual(res["files"], ["notes.json", "story.md"])
        self.assertTrue(os.path.exists(os.path.join(self.root, "notes.json.r1")))


if __name__ == "__main__":
    unittest.main()
