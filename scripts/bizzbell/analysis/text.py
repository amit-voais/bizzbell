"""Shared text handling for the analysis tools: safe file reading, words in any script, filler cues, timed cues.

Every problem with an input file raises a BBError with a plain message, never a traceback.
Adapted from Jakeschincariol/youtube-agent-skill (MIT, see NOTICE)."""
import html
import json
import math
import os
import re
import unicodedata

from ..errors import BBError, UsageError

MAX_INPUT_BYTES = 50 * 1024 * 1024
_BOMS = ((b"\xef\xbb\xbf", "utf-8-sig"), (b"\xff\xfe\x00\x00", "utf-32"), (b"\x00\x00\xfe\xff", "utf-32"),
         (b"\xff\xfe", "utf-16"), (b"\xfe\xff", "utf-16"))
_TIMING = re.compile(r"^\s*(\S+)\s*-->\s*(\S+)")
_TAG = re.compile(r"<[^>]*>|\{\\[^}]*\}")
_CLOCK = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{1,2}(?:\.\d+)?)$")


def printable(text):
    """`text` safe to write as UTF-8 (a file name that is not valid UTF-8 keeps its bytes as escapes)."""
    return str(text).encode("utf-8", "backslashreplace").decode("utf-8")


def source_name(path):
    """The file's name for a report, without the folders it came from."""
    return printable(os.path.basename(path))


def read_input(path, what="file"):
    """The text of a file the user brought, whatever its BOM. Raises a friendly error for anything unreadable."""
    name = printable(path)
    if os.path.isdir(path):
        raise UsageError("%s is a folder, not a %s" % (name, what))
    if not os.path.isfile(path):
        raise UsageError("cannot find the %s: %s" % (what, name))
    try:
        if os.path.getsize(path) > MAX_INPUT_BYTES:
            raise BBError("%s is too large for a %s (over 50 MB)" % (name, what))
        with open(path, "rb") as f:
            raw = f.read()
    except OSError as e:
        raise BBError("cannot read %s: %s" % (name, e.strerror or "read error"))
    if raw.startswith(b"PK\x03\x04"):
        raise BBError("%s looks like a spreadsheet or zip file. Save it as plain text (CSV, SRT, VTT or JSON)" % name)
    encoding = next((enc for bom, enc in _BOMS if raw.startswith(bom)), "utf-8")
    try:
        text = raw.decode(encoding)
    except (UnicodeDecodeError, LookupError):
        raise BBError("%s is not UTF-8 text. Save it as UTF-8 and try again" % name)
    if "\x00" in text:
        raise BBError("%s does not look like a text file" % name)
    if not text.strip():
        raise BBError("%s is empty" % name)
    return text


def read_json_input(path, what="JSON file"):
    """Parsed JSON from a file the user brought."""
    try:
        return json.loads(read_input(path, what))
    except (ValueError, RecursionError) as e:
        raise BBError("%s is not valid JSON (%s)" % (printable(path), str(e)[:120]))


def finite(value):
    """float(value) when it is a real finite number, else None."""
    if isinstance(value, bool):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return v if math.isfinite(v) else None


def parse_clock(text):
    """Seconds from `1:02:03,500`, `02:03.5` or `0:30`, else None."""
    m = _CLOCK.match(text.strip().lstrip("\ufeff").replace(",", "."))
    if not m:
        return None
    return int(m.group(1) or 0) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def _spaceless(ch):
    """Han, Hiragana or Katakana: scripts written without spaces, so each character counts as a word."""
    cp = ord(ch)
    return (0x3040 <= cp <= 0x30FF or 0x3400 <= cp <= 0x4DBF or 0x4E00 <= cp <= 0x9FFF or 0xF900 <= cp <= 0xFAFF
            or 0x20000 <= cp <= 0x2FFFF)


def unspaced(ch):
    """Thai, Lao, Myanmar or Khmer: written without spaces between words, with no way to find the words without a
    dictionary, so each letter and its marks counts as one token."""
    cp = ord(ch)
    return 0x0E00 <= cp <= 0x0EFF or 0x1000 <= cp <= 0x109F or 0x1780 <= cp <= 0x17FF


def words(text):
    """Comparable words in any script. Keeps combining marks, which Python's \\w does not: a Devanagari vowel sign is
    a mark, and `[^\\W_]+` would break a word at every one. Removes joiners and folds case; chandrabindu and anusvara
    compare equal, because the same Hindi word is typed with either."""
    text = unicodedata.normalize("NFKC", text).casefold().replace("ँ", "ं").replace("i\u0307", "i")
    out, cur = [], []
    for i, ch in enumerate(text):
        cat = unicodedata.category(ch)
        if cat == "Cf":
            continue
        if _spaceless(ch):
            if cur:
                out.append("".join(cur))
                cur = []
            out.append(ch)
        elif cat[0] == "L" and unspaced(ch):
            if cur:
                out.append("".join(cur))
            cur = [ch]
        elif cat[0] in "LMN":
            cur.append(ch)
        elif ch in "'’" and cur and i + 1 < len(text) and unicodedata.category(text[i + 1])[0] == "L":
            cur.append("'")
        elif cur:
            out.append("".join(cur))
            cur = []
    if cur:
        out.append("".join(cur))
    return out


