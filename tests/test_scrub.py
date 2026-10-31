"""Scrub test: no committed file (git ls-files, plus new files git would add) holds a private name or a key.

The private names are stored as sha256 prefixes so this file does not contain them. Distinctive names are matched
inside any run of letters (so a prefixed or joined spelling is caught too); short names are matched as whole
words only. Key-shaped strings are hi_ or sk_ followed by 16 or more characters, except the obvious fake keys."""
import hashlib
import os
import re
import subprocess
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# length -> sha256(name)[:16]: matched anywhere inside a run of letters, case-insensitive
INSIDE = {5: {"1a74b31dd44546ca"}, 6: {"31388fe3ce236632", "b22e3c9fedd55f17"},
          7: {"119f43df4c6ecc2d", "87e9390f745fcff8", "a517be3674fe608c"}, 8: {"5f62d4944949941f"},
          9: {"6fd4125c253a7dd4", "7a95b2fc8d8f0e55"}, 10: {"d4900b84c3ca2029"}}
# sha256(name)[:16]: matched as whole words only, case-insensitive
WHOLE = {"5152cc21067154b8", "623f0b5584eb86d9", "a132c114be981e20"}
FAKE_KEYS = {"hi_test_0000000000000000fake", "hi_test_1111111111111111envv", "hi_abcdefghijklmnopqrstuvwxyz"}
KEY = re.compile(r"(?<![A-Za-z0-9])(?:hi|sk)_[A-Za-z0-9_\-]{16,}")


def _h(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def private_hits(text, inside=INSIDE, whole=WHOLE):
    """Sorted list of the banned hashes found in `text`."""
    found = set()
    for tok in set(t.lower() for t in re.findall(r"[A-Za-z]+", text)):
        if _h(tok) in whole:
            found.add(_h(tok))
        for n, hashes in inside.items():
            for i in range(0, len(tok) - n + 1):
                if _h(tok[i:i + n]) in hashes:
                    found.add(_h(tok[i:i + n]))
    return sorted(found)


def key_hits(text):
    return [k for k in KEY.findall(text) if k not in FAKE_KEYS]


def committed_files():
    """Tracked files plus untracked files that are not ignored: what `git add -A` would commit."""
    r = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=REPO,
                       capture_output=True, timeout=60)
    if r.returncode != 0:
        raise unittest.SkipTest("not a git checkout")
    return sorted(set(p for p in r.stdout.decode("utf-8").split("\0") if p))


class ScrubTests(unittest.TestCase):
    def test_matcher_catches_inside_and_whole_words(self):
        inside = {8: {_h("bellbake")}}
        whole = {_h("zed")}
        self.assertEqual(private_hits("our-BellBakeShop and Zed.", inside, whole),
                         sorted({_h("bellbake"), _h("zed")}))
        self.assertEqual(private_hits("zedonk bell bake", inside, whole), [])     # whole-word only; split words
        self.assertEqual(key_hits("x hi_" + "a1" * 9 + " y"), ["hi_" + "a1" * 9])
        self.assertEqual(key_hits("sk_" + "Z" * 20), ["sk_" + "Z" * 20])
        self.assertEqual(key_hits(" ".join(sorted(FAKE_KEYS)) + " hi_short ok_" + "x" * 20), [])

    def test_committed_files_are_clean(self):
        files = committed_files()
        self.assertTrue(files)
        self.assertNotIn("docs/internal", " ".join(files))
        bad = []
        for rel in files:
            p = os.path.join(REPO, rel)
            if private_hits(rel):
                bad.append("%s: private name in the path" % rel)
            if not os.path.isfile(p):
                continue
            try:
                with open(p, encoding="utf-8") as f:
                    text = f.read()
            except (UnicodeDecodeError, OSError):
                continue
            if private_hits(text):
                bad.append("%s: private name" % rel)
            if key_hits(text):
                bad.append("%s: key-shaped string" % rel)
            if "/" + "Users" + "/" in text or "/" + "home" + "/" in text.replace("/home/user", ""):
                bad.append("%s: absolute home path" % rel)
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
