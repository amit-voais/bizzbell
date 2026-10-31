"""The media pipeline against the mock: characters -> keyframes -> clips -> voice -> music -> mix -> Version A,
plus the guards (budget, dry run, consent, 404 skip, safety block, retakes, voice-free music, restructure)."""
import json
import os
import unittest

from test_media_base import SCREENPLAY, MediaCase

from bizzbell import hidrogen, ledger, project, util
from bizzbell.errors import BudgetExceeded, UsageError
from bizzbell.media import (characters, clips, ff, keyframes, layers, mix, music, store, version_a,
                            voice)


def _copy(d):
    return json.loads(json.dumps(d))


class PipelineTests(MediaCase):
    def test_whole_pipeline(self):
        root = self.make_media_project()
        out, log = self.quiet()
        characters.make(root, log=log)
        for f in ("characters/sheets/COACH.png", "characters/plates/GYM.png"):
            self.assertTrue(os.path.exists(os.path.join(root, f)), f)
        self.assertTrue(layers.run_gate(root, "characters")[0]["passed"])

        keyframes.make(root, log=log)
        kf = self.posts("/v1/images/generations")[-1]["body"]          # S02: sheet + plate + previous keyframe
        self.assertEqual(len(kf["references"]), 3)
        self.assertIn(SCREENPLAY["bibles"]["characters"]["COACH"]["text"], kf["prompt"])
        self.assertIn(SCREENPLAY["bibles"]["props"]["BOTTLE"]["text"], kf["prompt"])
        self.assertIn("Image 3: the previous shot's approved keyframe", kf["prompt"])
        reg = store.load_registry(root, "keyframes")["items"]
        self.assertEqual({k: v["status"] for k, v in reg.items()}, {"S01": "accepted", "S02": "accepted"})
        self.assertTrue(layers.run_gate(root, "keyframes")[0]["passed"])

        clips.make(root, log=log)
        vid = self.posts("/v1/videos")[-1]["body"]
        self.assertTrue(vid["first_frame"].startswith("data:image/png;base64,"))
        self.assertTrue(4 <= vid["seconds"] <= 10)
        cut = ff.probe(os.path.join(root, "clips/cut/S01.mp4"))
        self.assertFalse(cut["has_audio"])                              # the model's sound is discarded
        self.assertAlmostEqual(cut["duration"], 2.0, delta=0.15)
        pick = store.load_registry(root, "clips")["items"]["S01"]["pick"]
        self.assertAlmostEqual(pick["start"], 0.3)

        res = voice.audition(root, log=log)
        self.assertEqual(res["chosen"], "priya")
        self.assertEqual(len(res["ranking"]), 2)
        voice.make_takes(root, log=log)
        tts = [r["body"] for r in self.posts("/v1/audio/speech")]
        self.assertIn("रोज़ सुबह थोड़ा सा", [b["input"] for b in tts])      # Devanagari goes to the voice
        timing = voice.place(root, log=log)
        self.assertEqual([l["id"] for l in timing["lines"]], ["L01", "L02", "L03"])
        self.assertAlmostEqual(ff.duration(os.path.join(root, "audio/vo.wav")), 6.0, delta=0.05)

        music.make(root, log=log)
        mbody = self.posts("/v1/music")[-1]["body"]
        self.assertTrue(mbody["instrumental"])
        self.assertIn("no vocals", mbody["prompt"])
        self.assertAlmostEqual(ff.duration(os.path.join(root, "audio/music_bed.wav")), 6.0, delta=0.05)

        rep = mix.build(root, log=log)
        self.assertTrue(rep["ok"], rep)
        self.assertLessEqual(abs(rep["result"]["I"] + 14.0), 1.0)
        self.assertLessEqual(rep["result"]["TP"], -1.0)
        self.assertEqual(rep["ducking"], mix.DUCK)

        for layer in ("voice", "music", "mix"):
            layers.run_gate(root, layer)
        self.assertEqual(project.stage_state(root, "audio")["status"], "passed")

        rep = version_a.build(root, log=log)
        self.assertEqual(rep["file"], "out/A/%s_A_9x16.mp4" % project.load_state(root)["slug"])
        p = ff.probe(os.path.join(root, rep["file"]))
        self.assertAlmostEqual(p["duration"], 6.0, delta=0.15)
        self.assertTrue(p["has_audio"])
        self.assertEqual((p["width"], p["height"]), (180, 320))
        self.assertEqual([s["used"] for s in rep["shots"]], ["clip", "clip", "card"])
        self.assertEqual(rep["caption_method"], "ass")
        ass = util.read_text(os.path.join(root, "out/A/captions.ass"))
        self.assertIn("Roz subah", ass)
        self.assertIn("Morning Gym", ass)
        self.assertLessEqual(abs(rep["loudness"]["I"] + 14.0), 1.0)

        layers.run_gate(root, "clips")
        rec, rolled = layers.run_gate(root, "version_a")
        self.assertTrue(rec["passed"], rec)
        self.assertEqual(rolled, "video_a")
        self.assertEqual(project.stage_state(root, "video_a")["status"], "passed")

        # every paid POST carried an Idempotency-Key and was reserved in the ledger
        paid = [r for r in self.mock.requests if r["method"] == "POST" and r["path"] != "/v1/media/quote"]
        self.assertTrue(all(r["idempotency_key"] for r in paid))
        entries = ledger.Ledger(root).entries()
        self.assertEqual(len([e for e in entries if e["status"] != "released"]), len(self.mock.charges))
        self.assertTrue(self.posts("/v1/media/quote"))                  # quoted before paying

    def test_drawtext_fallback(self):
        root = self.make_media_project()
        out, log = self.quiet()
        characters.make(root, judge=False, log=log)
        keyframes.make(root, judge=False, log=log)
        clips.make(root, judge=False, log=log)
        voice.make_takes(root, judge=False, log=log)
        voice.place(root, log=log)
        mix.build(root, log=log)                       # VO only: no music bed
        os.environ["BB_NO_SUBTITLES"] = "1"
        rep = version_a.build(root, log=log)
        self.assertEqual(rep["caption_method"], "drawtext")
        self.assertTrue(ff.probe(os.path.join(root, rep["file"]))["has_audio"])
        self.assertFalse(self.posts("/v1/media/judge"))                # --no-judge: no paid judge


