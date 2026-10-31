"""Media building blocks without the pipeline: ffmpeg helpers, the screenplay reader, captions, local checks."""
import os
import shutil
import tempfile
import unittest

from helpers import TMP_ROOT
from test_media_base import BIBLE_MD, SCREENPLAY, MediaCase

from bizzbell import gate
from bizzbell.errors import UsageError
from bizzbell.media import ff, judging, screenplay, store, version_a


class FFTests(unittest.TestCase):
    def setUp(self):
        os.makedirs(TMP_ROOT, exist_ok=True)
        self.tmp = tempfile.mkdtemp(dir=TMP_ROOT)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def p(self, name):
        return os.path.join(self.tmp, name)

    def test_probe_black_freeze(self):
        ff.run(["-f", "lavfi", "-i", "testsrc=s=96x160:d=2:r=12", "-f", "lavfi", "-i", "sine=d=2", "-shortest",
                "-pix_fmt", "yuv420p", self.p("t.mp4")])
        pr = ff.probe(self.p("t.mp4"))
        self.assertEqual((pr["width"], pr["height"], pr["has_audio"]), (96, 160, True))
        self.assertAlmostEqual(pr["duration"], 2.0, delta=0.2)
        self.assertEqual(ff.black_spans(self.p("t.mp4")), [])
        self.assertEqual(ff.freeze_spans(self.p("t.mp4"), min_dur=0.5), [])
        ff.run(["-f", "lavfi", "-i", "color=c=black:s=96x160:d=2", "-pix_fmt", "yuv420p", self.p("b.mp4")])
        self.assertTrue(ff.black_spans(self.p("b.mp4")))
        ff.run(["-f", "lavfi", "-i", "color=c=0x8090a0:s=96x160:d=2", "-pix_fmt", "yuv420p", self.p("f.mp4")])
        self.assertTrue(ff.freeze_spans(self.p("f.mp4"), min_dur=0.5))

    def test_loudnorm_hits_target_and_ceiling(self):
        ff.run(["-f", "lavfi", "-i", "sine=f=330:d=4", "-af", "volume=-30dB", self.p("quiet.wav")])
        res = ff.loudnorm(self.p("quiet.wav"), self.p("loud.wav"))
        self.assertLessEqual(abs(res["result"]["I"] + 14.0), 1.0)
        self.assertLessEqual(res["result"]["TP"], -1.0)
        self.assertLess(ff.loudness(self.p("quiet.wav"))["I"], -30)

    def test_silence_and_volume(self):
        ff.run(["-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t", "1.5", self.p("s.wav")])
        self.assertLess(ff.max_volume(self.p("s.wav")), -80)
        self.assertTrue(ff.silence_spans(self.p("s.wav"), min_dur=0.5))

    def test_crop_to_aspect_and_sizes(self):
        ff.run(["-f", "lavfi", "-i", "color=c=0x406080:s=200x200", "-frames:v", "1", self.p("sq.png")])
        self.assertTrue(ff.crop_image_to_aspect(self.p("sq.png"), "9:16"))
        pr = ff.probe(self.p("sq.png"))
        self.assertAlmostEqual(pr["width"] / float(pr["height"]), 9 / 16.0, delta=0.02)
        self.assertFalse(ff.crop_image_to_aspect(self.p("sq.png"), "9:16"))
        self.assertEqual(ff.master_size("16:9"), (1920, 1080))
        self.assertEqual(ff.master_size("9:16", {"media": {"width": 360}}), (360, 640))

    def test_missing_file(self):
        with self.assertRaises(Exception):
            ff.probe(self.p("nope.mp4"))


class ScreenplayTests(unittest.TestCase):
    def test_full_schema(self):
        sp = screenplay.Screenplay(SCREENPLAY)
        self.assertEqual([s["id"] for s in sp.shots], ["S01", "S02", "G03"])
        self.assertEqual([s["id"] for s in sp.live_shots()], ["S01", "S02"])
        self.assertEqual(sp.shot("S02")["props"], ["BOTTLE"])
        self.assertEqual(sp.slot("G03"), (4, 6))
        self.assertEqual(sp.lines[0]["tts"], "रोज़ सुबह थोड़ा सा")
        self.assertEqual(sp.line_slot_end(sp.lines[0]), 1.9)
        self.assertEqual(sp.row_captions()[:2], [(0, 1, "Roz subah"), (1, 2, "thoda sa")])
        self.assertEqual(sp.shot("G03")["card"]["cta"], "Join today")
        with self.assertRaises(UsageError):
            sp.shot("S99")

    def test_rows_only_screenplay(self):
        data = {"duration": 4, "bibles": {"characters": {"MAYA": "MAYA (28): short curly hair, red scarf."},
                                          "locations": {"CAFE": "CAFE: wooden tables, warm light."}},
                "rows": [{"t": 0, "shot": "S01", "screen": "Maya sips coffee in the cafe", "vo": "Pehla sip"},
                         {"t": 1, "shot": "S01", "screen": "Maya sips coffee in the cafe", "vo": "sabse acha"},
                         {"t": 2, "shot": "G02", "image": {"source": "graphic"}, "screen": "logo card", "vo": ""},
                         {"t": 3, "shot": "G02", "image": {"source": "graphic"}, "vo": "Aao na"}]}
        sp = screenplay.Screenplay(data)
        self.assertEqual([(s["id"], s["kind"], s["start"], s["end"]) for s in sp.shots],
                         [("S01", "live", 0, 2), ("G02", "graphic", 2, 4)])
        self.assertEqual(sp.shot("S01")["characters"], ["MAYA"])          # inferred from the text
        self.assertEqual(sp.shot("S01")["location"], "CAFE")
        self.assertEqual([(l["id"], l["text"], l["at"]) for l in sp.lines],
                         [("L01", "Pehla sip sabse acha", 0.0), ("L02", "Aao na", 3.0)])

    def test_empty_is_refused(self):
        with self.assertRaises(UsageError):
            screenplay.Screenplay({"duration": 3})
        with self.assertRaises(UsageError):
            screenplay.Screenplay([1, 2])


