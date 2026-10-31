"""INR spend ledger with a hard cap: <project>/ledger.json (file-locked).

Every paid call is RESERVED before it is sent (estimate from /v1/media/quote, else the rates in bizzbell.json
budget.rates_inr) and SETTLED after (the INR the reply says it cost, else the reservation). A reservation that
would pass the cap is refused with BudgetExceeded and nothing is sent. With no approved budget (cap 0) every
paid call is refused: the cap is the user's yes, set only by `bb budget set|raise`.

Entry statuses: pending, settled, estimated (settled at the reservation), released (charged 0), uncertain
(the call failed in a way that may have been charged; counted at the reservation to stay safe)."""
import os

from . import hidrogen, project, util
from .errors import BudgetExceeded, UsageError

KINDS = ("chat", "judge", "image", "video", "voice", "music")
RATE_KEY = {"chat": "chat", "judge": "judge", "image": "image", "video": "video_second", "voice": "voice",
            "music": "music"}
COUNTED = ("pending", "settled", "estimated", "uncertain")


class Ledger(object):
    """The spend ledger of one project."""

    def __init__(self, root):
        self.root = root
        self.path = os.path.join(root, "ledger.json")

    # -- storage
    def _load(self):
        return util.read_json(self.path, None) or {"entries": [], "log": []}

    def _budget(self):
        return project.load_settings(self.root).get("budget", {})

    def _locked(self, fn):
        with util.locked(self.path):
            d = self._load()
            r = fn(d)
            util.write_json(self.path, d)
        self._mirror(d)
        return r

    def _mirror(self, d):
        s = self._summarise(d)
        if os.path.exists(os.path.join(self.root, "project.json")):
            project.update_state(self.root, lambda st: st.__setitem__(
                "spend", {"cap_inr": s["cap_inr"], "spent_inr": s["spent_inr"], "reserved_inr": s["reserved_inr"]}))

    def _summarise(self, d):
        b = self._budget()
        spent = sum(e.get("actual_inr") or 0 for e in d["entries"] if e["status"] in ("settled", "estimated",
                                                                                         "uncertain"))
        reserved = sum(e["reserved_inr"] for e in d["entries"] if e["status"] == "pending")
        by_kind = {}
        for e in d["entries"]:
            if e["status"] in COUNTED:
                v = e["reserved_inr"] if e["status"] == "pending" else (e.get("actual_inr") or 0)
                by_kind[e["kind"]] = round(by_kind.get(e["kind"], 0) + v, 2)
        cap = float(b.get("cap_inr") or 0)
        return {"cap_inr": round(cap, 2), "approved": bool(b.get("approved")) and cap > 0,
                "spent_inr": round(spent, 2), "reserved_inr": round(reserved, 2),
                "remaining_inr": round(max(0.0, cap - spent - reserved), 2),
                "calls": len([e for e in d["entries"] if e["status"] != "released"]), "by_kind": by_kind}

    # -- reading
    def summary(self):
        """{cap_inr, approved, spent_inr, reserved_inr, remaining_inr, calls, by_kind}."""
        return self._summarise(self._load())

    def entries(self):
        return list(self._load()["entries"])

    def check(self, inr):
        """None if `inr` more would fit under the cap, else the refusal reason. Writes nothing."""
        return self._refusal(self._summarise(self._load()), inr)

    def _refusal(self, s, inr):
        if not s["approved"]:
            return ("no budget approved yet: ask the user for a cap in INR, then run "
                    "python3 scripts/bb.py budget set <inr>. Nothing was sent.")
        used = s["spent_inr"] + s["reserved_inr"]
        if used + inr > s["cap_inr"] + 1e-9:
            return ("this call (about INR %.2f) would pass the INR %.2f cap (INR %.2f used). Nothing was sent. "
                    "Ask the user before raising it: python3 scripts/bb.py budget raise <inr>"
                    % (inr, s["cap_inr"], used))
        return None

    # -- writing
    def reserve(self, kind, inr, model="", purpose="", ref=""):
        """Reserve `inr` for one call. Returns the entry id. Raises BudgetExceeded (nothing is written)."""
        if kind not in KINDS:
            raise UsageError("unknown spend kind %r (kinds: %s)" % (kind, ", ".join(KINDS)))
        inr = round(max(0.0, float(inr)), 2)

        def f(d):
            why = self._refusal(self._summarise(d), inr)
            if why:
                raise BudgetExceeded(why)
            eid = len(d["entries"]) + 1
            d["entries"].append({"id": eid, "kind": kind, "model": model, "purpose": purpose, "ref": ref,
                                 "reserved_inr": inr, "actual_inr": None, "status": "pending", "time": util.now()})
            return eid
        return self._locked(f)

    def settle(self, entry_id, actual_inr=None, status=None, note=""):
        """Close a reservation. actual_inr None -> charged at the reservation (status "estimated")."""
        def f(d):
            for e in d["entries"]:
                if e["id"] == entry_id:
                    if actual_inr is None:
                        e["actual_inr"] = e["reserved_inr"]
                        e["status"] = status or "estimated"
                    else:
                        e["actual_inr"] = round(float(actual_inr), 2)
                        e["status"] = status or "settled"
                    if note:
                        e["note"] = note
                    e["settled"] = util.now()
                    return True
            return False
        return self._locked(f)

    def release(self, entry_id, note=""):
        """Close a reservation as charged 0 (nothing sent, refused, blocked or not live)."""
        return self.settle(entry_id, 0.0, status="released", note=note)

    # -- estimating + calling
    def estimate(self, kind, model=None, units=1, quote_params=None):
        """(inr, source): /v1/media/quote when it answers, else the bizzbell.json rate x units."""
        if quote_params is not None and kind != "chat":
            try:
                q = hidrogen.quote(kind, model, **quote_params)
                if q is not None:
                    return q, "quote"
            except hidrogen.HidrogenError:
                pass
        rates = self._budget().get("rates_inr", {})
        rate = float(rates.get(RATE_KEY[kind], project.DEFAULT_SETTINGS["budget"]["rates_inr"][RATE_KEY[kind]]))
        return round(rate * max(1.0, float(units)), 2), "rate"

    def call(self, kind, fn, model="", purpose="", units=1, estimate_inr=None, quote_params=None, ref=""):
        """Reserve, run fn(), settle with the cost the reply reports. Returns fn()'s result.

        Charged 0 when fn raises PaymentRequired, NotAvailable, Blocked or another 4xx; counted at the
        reservation ("uncertain") for network/5xx failures."""
        inr = estimate_inr
        if inr is None:
            inr, _src = self.estimate(kind, model, units, quote_params)
        eid = self.reserve(kind, inr, model=model, purpose=purpose, ref=ref)
        try:
            result = fn()
        except hidrogen.HidrogenError as e:
            if isinstance(e, (hidrogen.PaymentRequired, hidrogen.NotAvailable, hidrogen.Blocked)) or \
                    (e.status is not None and 400 <= e.status < 500):
                self.release(eid, note=type(e).__name__)
            else:
                self.settle(eid, None, status="uncertain", note=hidrogen.redact(str(e))[:200])
            raise
        except BaseException:
            self.settle(eid, None, status="uncertain", note="interrupted")
            raise
        self.settle(eid, cost_of(result))
        return result


