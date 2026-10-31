"""Generic local checks any rubric can use."""
import json
import os
import re

from ..gate import check


@check("files_exist")
def files_exist(ctx, files=None):
    """Every path in `files` (default: the layer's files) exists and is not empty."""
    paths = files or ctx.rubric["layer"]["files"]
    import glob
    missing = [p for p in paths if not [h for h in glob.glob(os.path.join(ctx.root, p)) if os.path.getsize(h) > 0]]
    if missing:
        return "no", "missing or empty: " + ", ".join(missing)
    return "yes", "present: " + ", ".join(paths)


def _words(text):
    return re.findall(r"\w+", text, re.UNICODE)


@check("word_count")
def word_count(ctx, min_words=0, max_words=None, file=None):
    """The layer (or `file`) has between `min_words` and `max_words` words."""
    text = ctx.read(file) if file else ctx.layer_text
    n = len(_words(text))
    if n < min_words:
        return "no", "%d words, fewer than %d" % (n, min_words)
    if max_words is not None and n > max_words:
        return "partly" if n <= max_words * 1.2 else "no", "%d words, more than %d" % (n, max_words)
    return "yes", "%d words" % n


@check("json_valid")
def json_valid(ctx, file=None):
    """`file` (default: every .json layer file) parses as JSON."""
    files = [file] if file else [ctx.rel(p) for p in ctx.layer_files if p.endswith(".json")]
    if not files:
        return "no", "no JSON file in the layer"
    for f in files:
        try:
            with open(os.path.join(ctx.root, f), encoding="utf-8") as fh:
                json.load(fh)
        except (OSError, ValueError) as e:
            return "no", "%s: %s" % (f, e)
    return "yes", "valid JSON: " + ", ".join(files)


@check("contains_none")
def contains_none(ctx, words=(), file=None):
    """None of `words` (case-insensitive, whole words) appears in the layer (or `file`)."""
    text = (ctx.read(file) if file else ctx.layer_text).lower()
    hits = [w for w in words if re.search(r"(?<!\w)%s(?!\w)" % re.escape(w.lower()), text)]
    if hits:
        return "no", "found: " + ", ".join(hits)
    return "yes", "none of: " + ", ".join(words)


@check("has_sections")
def has_sections(ctx, headings=(), file=None):
    """Every heading in `headings` appears as a Markdown heading (case-insensitive)."""
    text = ctx.read(file) if file else ctx.layer_text
    found = [h.lower() for h in re.findall(r"(?m)^#{1,6}\s+(.+?)\s*$", text)]
    missing = [h for h in headings if not any(h.lower() in f for f in found)]
    if not missing:
        return "yes", "all headings present"
    return ("partly" if len(missing) < len(headings) else "no"), "missing headings: " + ", ".join(missing)
