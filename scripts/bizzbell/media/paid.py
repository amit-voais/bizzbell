"""Paid calls for the media stages: a dry-run plan, and the real call through the ledger.

Real call: ledger.Ledger(root).call(kind, fn, model, purpose, units, quote_params) - /v1/media/quote first (free),
reserve under the cap, send with a stable Idempotency-Key, settle with what the reply says it cost.

Dry run (--dry-run on every paid command): Plan.add() records the exact request (endpoint and JSON body, with
reference files shown as their project paths instead of base64), Plan.show() prints them with the ledger check at
the bizzbell.json rates. Nothing is sent, not even the free quote."""
import json

from .. import hidrogen, ledger as ledger_mod


def image_body(prompt, refs, aspect, size, model):
    return {"model": model, "prompt": prompt, "references": ["<file %s>" % r for r in refs], "aspect_ratio": aspect,
            "image_size": size, "response_format": "url"}


def video_body(prompt, first_frame, aspect, resolution, seconds, model):
    b = {"model": model, "prompt": prompt, "aspect_ratio": aspect, "resolution": resolution,
         "first_frame": "<file %s>" % first_frame}
    if seconds:
        b["seconds"] = seconds
    return b


def tts_body(text, voice, model, style, fmt="wav"):
    b = {"model": model, "input": text, "voice": voice, "response_format": fmt}
    if style:
        b["style"] = style
    return b


def music_body(prompt, seconds, model):
    return {"model": model, "prompt": prompt, "seconds": seconds, "instrumental": True}


class Plan(object):
    """What a dry run would send."""

    def __init__(self, root):
        self.root = root
        self.calls = []

    def add(self, kind, model, path, body, purpose, units=1):
        self.calls.append({"kind": kind, "model": model, "path": path, "body": body, "purpose": purpose,
                           "units": units})

    def add_judge(self, purpose, files, passes=1):
        for i in range(passes):
            self.calls.append({"kind": "judge", "model": "media-judge", "path": "/v1/media/judge",
                               "body": {"content": ["<rubric questions as text>"] + ["<file %s>" % f for f in files],
                                        "output": "json"},
                               "purpose": "%s judge pass %d" % (purpose, i + 1), "units": 1})

    def total(self):
        led = ledger_mod.Ledger(self.root)
        return round(sum(led.estimate(c["kind"], c["model"], c["units"], None)[0] for c in self.calls), 2)

    def show(self, out=print):
        """Print every request and the ledger check. Returns the total estimate in INR."""
        for c in self.calls:
            out("=== %s  (%s, %s)" % (c["purpose"], c["kind"], c["model"]))
            out("POST %s" % c["path"])
            out(hidrogen.redact(json.dumps(c["body"], indent=1, ensure_ascii=False)))
        total = self.total()
        why = ledger_mod.Ledger(self.root).check(total)
        n_paid = len([c for c in self.calls if c["kind"] != "judge"])
        n_judge = len(self.calls) - n_paid
        out("ledger: %d paid call(s) + up to %d judge call(s), about INR %.2f at the bizzbell.json rates: %s"
            % (n_paid, n_judge, total, why or "fits under the cap"))
        out("dry run: nothing was sent")
        return total


def call(root, kind, fn, model, purpose, units=1, quote_params=None, ref=""):
    """fn() through the ledger (quote -> reserve -> call -> settle). Returns fn()'s result."""
    return ledger_mod.Ledger(root).call(kind, fn, model=model, purpose=purpose, units=units,
                                        quote_params=quote_params if quote_params is not None else {}, ref=ref)