class GuardTests(MediaCase):
    def test_dry_run_sends_nothing(self):
        root = self.make_media_project()
        out, log = self.quiet()
        characters.make(root, judge=False, log=lambda *_: None)
        keyframes.make(root, judge=False, log=lambda *_: None)
        before = len(self.mock.requests)
        characters.make(root, redo=True, dry_run=True, log=log)
        keyframes.make(root, redo=True, dry_run=True, log=log)
        clips.make(root, dry_run=True, log=log)
        voice.audition(root, dry_run=True, log=log)
        voice.make_takes(root, dry_run=True, log=log)
        music.make(root, dry_run=True, log=log)
        self.assertEqual(len(self.mock.requests), before)
        text = "\n".join(out)
        for endpoint in ("/v1/images/generations", "/v1/videos", "/v1/audio/speech", "/v1/music"):
            self.assertIn("POST " + endpoint, text)
        self.assertIn("<file keyframes/S01.png>", text)
        self.assertIn("fits under the cap", text)
        self.assertEqual(text.count("dry run: nothing was sent"), 6)
        self.assertNotIn(hidrogen.key(), text)

    def test_no_budget_refuses_and_dry_run_says_why(self):
        root = self.make_media_project(budget=0)
        out, log = self.quiet()
        characters.make(root, dry_run=True, log=log)
        self.assertIn("no budget approved yet", "\n".join(out))
        with self.assertRaises(BudgetExceeded):
            characters.make(root, log=log)
        self.assertFalse(self.posts("/v1/images"))

    def test_real_person_needs_consent(self):
        sp = _copy(SCREENPLAY)
        sp["bibles"]["characters"]["COACH"]["real_person"] = True
        root = self.make_media_project(screenplay=sp)
        with self.assertRaises(UsageError) as cm:
            characters.make(root, ["COACH"], log=lambda *_: None)
        self.assertIn("CONSENT.md", str(cm.exception))
        self.assertFalse(self.posts("/v1/images"))
        self.write(root, "CONSENT.md", "Who: Coach (the gym owner). Film: morning gym reel. Channels: Instagram. "
                                       "How long: 12 months. Date: 2026-10-31.")
        characters.make(root, ["COACH"], log=lambda *_: None)
        self.assertIn("real photos", self.posts("/v1/images")[-1]["body"]["prompt"])

    def test_import_from_chatgpt(self):
        root = self.make_media_project()
        src = os.path.join(self.tmp, "download.png")
        ff.run(["-f", "lavfi", "-i", "color=c=0x8899aa:s=320x180", "-frames:v", "1", src])
        res = characters.import_image(root, src, character="COACH", source="chatgpt")
        self.assertEqual(res["file"], "characters/sheets/COACH.png")
        it = characters.status(root)["sheet:COACH"]
        self.assertEqual((it["status"], it["source"]), ("approved", "chatgpt"))
        characters.make(root, ["COACH"], log=lambda *_: None)          # the approved import is kept
        self.assertFalse(self.posts("/v1/images"))
        with self.assertRaises(UsageError):
            characters.import_image(root, src, character="NOBODY")

    def test_missing_bible_md(self):
        root = self.make_media_project()
        os.remove(os.path.join(root, "characters/bible.md"))
        with self.assertRaises(UsageError):
            characters.make(root, log=lambda *_: None)