class CaptionTests(unittest.TestCase):
    def test_chunk_and_ass(self):
        self.assertEqual(version_a.chunk("one two three four", 9), ["one two", "three", "four"])
        tmp = tempfile.mkdtemp(dir=TMP_ROOT)
        try:
            path = os.path.join(tmp, "c.ass")
            version_a.write_ass(path, [(0.0, 1.5, "Hello {there}")], 1080, 1920, [(2.0, 4.0, ["Title", "Go"])])
            with open(path, encoding="utf-8") as f:
                text = f.read()
            self.assertIn("PlayResY: 1920", text)
            self.assertIn("Dialogue: 0,0:00:00.00,0:00:01.50,Default,,0,0,0,,Hello (there)", text)
            self.assertIn("Card,,0,0,0,,Title\\N{\\fs81}Go", text)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(version_a.caption_problems([(0, 1, "Roz"), (1, 2, "रोज़")]), [(1, 2, "रोज़")])


class StoreTests(MediaCase):
    def test_prompts_keep_edits_and_idem_is_stable(self):
        root = self.make_media_project()
        store.sync_prompts(root, "keyframes", {"S01": "a", "S02": "b"})
        p = store.load_prompts(root, "keyframes")
        p["S01"] = "edited"
        from bizzbell import util
        util.write_json(store.prompts_path(root, "keyframes"), p)
        self.assertEqual(store.sync_prompts(root, "keyframes", {"S01": "a", "S03": "c"}),
                         {"S01": "edited", "S02": "b", "S03": "c"})
        self.assertEqual(store.sync_prompts(root, "keyframes", {"S01": "a"}, rebuild=True), {"S01": "a"})
        self.assertEqual(store.idem(root, "x", 1), store.idem(root, "x", 1))
        self.assertNotEqual(store.idem(root, "x", 1), store.idem(root, "x", 2))
        self.assertTrue(store.idem(root, "x").startswith("bb-"))

    def test_consent_rule(self):
        root = self.make_media_project()
        self.assertIn("CONSENT.md", store.consent_problem(root, ["Coach"]))
        self.write(root, "CONSENT.md", "Coach agreed. Film: gym reel. Channels: Instagram.")
        why = store.consent_problem(root, ["Coach"])
        self.assertIn("how long", why)
        self.assertIn("a date", why)
        self.write(root, "CONSENT.md", "Coach agreed. Film: gym reel. Channels: Instagram. How long: 1 year. "
                                       "Date: 2026-10-31.")
        self.assertIsNone(store.consent_problem(root, ["Coach"]))

    def test_voice_free_question_found(self):
        qs = [{"id": "A", "text": "Is the mood right?"}, {"id": "B", "text": "Is it free of vocals?"}]
        self.assertEqual(judging.voice_free_ids(qs), ["B"])
        qs[0]["voice_free"] = True
        self.assertEqual(judging.voice_free_ids(qs), ["A"])
        self.assertEqual(judging.fix_from(None), "")


class CheckTests(MediaCase):
    def ctx(self, root, layer="keyframes", files=("keyframes/*.png",)):
        r = {"stage": layer, "layer": {"kind": "media", "files": list(files)}, "questions": [{"id": "x", "text": "x"}]}
        return gate.GateContext(root, layer, r)

    def test_prompt_checks(self):
        root = self.make_media_project()
        checks = gate.registered_checks()
        from bizzbell.media import keyframes
        sp = screenplay.load(root)
        store.sync_prompts(root, "keyframes", keyframes.build_prompts(sp))
        ctx = self.ctx(root)
        self.assertEqual(checks["prompts_carry_bibles"](ctx)[0], "yes")
        self.assertEqual(checks["prompt_file_no_text"](ctx)[0], "yes")    # "No text, ..." is a negation
        from bizzbell import util
        p = store.load_prompts(root, "keyframes")
        p["S01"] = p["S01"].replace("COACH (30)", "THE COACH") + "\nA sign that reads OPEN hangs on the wall."
        util.write_json(store.prompts_path(root, "keyframes"), p)
        self.assertEqual(checks["prompts_carry_bibles"](ctx)[0], "partly")
        ans, ev = checks["prompt_file_no_text"](ctx)
        self.assertEqual(ans, "no")
        self.assertIn("reads OPEN", ev)

    def test_voice_text_and_captions(self):
        root = self.make_media_project()
        checks = gate.registered_checks()
        ctx = self.ctx(root, "voice", ["audio/vo.wav"])
        self.assertEqual(checks["voice_text_devanagari"](ctx)[0], "yes")
        self.assertEqual(checks["captions_roman"](ctx)[0], "yes")
        self.assertEqual(checks["vo_covers_lines"](ctx)[0], "no")
        self.assertEqual(checks["music_voice_free"](ctx)[0], "no")
        self.assertEqual(checks["sheets_cover_cast"](ctx)[0], "no")
        self.assertTrue(BIBLE_MD)


if __name__ == "__main__":
    unittest.main()
