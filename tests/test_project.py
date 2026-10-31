"""Project layout, settings, model roles, stage status and next stage."""
import os
import unittest

from helpers import MockCase

from bizzbell import project
from bizzbell.errors import ConfigError, UsageError


class ProjectTests(MockCase):
    def test_init_layout(self):
        root = project.init(os.path.join(self.tmp, "bakery"), "Diwali box reel", lang="hinglish", aspect="9:16")
        for rel in ("brief.md", "project.json", "bizzbell.json", "gates", "keyframes", "out/A", "out/B", "rubrics"):
            self.assertTrue(os.path.exists(os.path.join(root, rel)), rel)
        st = project.load_state(root)
        self.assertEqual((st["lang"], st["aspect"], st["stage"]), ("hinglish", "9:16", "brief"))
        s = project.load_settings(root)
        self.assertEqual(s["budget"]["cap_inr"], 0)
        self.assertEqual(s["gate"]["pass_score"], 95)
        self.assertEqual(set(s["models"]), set(project.ROLES))
        self.assertTrue(s["hyperframes"]["version"])
        self.assertIn("Diwali box reel", open(os.path.join(root, "brief.md")).read())

    def test_init_refuses_twice_and_bad_input(self):
        root = project.init(os.path.join(self.tmp, "p"), "x")
        with self.assertRaises(UsageError):
            project.init(root, "x")
        with self.assertRaises(UsageError):
            project.init(os.path.join(self.tmp, "q"), "  ")
        with self.assertRaises(UsageError):
            project.init(os.path.join(self.tmp, "r"), "x", aspect="2:1")

    def test_find_project(self):
        root = project.init(os.path.join(self.tmp, "p"), "x")
        self.assertEqual(project.find_project(root), root)
        os.environ["BB_PROJECT"] = root
        self.assertEqual(project.find_project(), root)
        with self.assertRaises(UsageError):
            project.find_project(self.tmp)

    def test_model_roles(self):
        root = project.init(os.path.join(self.tmp, "p"), "x")
        with self.assertRaises(ConfigError):
            project.model_for(root, "judge")
        self.assertEqual(project.model_for(root, "image"), "image-pro")
        os.environ["BB_IMAGE_MODEL"] = "image-fast"
        self.assertEqual(project.model_for(root, "image"), "image-fast")
        project.update_settings(root, lambda s: s.setdefault("models_chosen", {}).__setitem__(
            "judge", {"id": "some-judge", "reason": "test"}))
        self.assertEqual(project.model_for(root, "judge"), "some-judge")
        with self.assertRaises(ConfigError):
            project.model_for(root, "painter")

    def test_next_stage_flow(self):
        root = project.init(os.path.join(self.tmp, "p"), "x")
        self.assertEqual(project.next_stage(root), "brief")
        from bizzbell import ledger
        ledger.set_cap(root, 100)
        self.assertEqual(project.next_stage(root), "research")
        self.write(root, "research.md", "# Research\n")
        self.assertEqual(project.stage_status(root, "research"), "made")
        self.assertEqual(project.next_stage(root), "research")      # gated: made is not done
        project.mark_stage(root, "research", "passed")
        self.assertEqual(project.next_stage(root), "story")
        self.assertEqual(project.load_state(root)["stage"], "story")
        rep = project.status_report(root)
        self.assertEqual(rep["next"], "story")
        self.assertEqual(len(rep["stages"]), len(project.STAGES))
        with self.assertRaises(UsageError):
            project.mark_stage(root, "nope", "passed")


if __name__ == "__main__":
    unittest.main()