class VideoNotLiveTests(MediaCase):
    def test_404_marks_version_a_skipped(self):
        root = self.make_media_project()
        characters.make(root, judge=False, log=lambda *_: None)
        keyframes.make(root, judge=False, log=lambda *_: None)
        self.mock.set_behaviours(["media404"])
        out, log = self.quiet()
        res = clips.make(root, log=log)
        self.assertTrue(res["skipped"])
        st = project.stage_state(root, "video_a")
        self.assertEqual(st["status"], "skipped")
        self.assertIn("/v1/videos is not live", st["note"])
        self.assertFalse([c for c in self.mock.charges if c["kind"] == "video"])
        self.assertTrue(all(e["status"] == "released" for e in ledger.Ledger(root).entries() if e["kind"] == "video"))
        with self.assertRaises(UsageError):
            version_a.build(root, log=log)

    def test_doctor_missing_skips_without_calling(self):
        root = self.make_media_project()
        characters.make(root, judge=False, log=lambda *_: None)
        keyframes.make(root, judge=False, log=lambda *_: None)
        project.update_settings(root, lambda s: s.setdefault("endpoints", {}).__setitem__("videos", "missing"))
        res = clips.make(root, log=lambda *_: None)
        self.assertTrue(res["skipped"])
        self.assertFalse(self.posts("/v1/videos"))


class BlockTests(MediaCase):
    def test_safety_block_stops_item_charged_zero(self):
        root = self.make_media_project()
        self.mock.set_behaviours(["block"])
        out, log = self.quiet()
        items = characters.make(root, ["COACH"], log=log)
        self.assertEqual(items["sheet:COACH"]["status"], "blocked")
        self.assertFalse(os.path.exists(os.path.join(root, "characters/sheets/COACH.png")))
        self.assertEqual(ledger.Ledger(root).summary()["spent_inr"], 0.0)
        self.assertIn("BLOCKED", "\n".join(out))


