"""Hidrogen client against the mock: key, redaction, retries, idempotency, errors, every endpoint."""
import os
import stat
import unittest

from helpers import FAKE_KEY, MockCase, hidrogen


class KeyTests(MockCase):
    with_key = False

    def test_missing_key(self):
        with self.assertRaises(hidrogen.KeyMissing):
            hidrogen.key()
        self.assertEqual(hidrogen.key(quiet=True), "")

    def test_key_file_follows_home(self):
        path = hidrogen.save_key(FAKE_KEY)
        self.assertTrue(path.startswith(self.home))
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        self.assertEqual(hidrogen.key(), FAKE_KEY)

    def test_env_beats_file(self):
        hidrogen.save_key(FAKE_KEY)
        os.environ["HIDROGEN_API_KEY"] = "hi_test_1111111111111111envv"
        self.assertEqual(hidrogen.key(), "hi_test_1111111111111111envv")

    def test_save_key_rejects_junk(self):
        with self.assertRaises(hidrogen.BBError):
            hidrogen.save_key("not-a-key")
        with self.assertRaises(hidrogen.BBError):
            hidrogen.save_key("   ")

    def test_redact(self):
        os.environ["HIDROGEN_API_KEY"] = "hi_short"
        hidrogen.key()
        t = hidrogen.redact("key hi_short and hi_abcdefghijklmnopqrstuvwxyz and Bearer abc123def456")
        self.assertNotIn("hi_short", t)
        self.assertNotIn("abcdefghijklmnop", t)
        self.assertNotIn("abc123def456", t)

    def test_401_without_good_key(self):
        os.environ["HIDROGEN_API_KEY"] = "bad_key_value_zzzzzzzzzzzz"
        with self.assertRaises(hidrogen.HidrogenError) as cm:
            hidrogen.models()
        self.assertEqual(cm.exception.status, 401)
        self.assertNotIn("bad_key_value", str(cm.exception))


