"""Mock fixtures are real media; the package carries no private names, paths or key-shaped strings."""
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import unittest
import urllib.request
import wave

from helpers import REPO, SCRIPTS

from bizzbell import mock_server


class FixtureTests(unittest.TestCase):
    def test_png(self):
        data = mock_server.png(10, 20)
        self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(int.from_bytes(data[16:20], "big"), 10)

    def test_wav(self):
        w = wave.open(io.BytesIO(mock_server.wav(0.5)))
        self.assertEqual((w.getnchannels(), w.getframerate(), w.getnframes()), (1, 16000, 8000))

    @unittest.skipUnless(shutil.which("ffprobe") or os.path.exists("/opt/homebrew/bin/ffprobe"), "no ffprobe")
    def test_mp4_is_a_real_clip(self):
        data = mock_server.mp4(1.5, 64, 112)
        probe = shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe"
        r = subprocess.run([probe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", "-"],
                           input=data, capture_output=True)
        self.assertAlmostEqual(float(r.stdout.strip()), 1.5, delta=0.3)

    def test_unknown_behaviour(self):
        with self.assertRaises(ValueError):
            mock_server.MockHidrogen(["nope"])

    def test_cli_prints_url_and_control_endpoint(self):
        env = dict(os.environ, PYTHONPATH=SCRIPTS)
        p = subprocess.Popen([sys.executable, "-m", "bizzbell.mock_server", "--port", "0", "--behaviour", "flaky"],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env, text=True)
        try:
            url = p.stdout.readline().strip()
            self.assertTrue(url.startswith("http://127.0.0.1:"))
            state = json.load(urllib.request.urlopen(url + "/_mock/state", timeout=10))
            self.assertEqual(state["behaviours"], ["flaky"])
            req = urllib.request.Request(url + "/_mock/behaviour", data=b'{"set": ["block"]}', method="POST")
            self.assertEqual(json.load(urllib.request.urlopen(req, timeout=10))["behaviours"], ["block"])
        finally:
            p.terminate()
            p.wait(10)


# sha256(word)[:16] of private words that must never appear as a token in the package (stored hashed so this
# file does not contain them either).
BANNED = {"b22e3c9fedd55f17", "31388fe3ce236632", "119f43df4c6ecc2d", "1a74b31dd44546ca", "623f0b5584eb86d9",
          "5152cc21067154b8", "6fd4125c253a7dd4", "d4900b84c3ca2029", "a29f6d7c87fff230", "a517be3674fe608c",
          "87e9390f745fcff8", "5f62d4944949941f", "a132c114be981e20", "7a95b2fc8d8f0e55"}
SKIP_DIRS = {".git", ".tmp", "node_modules", "__pycache__"}
ALLOWED_KEYS = {"hi_test_0000000000000000fake", "hi_test_1111111111111111envv", "hi_abcdefghijklmnopqrstuvwxyz"}


def package_files():
    """Every file that would be committed (skips .git, .tmp, caches and the gitignored docs/internal)."""
    for d, dirs, files in os.walk(REPO):
        rel = os.path.relpath(d, REPO)
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
        if rel.replace(os.sep, "/").startswith("docs/internal"):
            continue
        for f in files:
            yield os.path.join(d, f)


class HygieneTests(unittest.TestCase):
    def test_no_private_names_or_keys(self):
        bad = []
        for p in package_files():
            rel = os.path.relpath(p, REPO)
            try:
                text = open(p, encoding="utf-8").read()
            except (UnicodeDecodeError, OSError):
                continue
            for tok in set(re.findall(r"[A-Za-z]+", text + " " + rel)):
                if hashlib.sha256(tok.lower().encode()).hexdigest()[:16] in BANNED:
                    bad.append("%s: private word" % rel)
            for k in re.findall(r"\b(?:hi|sk)_[A-Za-z0-9_\-]{16,}", text):
                if k not in ALLOWED_KEYS:
                    bad.append("%s: key-shaped string" % rel)
            if "/" + "Users" + "/" in text:
                bad.append("%s: absolute home path" % rel)
        self.assertEqual(bad, [])

    def test_no_emoji_in_package(self):
        emoji = re.compile("[%s-%s%s-%s]" % (chr(0x1F300), chr(0x1FAFF), chr(0x2600), chr(0x27BF)))
        hits = [os.path.relpath(p, REPO) for p in package_files()
                if p.endswith((".py", ".md", ".json", ".html", ".css")) and emoji.search(open(p, encoding="utf-8",
                                                                                              errors="ignore").read())]
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