class RetakeTests(MediaCase):
    def test_low_judge_retakes_then_flags_best(self):
        root = self.make_media_project()
        characters.make(root, judge=False, log=lambda *_: None)
        self.mock.set_behaviours(["judge_always_low"])
        out, log = self.quiet()
        items = keyframes.make(root, ["S01"], log=log)
        it = items["S01"]
        self.assertEqual(it["status"], "flagged")
        self.assertEqual(len(it["takes"]), store.max_takes(root))
        self.assertTrue(os.path.exists(os.path.join(root, "keyframes/S01.png")))
        self.assertEqual(len(os.listdir(os.path.join(root, "keyframes/_rejected"))), 3)
        prompts = [r["body"]["prompt"] for r in self.posts("/v1/images/generations")][-3:]
        self.assertNotIn("Fix these", prompts[0])
        self.assertIn("IMPORTANT CORRECTIONS: Fix these", prompts[1])       # the judge's evidence steers take 2
        again = keyframes.make(root, ["S01"], log=log)                       # flagged + same prompt: nothing more
        self.assertEqual(len(again["S01"]["takes"]), 3)
        keyframes.make(root, ["S01"], redo=True, extra=1, log=log)          # the user allowed one more take
        self.assertEqual(len(store.load_registry(root, "keyframes")["items"]["S01"]["takes"]), 4)

    def test_music_with_a_voice_is_rejected_every_take(self):
        root = self.make_media_project()
        self.mock.set_behaviours(["judge_hard_no"])
        it = music.make(root, log=lambda *_: None)
        self.assertEqual(it["status"], "rejected")
        self.assertTrue(all(t["status"] == "rejected" and t.get("voice_free") is False for t in it["takes"]))
        self.assertFalse(os.path.exists(os.path.join(root, "audio/music_bed.wav")))

    def test_local_check_rejects_a_frozen_clip(self):
        root = self.make_media_project()
        frozen = os.path.join(self.tmp, "frozen.mp4")
        ff.run(["-f", "lavfi", "-i", "color=c=0x7788aa:s=144x256:d=4", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                frozen])
        ok, notes, _start = clips.clip_ok(frozen, 0.3, 2.0)
        self.assertFalse(ok)
        self.assertIn("freezes", notes)
        black = os.path.join(self.tmp, "black.mp4")
        ff.run(["-f", "lavfi", "-i", "color=c=black:s=144x256:d=4", "-c:v", "libx264", "-pix_fmt", "yuv420p", black])
        ok, notes, _start = clips.clip_ok(black, 0.3, 2.0)
        self.assertFalse(ok)
        self.assertIn("black", notes)
        self.assertTrue(root)


class RestructureTests(MediaCase):
    def test_restructure_prompts_then_only_changed_shots_are_remade(self):
        root = self.make_media_project()
        characters.make(root, judge=False, log=lambda *_: None)
        keyframes.make(root, judge=False, log=lambda *_: None)
        self.mock.set_behaviours(["judge_low_then_high"])
        rec, _ = layers.run_gate(root, "keyframes")
        self.assertFalse(rec["passed"])
        res = layers.run_restructure(root, "keyframes")
        self.assertEqual(res["files"], ["keyframes/prompts.json"])
        self.assertTrue(os.path.exists(os.path.join(root, "keyframes/prompts.json.r1")))
        p = os.path.join(root, "keyframes/prompts.json")
        prompts = util.read_json(p)
        prompts["S01"] += "\nHe keeps both feet still."
        util.write_json(p, prompts)
        n_before = len(self.posts("/v1/images/generations"))
        items = keyframes.make(root, judge=False, log=lambda *_: None)
        self.assertEqual(len(self.posts("/v1/images/generations")) - n_before, 1)     # only S01 again
        self.assertIn("He keeps both feet still.", self.posts("/v1/images/generations")[-1]["body"]["prompt"])
        self.assertEqual(items["S01"]["status"], "accepted")
        self.assertTrue(layers.run_gate(root, "keyframes")[0]["passed"])

    def test_sub_layer_restructure_needs_a_rubric(self):
        root = self.make_media_project(rubrics=False)
        with self.assertRaises(UsageError):
            layers.run_restructure(root, "nonexistent_layer")


class PaymentTests(MediaCase):
    def test_wallet_empty_stops_and_charges_nothing(self):
        root = self.make_media_project()
        self.mock.set_behaviours(["pay402"])
        with self.assertRaises(hidrogen.PaymentRequired):
            characters.make(root, log=lambda *_: None)
        s = ledger.Ledger(root).summary()
        self.assertEqual((s["spent_inr"], s["reserved_inr"]), (0.0, 0.0))


if __name__ == "__main__":
    unittest.main()
