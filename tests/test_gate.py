"""Gate engine: rubric validation, evidence, scoring, passes, hard questions, local checks, media layers."""
import copy
import json
import os
import unittest

from helpers import STORY, STORY_RUBRIC, MockCase, REPO

from bizzbell import gate, hidrogen, project
from bizzbell.errors import BudgetExceeded, ConfigError, UsageError


class RubricTests(unittest.TestCase):
    def test_valid(self):
        gate.validate_rubric(copy.deepcopy(STORY_RUBRIC))

    def test_invalid(self):
        bad = [
            {},
            dict(STORY_RUBRIC, layer={"kind": "audio", "files": ["x"]}),
            dict(STORY_RUBRIC, layer={"kind": "text", "files": []}),
            dict(STORY_RUBRIC, questions=[]),
            dict(STORY_RUBRIC, questions=[{"id": "A", "text": "x"}, {"id": "A", "text": "y"}]),
            dict(STORY_RUBRIC, questions=[{"id": "A", "text": "x", "weight": 0}]),
            dict(STORY_RUBRIC, questions=[{"id": "A", "text": "x", "hard": "yes"}]),
            dict(STORY_RUBRIC, questions=[{"id": "a b", "text": "x"}]),
            dict(STORY_RUBRIC, pass_score=120),
        ]
        for r in bad:
            with self.assertRaises(ConfigError):
                gate.validate_rubric(r)

    def test_skill_rubrics_are_valid(self):
        d = os.path.join(REPO, "rubrics")
        for name in sorted(os.listdir(d)):
            if name.endswith(".json"):
                with open(os.path.join(d, name)) as f:
                    gate.validate_rubric(json.load(f), where=name)


class ScoringTests(unittest.TestCase):
    QS = [{"id": "A", "text": "a", "weight": 3}, {"id": "B", "text": "b", "weight": 1, "hard": True}]

    def test_score_and_combine(self):
        p1 = {"A": {"answer": "yes"}, "B": {"answer": "partly"}}
        p2 = {"A": {"answer": "no"}, "B": {"answer": "yes"}}
        v = gate.combine(self.QS, [p1, p2])
        self.assertEqual(v, {"A": 0.5, "B": 0.75})
        self.assertEqual(gate.score(self.QS, v), 56.2)
        p3 = {"A": {"answer": "yes"}, "B": {"answer": "no"}}
        self.assertEqual(gate.combine(self.QS, [p1, p2, p3]), {"A": 1.0, "B": 0.5})

    def test_validate_answers(self):
        good = {"answers": [{"id": "A", "answer": "Yes", "evidence": "x"}, {"id": "B", "answer": "no",
                                                                            "evidence": "y"}]}
        self.assertEqual(gate.validate_answers(good, self.QS)["A"]["answer"], "yes")
        for bad in ({"answers": [{"id": "A", "answer": "yes", "evidence": "x"}]},
                    {"answers": [{"id": "A", "answer": "maybe", "evidence": "x"}, {"id": "B", "answer": "no",
                                                                                  "evidence": "y"}]},
                    {"answers": [{"id": "A", "answer": "yes", "evidence": ""}, {"id": "B", "answer": "no",
                                                                               "evidence": "y"}]},
                    {"answers": [{"id": "Z", "answer": "yes", "evidence": "x"}]},
                    "nope"):
            with self.assertRaises(ValueError):
                gate.validate_answers(bad, self.QS)

    def test_evidence_found(self):
        hay = "The baker lifts the lid.\nThe whole lane leans in to smell it."
        self.assertTrue(gate.evidence_found('"the whole  lane leans in"', hay))
        self.assertTrue(gate.evidence_found('"The baker lifts ... leans in to smell"', hay))
        self.assertFalse(gate.evidence_found('"a dragon flies over the shop"', hay))
        self.assertTrue(gate.evidence_found("The baker lifts the lid", hay))

    def test_evidence_found_short_quote_first(self):
        # a short quote ("0-3 s") used to be skipped, and the prose BETWEEN two quotes was then paired as a quote
        hay = "0-3 s: the hook. The baker lifts the lid.\n3-6 s: the whole lane leans in."
        self.assertTrue(gate.evidence_found('The hook sits at "0-3 s" and says "The baker lifts the lid"', hay))
        self.assertTrue(gate.evidence_found('Timed "0-3 s"', hay))
        self.assertFalse(gate.evidence_found('Timed "9-12 s"', hay))
        self.assertFalse(gate.evidence_found('"0-3 s" and "a dragon flies over"', hay))

    def test_evidence_found_quote_holding_quotes(self):
        hay = 'At 12 s the voice says cut to "Star it" now, and the end card shows the logo.'
        self.assertTrue(gate.evidence_found('"cut to "Star it" now"', hay))
        self.assertTrue(gate.evidence_found('The CTA: "cut to \\"Star it\\" now"', hay))
        self.assertTrue(gate.evidence_found('“cut to "Star it" now”', hay))
        self.assertFalse(gate.evidence_found('"pay today "Buy it" before noon"', hay))
        self.assertFalse(gate.evidence_found('"the dragon roars "Star it" loudly"', hay))