def cost_of(result):
    """INR a client result says it cost (chat/media_judge dicts, image/video/tts/music tuples). None if unknown."""
    if isinstance(result, dict):
        if result.get("charged_inr") is not None:
            return result["charged_inr"]
        return hidrogen.charged_inr(result)
    if isinstance(result, tuple) and result:
        last = result[-1]
        if isinstance(last, dict):
            if last.get("charged_inr") is not None:
                return last["charged_inr"]
            return hidrogen.charged_inr(last)
    return None


def set_cap(root, inr, note=""):
    """The user's yes: set the INR cap (0 withdraws it). Logged. Returns the new summary."""
    inr = round(float(inr), 2)
    if inr < 0:
        raise UsageError("the cap cannot be negative")

    def f(s):
        b = s.setdefault("budget", {})
        b["cap_inr"] = inr
        b["approved"] = inr > 0
    project.update_settings(root, f)
    L = Ledger(root)
    L._locked(lambda d: d["log"].append({"time": util.now(), "cap_inr": inr, "note": note}))
    project.refresh(root)
    return L.summary()


def raise_cap(root, by_inr, note=""):
    """Raise the cap by `by_inr` (only on the user's word). Returns the new summary."""
    by_inr = float(by_inr)
    if by_inr <= 0:
        raise UsageError("raise by a positive amount")
    cur = float(project.load_settings(root).get("budget", {}).get("cap_inr") or 0)
    return set_cap(root, cur + by_inr, note=note or "raised by %.2f" % by_inr)