class ClientTests(MockCase):
    def test_chat_moves_system_to_system_prompt(self):
        r = hidrogen.chat([{"role": "system", "content": "be brief"}, {"role": "user", "content": "hello"}],
                          "claude-sonnet-4-5", system_prompt="rule one")
        self.assertTrue(r["text"].startswith("Mock reply"))
        self.assertEqual(r["charged_inr"], 0.5)
        body = [q for q in self.mock.requests if q["path"] == "/v1/chat/completions"][-1]["body"]
        self.assertEqual(body["system_prompt"], "rule one\n\nbe brief")
        self.assertFalse(any(m["role"] == "system" for m in body["messages"]))

    def test_chat_json(self):
        obj, reply = hidrogen.chat_json("give json", "claude-sonnet-4-5")
        self.assertTrue(obj["ok"])

    def test_parse_json_text(self):
        self.assertEqual(hidrogen.parse_json_text('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(hidrogen.parse_json_text('Sure: {"a": [1]} done'), {"a": [1]})
        with self.assertRaises(ValueError):
            hidrogen.parse_json_text("no json here")

    def test_models_balance_quote(self):
        ids = [m["id"] for m in hidrogen.models()]
        self.assertIn("claude-opus-4-5", ids)
        self.assertEqual(hidrogen.balance_inr(), 1000.0)
        self.assertEqual(hidrogen.quote("video", "video", seconds=6), 30.0)
        self.assertEqual(hidrogen.quote("image", "image-pro"), 4.0)

    def test_image(self):
        data, resp = hidrogen.image("a loaf of bread on a table", refs=(), aspect="9:16")
        self.assertTrue(data.startswith(b"\x89PNG"))
        self.assertEqual(hidrogen.charged_inr(resp), 4.0)

    def test_image_with_reference_file(self):
        ref = os.path.join(self.tmp, "ref.png")
        with open(ref, "wb") as f:
            f.write(hidrogen.download(hidrogen.image("x")[1]["data"][0]["url"]))
        hidrogen.image("same loaf", refs=[ref])
        body = [q for q in self.mock.requests if q["path"] == "/v1/images/generations"][-1]["body"]
        self.assertTrue(body["references"][0].startswith("data:image/png;base64,"))

    def test_video_and_wait(self):
        data, job = hidrogen.video("the lid lifts slowly", seconds=2, poll_wait=1)
        self.assertEqual(data[4:8], b"ftyp")
        self.assertEqual(job["status"], "succeeded")
        self.assertEqual(hidrogen.charged_inr(job), 10.0)

    def test_tts_and_music(self):
        audio, meta = hidrogen.tts("namaste, yeh box dekho", voice="priya")
        self.assertTrue(audio.startswith(b"RIFF"))
        self.assertEqual(meta["charged_inr"], 0.3)
        outs, job = hidrogen.music("warm festive bed, no vocals", seconds=3, poll_wait=1)
        self.assertTrue(outs[0][0].startswith(b"RIFF"))

    def test_media_judge(self):
        img = os.path.join(self.tmp, "k.png")
        with open(img, "wb") as f:
            f.write(hidrogen.image("x")[0])
        r = hidrogen.media_judge("describe", [img])
        self.assertEqual(r["result"]["media"], 1)
        self.assertEqual(r["charged_inr"], 1.0)

    def test_probe(self):
        self.assertEqual(hidrogen.probe("/v1/videos"), "live")

    def test_idempotent_replay_charges_once(self):
        body = {"model": "image-pro", "prompt": "x"}
        a = hidrogen.request("POST", "/v1/images/generations", body, idem="same-key-1")
        b = hidrogen.request("POST", "/v1/images/generations", body, idem="same-key-1")
        self.assertEqual(a, b)
        self.assertEqual(len([c for c in self.mock.charges if c["kind"] == "image"]), 1)


class FlakyTests(MockCase):
    behaviours = ("flaky",)

    def test_retry_reuses_idempotency_key(self):
        hidrogen.chat("hi", "claude-sonnet-4-5")
        posts = [q for q in self.mock.requests if q["method"] == "POST"]
        self.assertEqual(len(posts), 2)
        self.assertEqual(posts[0]["idempotency_key"], posts[1]["idempotency_key"])
        self.assertTrue(posts[0]["idempotency_key"].startswith("bb-"))
        self.assertEqual(len(self.mock.charges), 1)

    def test_network_error_is_friendly(self):
        os.environ["HIDROGEN_API_URL"] = "http://127.0.0.1:9"
        with self.assertRaises(hidrogen.HidrogenError) as cm:
            hidrogen.request("GET", "/v1/models", tries=2)
        self.assertIn("could not reach", str(cm.exception))
        self.assertIsNone(cm.exception.status)


class ErrorTests(MockCase):
    def test_402(self):
        self.mock.set_behaviours(["pay402"])
        with self.assertRaises(hidrogen.PaymentRequired) as cm:
            hidrogen.image("x")
        self.assertIn("Recharge the wallet", str(cm.exception))
        self.assertEqual(cm.exception.exit_code, 5)

    def test_404_media(self):
        self.mock.set_behaviours(["media404"])
        for fn in (lambda: hidrogen.image("x"), lambda: hidrogen.video("x"), lambda: hidrogen.tts("x"),
                   lambda: hidrogen.quote("image")):
            with self.assertRaises(hidrogen.NotAvailable):
                fn()
        self.assertEqual(hidrogen.probe("/v1/videos"), "missing")
        hidrogen.chat("still works", "claude-sonnet-4-5")

    def test_block(self):
        self.mock.set_behaviours(["block"])
        with self.assertRaises(hidrogen.Blocked):
            hidrogen.image("x")
        with self.assertRaises(hidrogen.Blocked):
            hidrogen.tts("x")
        with self.assertRaises(hidrogen.Blocked):
            hidrogen.video("x", poll_wait=1)
        with self.assertRaises(hidrogen.Blocked):
            hidrogen.music("x", poll_wait=1)
        self.assertEqual(sum(c["paise"] for c in self.mock.charges), 0)

    def test_slow_job_times_out(self):
        self.mock.set_behaviours(["slow_job"])
        with self.assertRaises(hidrogen.HidrogenError) as cm:
            hidrogen.video("x", poll_wait=0, max_wait=0)
        self.assertIn("still running", str(cm.exception))

    def test_slow_job_finishes(self):
        self.mock.set_behaviours(["slow_job"])
        data, job = hidrogen.video("x", poll_wait=0)
        self.assertEqual(job["status"], "succeeded")


if __name__ == "__main__":
    unittest.main()
