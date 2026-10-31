"""Shared fixtures for the media tests: a 6-second gym screenplay, small media rubrics, MediaCase."""
import json
import os

from helpers import MockCase

from bizzbell import project

# A tiny generic project: two live shots and an end card, Hinglish (Devanagari voice text, Roman captions).
SCREENPLAY = {
    "bizzbell": 1, "title": "Morning gym", "slug": "gym-reel", "lang": "hinglish", "aspect": "9:16", "fps": 24,
    "duration": 6,
    "continuity": ["One morning light from the left window in every shot."],
    "bibles": {
        "characters": {"COACH": {"name": "Coach", "real_person": False, "photos": [],
                                 "text": "COACH (30): Indian man, 30, short black hair, trimmed beard, navy t-shirt, "
                                         "grey track pants, a black band on the left wrist."}},
        "locations": {"GYM": {"name": "Gym", "text": "GYM (small, 7 am): rubber floor, a rack of dumbbells on the "
                                                      "right wall, a big window on the left, soft morning light."}},
        "props": {"BOTTLE": {"name": "Bottle", "text": "BOTTLE: plain steel water bottle; no print, no logo."}},
    },
    "voice": {"name": "priya", "candidates": ["priya", "arjun"], "style": "warm and casual, not an announcer",
              "audition_text": "Chalo, shuru karte hain."},
    "music": {"prompt": "light upbeat acoustic bed, 100 bpm", "instrumental": True, "seconds": 6},
    "shots": [
        {"id": "S01", "start": 0, "end": 2, "kind": "live", "source": "keyframe", "screen": "Coach lifts a dumbbell",
         "keyframe_prompt": "Medium shot: the coach stands by the rack holding one dumbbell at his waist.",
         "motion": "He curls the dumbbell once, slowly. He stays in place.", "camera": "handheld",
         "characters": ["COACH"], "location": "GYM", "props": [], "refs": [], "lines": ["L01"]},
        {"id": "S02", "start": 2, "end": 4, "kind": "live", "source": "keyframe", "screen": "Coach drinks water",
         "keyframe_prompt": "Close-up: the coach holds the steel bottle near his chin, smiling.",
         "motion": "He takes one sip and lowers the bottle.", "camera": "locked",
         "characters": ["COACH"], "location": "GYM", "props": ["BOTTLE"], "refs": [], "lines": ["L02"]},
        {"id": "G03", "start": 4, "end": 6, "kind": "graphic", "source": "graphic", "screen": "end card",
         "graphic": {"type": "endcard", "title": "Morning Gym", "cta": "Join today"}, "lines": ["L03"]},
    ],
    "rows": [
        {"t": 0, "shot": "S01", "vo": "Roz subah", "caption": "Roz subah"},
        {"t": 1, "shot": "S01", "vo": "thoda sa", "caption": "thoda sa"},
        {"t": 2, "shot": "S02", "vo": "paani, aur", "caption": "paani, aur"},
        {"t": 3, "shot": "S02", "vo": "smile", "caption": "smile"},
        {"t": 4, "shot": "G03", "vo": "Aaj join karo", "caption": "Aaj join karo"},
        {"t": 5, "shot": "G03", "vo": "", "caption": ""},
    ],
    "lines": [
        {"id": "L01", "shot": "S01", "at": 0.2, "end": 1.9, "text": "Roz subah thoda sa", "tts": "रोज़ सुबह थोड़ा सा"},
        {"id": "L02", "shot": "S02", "at": 2.2, "end": 3.9, "text": "paani, aur smile", "tts": "पानी, और स्माइल"},
        {"id": "L03", "shot": "G03", "at": 4.2, "end": 5.6, "text": "Aaj join karo", "tts": "आज जॉइन करो"},
    ],
}

BIBLE_MD = """# Character bible

## COACH
COACH (30): Indian man, 30, short black hair, trimmed beard, navy t-shirt, grey track pants, a black band on the
left wrist. Fixed details: the wrist band stays on the left wrist.

## GYM
GYM (small, 7 am): rubber floor, a rack of dumbbells on the right wall, a big window on the left.
"""


def media_rubric(layer, files, extra_questions=(), voice_free=False, targets=None):
    """A small media rubric: one hard no-text question plus one quality question (both per item)."""
    qs = [{"id": "Q1", "text": "Is it free of text, logos and number plates?", "weight": 2, "hard": True,
           "quote": False},
          {"id": "Q2", "text": "Does it match what the screenplay asks for?", "weight": 2, "quote": False}]
    if voice_free:
        qs.append({"id": "V1", "text": "Is the music free of any vocals?", "weight": 3, "hard": True,
                   "quote": False, "voice_free": True})
    qs += list(extra_questions)
    r = {"stage": layer, "title": layer, "layer": {"kind": "media", "files": files, "max_files": 4},
         "references": ["screenplay.json"], "questions": qs}
    if targets:
        r["restructure"] = {"targets": targets}
    return r


RUBRICS = {
    "characters": media_rubric("characters", ["characters/sheets/*.png", "characters/plates/*.png"],
                               [{"id": "L1", "text": "Does every character have a sheet?",
                                 "check": "sheets_cover_cast"}]),
    "keyframes": media_rubric("keyframes", ["keyframes/*.png"],
                              [{"id": "L1", "text": "Do the prompts carry the bibles?",
                                "check": "prompts_carry_bibles"},
                               {"id": "L2", "text": "Is light consistent across shots?", "scope": "layer"}],
                              targets=["keyframes/prompts.json"]),
    "clips": media_rubric("clips", ["clips/cut/*.mp4"]),
    "voice": media_rubric("voice", ["audio/vo.wav"],
                          [{"id": "L1", "text": "Is every line placed?", "check": "vo_covers_lines"}]),
    "music": media_rubric("music", ["audio/music_bed.wav"], voice_free=True),
    "mix": media_rubric("mix", ["audio/mix.wav"],
                        [{"id": "L1", "text": "Is it at -14 LUFS?", "check": "audio_loudness",
                          "args": {"files": ["audio/mix.wav"]}}]),
    "version_a": media_rubric("version_a", ["out/A/*.mp4"],
                              [{"id": "L1", "text": "Captions in Roman?", "check": "captions_roman"},
                               {"id": "L2", "text": "No frozen picture?", "check": "no_freeze_frames"}]),
}


class MediaCase(MockCase):
    """MockCase plus a ready gym project (screenplay, bible, rubric overrides, small master size)."""

    def make_media_project(self, name="gym", budget=500.0, screenplay=None, rubrics=True):
        root = self.make_project(name, budget=budget)
        self.write(root, "screenplay.json", screenplay or SCREENPLAY)
        self.write(root, "characters/bible.md", BIBLE_MD)
        if rubrics:
            for k, r in RUBRICS.items():
                self.write(root, "rubrics/%s.json" % k, r)
        with open(os.path.join(root, "bizzbell.json"), encoding="utf-8") as f:
            s = json.load(f)
        s.setdefault("media", {})["width"] = 180
        self.write(root, "bizzbell.json", s)
        for st in ("research", "story", "humanize", "screenplay", "characters", "keyframes"):
            project.mark_stage(root, st, "passed", note="test fixture: the earlier layers passed")
        return root

    def posts(self, prefix):
        return [r for r in self.mock.requests if r["method"] == "POST" and r["path"].startswith(prefix)]

    def quiet(self):
        lines = []
        return lines, lines.append