def _phrases(*groups):
    return {tuple(words(p)) for group in groups for p in group.split("|")}


# Heard anywhere in a line. Several are ordinary words too (na, haan, yaar), which is why they are only ever a cue.
FILLER_ANYWHERE = _phrases("you know|i mean", "matlab|matlb|yaani|yani|yaniki|yaar|haan|haa|han|na|naa|arre|arrey|arey",
                           "उम|उम्म|उम्म्म|अं|अम्म|हम्म|मतलब|यानी|यानि|यानिकी|यार|हाँ|हां|ना|न|अरे",
                           "o sea|en plan", "hani")
# Filler only when the whole line is nothing else: in a sentence these are normal words.
FILLER_LINE_ONLY = _phrases("so|okay|ok|right|yeah|like|well|anyway|basically|actually|let me see|hold on",
                            "acha|accha|achha|bas|toh|to|dekho|suno|theek hai|thik hai",
                            "अच्छा|बस|तो|देखो|सुनो|ठीक है",
                            "este|pues|bueno|vale|a ver|eh", "işte|şey|tamam|ee")
_HESITATION = re.compile(r"^(?:u+m+|u+h+|e+r+|e+r+m+|a+h+|h+m+|m{2,}|h+a{2,}n*|na{2,}|ar{2,}e+y*|are+y+|उम्+)$")
_LONGEST = 16


def _match_at(toks, i, lexicons):
    """Length of the filler phrase starting at toks[i], or 0."""
    if _HESITATION.match(toks[i]):
        return 1
    for n in range(_LONGEST, 0, -1):
        phrase = tuple(toks[i:i + n])
        if len(phrase) == n and any(phrase in lex for lex in lexicons):
            return n
    return 0


def filler_words(toks, extra=()):
    """The filler cues inside a line: (words kept after removing them, the cues found)."""
    kept, found, i = [], [], 0
    while i < len(toks):
        n = _match_at(toks, i, (FILLER_ANYWHERE, extra))
        if n:
            found.append(" ".join(toks[i:i + n]))
            i += n
        else:
            kept.append(toks[i])
            i += 1
    return kept, found


def only_filler(toks, extra=()):
    """True when a line holds words and every one of them is a filler cue."""
    i = 0
    while i < len(toks):
        n = _match_at(toks, i, (FILLER_ANYWHERE, FILLER_LINE_ONLY, extra))
        if not n:
            return False
        i += n
    return bool(toks)


def clip(text, limit=160):
    """Shorten for a report without splitting a letter from its vowel sign."""
    if len(text) <= limit:
        return text
    while limit > 0 and unicodedata.category(text[limit])[0] == "M":
        limit -= 1
    return text[:limit].rstrip() + "..."


def _cues_from_json(path, data):
    segments = data.get("segments") if isinstance(data, dict) else data
    if not isinstance(segments, list):
        raise BBError("%s has no \"segments\" list. Expected whisper JSON, SRT or VTT" % printable(path))
    cues, skipped = [], 0
    for seg in segments:
        start = finite(seg.get("start")) if isinstance(seg, dict) else None
        end = finite(seg.get("end")) if isinstance(seg, dict) else None
        spoken = seg.get("text") if isinstance(seg, dict) else None
        if start is None or end is None or start < 0 or end < start or not isinstance(spoken, str):
            skipped += 1
        elif spoken.strip():
            cues.append((start, end, " ".join(spoken.split())))
    return cues, skipped


def _cues_from_subtitles(text):
    cues, cur, skipped = [], None, 0
    for line in text.splitlines():
        stripped = line.strip().lstrip("﻿")
        timing = _TIMING.match(line)
        if timing:
            if cur and cur[2] and cur[2][-1].isdigit():      # no blank line before this cue: that was its number
                cur[2].pop()
            start, end = parse_clock(timing.group(1)), parse_clock(timing.group(2))
            if start is None or end is None or end < start:
                skipped += 1
                cur = None
            else:
                cur = [start, end, []]
                cues.append(cur)
        elif not stripped:
            cur = None
        elif cur is not None:
            spoken = html.unescape(_TAG.sub("", stripped)).strip()
            if spoken:
                cur[2].append(spoken)
    return [(a, b, " ".join(t)) for a, b, t in cues if t], skipped


def load_cues(path):
    """([(start, end, text)] sorted by start, how many broken cues were skipped) from SRT, VTT or whisper JSON."""
    text = read_input(path, "transcript")
    if text.lstrip("﻿ \t\r\n")[:1] in ("{", "["):
        try:
            data = json.loads(text)
        except (ValueError, RecursionError) as e:
            raise BBError("%s is not valid JSON (%s)" % (printable(path), str(e)[:120]))
        cues, skipped = _cues_from_json(path, data)
    else:
        cues, skipped = _cues_from_subtitles(text)
    if not cues:
        raise BBError("no timed lines found in %s. Expected SRT, VTT or whisper JSON" % printable(path))
    return sorted(cues, key=lambda c: (c[0], c[1])), skipped