class GateRunTests(MockCase):
    def setUp(self):
        MockCase.setUp(self)
        self.root = self.make_project()
        self.write(self.root, "rubrics/story.json", STORY_RUBRIC)
        self.write(self.root, "story.md", STORY)

    def test_pass(self):
        rec = gate.run(self.root, "story")
        self.assertTrue(rec["passed"])
        self.assertEqual(rec["score"], 100.0)
        self.assertEqual(rec["passes"], 2)
        self.assertEqual(rec["run"], 1)
        self.assertTrue(os.path.exists(os.path.join(self.root, "gates", "story.1.json")))
        st = project.load_state(self.root)
        self.assertEqual(st["stages"]["story"]["status"], "passed")
        self.assertEqual(st["scores"]["story"], 100.0)
        self.assertGreater(rec["cost_inr"], 0)
        judge = project.model_for(self.root, "judge")
        self.assertEqual(rec["model"], judge)
        self.assertNotEqual(judge, project.model_for(self.root, "writer"))
        body = [q for q in self.mock.requests if q["path"] == "/v1/chat/completions"][-1]["body"]
        self.assertIn("system_prompt", body)
        s4 = [q for q in rec["questions"] if q["id"] == "S4"][0]
        self.assertEqual(s4["source"], "check")

    def test_fail_low(self):
        self.mock.set_behaviours(["judge_always_low"])
        rec = gate.run(self.root, "story")
        self.assertFalse(rec["passed"])
        self.assertEqual(rec["score"], 50.0)
        self.assertEqual(gate.failed_questions(rec)[0]["id"], "S1")
        text = gate.format_result(rec)
        self.assertIn("FAIL", text)
        self.assertIn("restructure story", text)
        self.assertEqual(gate.run(self.root, "story")["run"], 2)

    def test_hard_no_fails_despite_high_score(self):
        r = copy.deepcopy(STORY_RUBRIC)
        r["questions"] = [{"id": "Q%d" % i, "text": "question %d?" % i, "weight": 10} for i in range(5)] + \
            [{"id": "H", "text": "Is the frame free of logos?", "weight": 1, "hard": True}]
        self.write(self.root, "rubrics/story.json", r)
        self.mock.set_behaviours(["judge_hard_no"])
        rec = gate.run(self.root, "story")
        self.assertGreaterEqual(rec["score"], 95)
        self.assertEqual(rec["hard_failed"], ["H"])
        self.assertFalse(rec["passed"])

    def test_disagreement_triggers_third_pass(self):
        self.mock.set_behaviours(["judge_disagree"])
        rec = gate.run(self.root, "story")
        self.assertEqual(rec["passes"], 3)
        self.assertEqual(rec["score"], 100.0)

    def test_bad_json_is_reasked(self):
        self.mock.set_behaviours(["judge_bad_json_once"])
        rec = gate.run(self.root, "story")
        self.assertTrue(rec["passed"])

    def test_yes_without_real_quote_is_downgraded(self):
        ctx = gate.GateContext(self.root, "story", gate.load_rubric(self.root, "story"))
        qs = [q for q in STORY_RUBRIC["questions"] if not q.get("check")]
        answers = {"S1": {"answer": "yes", "evidence": '"a dragon flies over the bakery"'},
                   "S2": {"answer": "yes", "evidence": '"the whole lane leans in"'},
                   "S3": {"answer": "no", "evidence": "missing"}}
        out = gate._verify(ctx, qs, answers)
        self.assertEqual(out["S1"]["answer"], "partly")
        self.assertEqual(out["S2"]["answer"], "yes")

    def test_local_only_rubric_spends_nothing(self):
        r = {"stage": "story", "layer": {"kind": "text", "files": ["story.md"]},
             "questions": [{"id": "L1", "text": "Long enough?", "check": "word_count", "args": {"min_words": 5}},
                           {"id": "L2", "text": "No banned words?", "check": "contains_none",
                            "args": {"words": ["guaranteed"]}},
                           {"id": "L3", "text": "Unknown check?", "check": "not_registered"}]}
        self.write(self.root, "rubrics/story.json", r)
        rec = gate.run(self.root, "story")
        self.assertEqual(rec["model"], "local")
        self.assertEqual(rec["cost_inr"], 0)
        self.assertEqual(round(rec["score"], 1), 66.7)
        self.assertFalse([q for q in self.mock.requests if q["method"] == "POST"])

    def test_registered_check_decorator(self):
        @gate.check("test_always_partly")
        def _c(ctx):
            return "partly", "half there"
        r = {"stage": "story", "layer": {"kind": "text", "files": ["story.md"]},
             "questions": [{"id": "C", "text": "custom?", "check": "test_always_partly"}]}
        self.write(self.root, "rubrics/story.json", r)
        self.assertEqual(gate.run(self.root, "story")["score"], 50.0)
        self.assertIn("files_exist", gate.registered_checks())

    def test_media_layer_uses_media_judge(self):
        r = {"stage": "keyframes", "layer": {"kind": "media", "files": ["keyframes/*.png"], "max_files": 2},
             "references": ["brief.md"],
             "questions": [{"id": "K1", "text": "Does every frame match its row?", "weight": 2},
                           {"id": "K2", "text": "Is every frame free of text and logos?", "hard": True},
                           {"id": "K3", "text": "Do the files exist?", "check": "files_exist"}]}
        self.write(self.root, "rubrics/keyframes.json", r)
        png = hidrogen.image("x")[0]
        for i in range(3):
            with open(os.path.join(self.root, "keyframes", "s%d.png" % i), "wb") as f:
                f.write(png)
        rec = gate.run(self.root, "keyframes")
        self.assertTrue(rec["passed"])
        judge_posts = [q for q in self.mock.requests if q["path"] == "/v1/media/judge" and q["method"] == "POST"]
        self.assertEqual(len(judge_posts), 2)
        self.assertEqual(len(judge_posts[0]["body"]["content"]), 3)       # text + 2 files (max_files)

    def test_missing_layer_and_rubric(self):
        os.remove(os.path.join(self.root, "story.md"))
        with self.assertRaises(UsageError):
            gate.run(self.root, "story")
        with self.assertRaises(UsageError):
            gate.run(self.root, "humanize")

    def test_no_budget_no_judge(self):
        from bizzbell import ledger
        ledger.set_cap(self.root, 0)
        with self.assertRaises(BudgetExceeded):
            gate.run(self.root, "story")
        self.assertFalse([q for q in self.mock.requests if q["path"] == "/v1/chat/completions"])


if __name__ == "__main__":
    unittest.main()
