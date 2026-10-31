"""Shared test setup: a temp folder under <repo>/.tmp, $HOME redirected there, the mock server, the fake key."""
import json
import os
import shutil
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(REPO, "scripts")
BB = os.path.join(SCRIPTS, "bb.py")
FAKE_KEY = "hi_test_0000000000000000fake"
TMP_ROOT = os.path.join(REPO, ".tmp", "tests")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from bizzbell import hidrogen  # noqa: E402
from bizzbell.mock_server import MockHidrogen  # noqa: E402

hidrogen.RETRY_BASE = 0.0


class MockCase(unittest.TestCase):
    """Each test gets a fresh temp dir, HOME, mock server (self.mock) and env pointing at it."""

    behaviours = ()
    with_key = True

    def setUp(self):
        os.makedirs(TMP_ROOT, exist_ok=True)
        self.tmp = tempfile.mkdtemp(dir=TMP_ROOT)
        self._env = dict(os.environ)
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        os.environ["HOME"] = self.home
        for k in list(os.environ):
            if k.startswith("BB_") or k == "HIDROGEN_API_KEY":
                del os.environ[k]
        self.mock = MockHidrogen(list(self.behaviours))
        self.mock.start()
        os.environ["HIDROGEN_API_URL"] = self.mock.url
        if self.with_key:
            os.environ["HIDROGEN_API_KEY"] = FAKE_KEY

    def tearDown(self):
        self.mock.stop()
        os.environ.clear()
        os.environ.update(self._env)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def env(self):
        return dict(os.environ)

    def make_project(self, name="proj", budget=100.0, doctor=True):
        from bizzbell import doctor as doctor_mod, ledger, project
        root = project.init(os.path.join(self.tmp, name), "A 20 s reel for a neighbourhood bakery's festive box",
                            lang="hinglish")
        if doctor:
            doctor_mod.run(root, write=True)
        if budget:
            ledger.set_cap(root, budget, "test")
        return root

    def write(self, root, rel, text):
        p = os.path.join(root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text if isinstance(text, str) else json.dumps(text))
        return p


STORY_RUBRIC = {
    "stage": "story", "title": "Story", "layer": {"kind": "text", "files": ["story.md"]},
    "references": ["brief.md"],
    "questions": [
        {"id": "S1", "text": "Does it open with a hook in the first 3 seconds?", "weight": 2,
         "evidence": "quote the hook"},
        {"id": "S2", "text": "Is every claim backed by the research?", "weight": 2, "hard": True},
        {"id": "S3", "text": "Does it end with the call to action?", "weight": 1},
        {"id": "S4", "text": "Is it at least 5 words long?", "check": "word_count", "args": {"min_words": 5}},
    ],
}

STORY = "# Story\n\nThe baker lifts the lid and the whole lane leans in to smell it.\nOrder your box today.\n"
