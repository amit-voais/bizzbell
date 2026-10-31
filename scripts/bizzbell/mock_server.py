"""Offline mock of every Hidrogen endpoint Bizzbell uses (stdlib http.server; no key, no network, no spend).

Start:  python3 scripts/bb.py mock --port 0 [--behaviour a,b]
        PYTHONPATH=scripts python3 -m bizzbell.mock_server --port 0 [--behaviour a,b]   (prints the URL)
In tests:
        with MockHidrogen(behaviours=["media404"]) as m:   # sets nothing globally; use m.url
            os.environ["HIDROGEN_API_URL"] = m.url
Switch behaviours at runtime: m.set_behaviours([...]) or POST /_mock/behaviour {"set": [...]};
GET /_mock/state -> {"behaviours", "requests", "charges", "restructured"}.

Any key starting with "hi_" is accepted (use hi_test_0000000000000000fake). Fixtures are generated on the fly:
PNG (zlib/struct), WAV (wave), MP4 (ffmpeg testsrc when ffmpeg exists, else a tiny placeholder).
POSTs are idempotent by Idempotency-Key: a repeated key replays the first reply and is not charged again."""
import argparse
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import threading
import time
import uuid
import wave
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO

BEHAVIOURS = {
    "pay402": "every paid POST answers 402 (wallet empty)",
    "media404": "images/videos/voice/music/media judge/quote answer 404 (not live)",
    "block": "images and voice answer content_blocked; video and music jobs end blocked",
    "slow_job": "video/music jobs need 3 extra polls before they finish",
    "flaky": "the first try of every POST answers 503 (retry with the same Idempotency-Key succeeds)",
    "no_opus": "/v1/models lists no Opus model",
    "judge_low_then_high": "the judge fails half the questions until a restructure reply was sent, then passes all",
    "judge_always_low": "the judge always fails half the questions",
    "judge_disagree": "judge passes alternate: all yes, then half no (forces a third pass)",
    "judge_hard_no": "the judge answers no to every hard question, yes to the rest",
    "judge_bad_json_once": "the first judge reply is not JSON",
}
MODELS = ["claude-opus-4-5", "claude-sonnet-4-5", "gemini-2.5-pro", "gemini-2.5-flash", "gpt-4o-mini",
          "image-pro", "image-fast", "video", "video-hq", "voice-studio", "music"]
PAISE = {"chat": 50, "judge": 100, "image": 400, "video": 500, "voice": 30, "music": 300}
MEDIA_PREFIXES = ("/v1/images", "/v1/videos", "/v1/audio", "/v1/music", "/v1/media")
SIZES = {"9:16": (72, 128), "16:9": (128, 72), "1:1": (96, 96), "4:5": (96, 120)}


# ---------------------------------------------------------------- fixtures
def png(width=72, height=128, rgb=(40, 90, 160)):
    """A solid-colour PNG."""
    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def wav(seconds=1.0, freq=440.0, rate=16000):
    """A mono 16-bit sine-wave WAV."""
    buf = BytesIO()
    w = wave.open(buf, "wb")
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(rate)
    n = int(seconds * rate)
    w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * freq * i / rate))) for i in range(n)))
    w.close()
    return buf.getvalue()


_MP4_CACHE = {}


def _ffmpeg():
    return shutil.which("ffmpeg") or ("/opt/homebrew/bin/ffmpeg" if os.path.exists("/opt/homebrew/bin/ffmpeg")
                                      else None)


def mp4(seconds=2.0, width=144, height=256):
    """A small testsrc MP4 with a sine audio track (written to a pipe, no temp files); placeholder without ffmpeg."""
    k = (round(seconds, 2), width, height)
    if k in _MP4_CACHE:
        return _MP4_CACHE[k]
    ff = _ffmpeg()
    data = b""
    if ff:
        cmd = [ff, "-v", "error", "-f", "lavfi", "-i", "testsrc=size=%dx%d:rate=12:duration=%s" % (width, height, seconds),
               "-f", "lavfi", "-i", "sine=frequency=330:duration=%s" % seconds, "-shortest", "-c:v", "libx264",
               "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "48k",
               "-movflags", "frag_keyframe+empty_moov", "-f", "mp4", "pipe:1"]
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=60)
            data = r.stdout if r.returncode == 0 else b""
        except Exception:
            data = b""
    if not data:
        data = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom"
    _MP4_CACHE[k] = data
    return data


# ---------------------------------------------------------------- judge / restructure logic
def _between(text, start, end):
    m = re.search(re.escape(start) + r"(.*?)" + re.escape(end), text, re.S)
    return m.group(1) if m else ""


def _quote_from_layer(text):
    layer = _between(text, "<layer>", "</layer>")
    for line in layer.splitlines():
        line = line.strip().strip("#").strip()
        if len(line) >= 12 and not line.startswith("==="):
            return line[:60]
    return ""


class State(object):
    def __init__(self, behaviours):
        self.lock = threading.Lock()
        self.behaviours = set(behaviours or [])
        self.requests = []
        self.charges = []
        self.idem = {}
        self.flaky_seen = set()
        self.files = {}
        self.jobs = {}
        self.judge_calls = 0
        self.restructured = False

    def has(self, b):
        return b in self.behaviours


def judge_answers(state, text):
    """The mock judge's answers for the <questions> block in `text`."""
    try:
        qs = json.loads(_between(text, "<questions>", "</questions>").strip() or "[]")
    except ValueError:
        qs = []
    with state.lock:
        state.judge_calls += 1
        n = state.judge_calls
    quote = _quote_from_layer(text)
    yes_ev = ('"%s"' % quote) if quote else "the attached media shows it"
    low = state.has("judge_always_low") or (state.has("judge_low_then_high") and not state.restructured) or \
        (state.has("judge_disagree") and n % 2 == 0)
    out = []
    for i, q in enumerate(qs):
        ans = "yes"
        if low and i % 2 == 0:
            ans = "no"
        if state.has("judge_hard_no") and q.get("hard"):
            ans = "no"
        ev = yes_ev if ans == "yes" else "missing: nothing in the layer answers '%s'" % q.get("question", "")[:60]
        out.append({"id": q.get("id"), "answer": ans, "evidence": ev})
    return {"answers": out}


def restructure_reply(state, text):
    files = re.findall(r'<file name="([^"]+)">\n(.*?)\n</file>', text, re.S)
    out = {}
    for name, content in files:
        out[name] = content if name.endswith(".json") else content.rstrip("\n") + "\n\n<!-- revised -->\n"
    with state.lock:
        state.restructured = True
    return {"files": out, "changes": ["revised to answer the failed questions"]}


# ---------------------------------------------------------------- handler
class Handler(BaseHTTPRequestHandler):
    server_version = "HidrogenMock/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    @property
    def st(self):
        return self.server.state

    # -- helpers
    def _send(self, code, payload, ctype="application/json", headers=None):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)
        return code, payload, ctype, headers

    def _err(self, code, ecode, msg):
        return self._send(code, {"error": {"code": ecode, "message": msg}})

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        try:
            return json.loads(raw.decode("utf-8")) if raw else {}
        except ValueError:
            return {}

    def _authed(self):
        a = self.headers.get("Authorization", "")
        return a.startswith("Bearer hi_")

    def _file_url(self, data, mime, ext):
        fid = uuid.uuid4().hex[:12] + ext
        with self.st.lock:
            self.st.files[fid] = (data, mime)
        return "http://%s:%d/_files/%s" % (self.server.server_address[0], self.server.server_address[1], fid)

    def _record(self, method, body):
        with self.st.lock:
            self.st.requests.append({"method": method, "path": self.path, "body": body,
                                     "idempotency_key": self.headers.get("Idempotency-Key"),
                                     "time": time.time()})

    def _charge(self, kind, paise):
        with self.st.lock:
            self.st.charges.append({"kind": kind, "paise": paise, "path": self.path})
        return {"charged_paise": paise}

    # -- verbs
    def do_OPTIONS(self):
        self._record("OPTIONS", None)
        path = self.path.split("?")[0]
        if self.st.has("media404") and path.startswith(MEDIA_PREFIXES):
            return self._err(404, "not_found", "no such endpoint")
        self.send_response(204)
        self.send_header("Allow", "GET, POST, OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        self._record("GET", None)
        path = self.path.split("?")[0]
        if path.startswith("/_files/"):
            f = self.st.files.get(path[len("/_files/"):])
            return self._send(200, f[0], f[1]) if f else self._err(404, "not_found", "no such file")
        if path == "/_mock/state":
            return self._send(200, {"behaviours": sorted(self.st.behaviours), "requests": len(self.st.requests),
                                    "charges": len(self.st.charges), "restructured": self.st.restructured})
        if not self._authed():
            return self._err(401, "unauthorized", "missing or bad key")
        if self.st.has("media404") and path.startswith(MEDIA_PREFIXES):
            return self._err(404, "not_found", "no such endpoint")
        if path == "/v1/models":
            ids = [m for m in MODELS if not (self.st.has("no_opus") and "opus" in m)]
            return self._send(200, {"object": "list", "data": [{"id": i, "object": "model"} for i in ids]})
        if path == "/v1/balance":
            return self._send(200, {"currency": "INR", "balance_paise": 100000})
        m = re.match(r"^/v1/(videos|music)/([A-Za-z0-9_\-]+)$", path)
        if m:
            return self._job(m.group(2))
        return self._err(404, "not_found", "no such endpoint")

    def do_POST(self):
        body = self._body()
        self._record("POST", body)
        path = self.path.split("?")[0]
        if path == "/_mock/behaviour":
            with self.st.lock:
                self.st.behaviours = set(body.get("set", []))
            return self._send(200, {"behaviours": sorted(self.st.behaviours)})
        if not self._authed():
            return self._err(401, "unauthorized", "missing or bad key")
        idem = self.headers.get("Idempotency-Key")
        if self.st.has("flaky") and idem and idem not in self.st.flaky_seen:
            with self.st.lock:
                self.st.flaky_seen.add(idem)
            return self._err(503, "unavailable", "try again")
        if idem and idem in self.st.idem:
            code, payload, ctype, headers = self.st.idem[idem]
            return self._send(code, payload, ctype, headers)
        if self.st.has("media404") and path.startswith(MEDIA_PREFIXES):
            return self._err(404, "not_found", "no such endpoint")
        if self.st.has("pay402") and path != "/v1/media/quote":
            return self._err(402, "insufficient_balance", "wallet balance too low for this request")
        route = {"/v1/chat/completions": self._chat, "/v1/images/generations": self._image,
                 "/v1/videos": self._video, "/v1/audio/speech": self._speech, "/v1/music": self._music,
                 "/v1/media/judge": self._judge, "/v1/media/quote": self._quote}.get(path)
        if not route:
            return self._err(404, "not_found", "no such endpoint")
        res = route(body)
        if idem and res and res[0] < 400:
            with self.st.lock:
                self.st.idem[idem] = res
        return res

    # -- endpoints
    def _chat(self, body):
        if not body.get("model") or not isinstance(body.get("messages"), list):
            return self._err(400, "bad_request", "model and messages are required")
        # the real gateway drops role:system; the mock does the same, so a test catches code that relies on it
        msgs = [m for m in body["messages"] if m.get("role") != "system"]
        text = "\n".join(m.get("content", "") if isinstance(m.get("content"), str) else "" for m in msgs)
        if "<questions>" in text:
            if self.st.has("judge_bad_json_once"):
                with self.st.lock:
                    self.st.behaviours.discard("judge_bad_json_once")
                out = "I think it is mostly fine."
            else:
                out = json.dumps(judge_answers(self.st, text))
        elif "<targets>" in text:
            out = json.dumps(restructure_reply(self.st, text))
        elif (body.get("response_format") or {}).get("type") == "json_object":
            out = json.dumps({"ok": True, "echo": text[-80:]})
        else:
            out = "Mock reply: " + text[-80:]
        return self._send(200, {"id": "chatcmpl-" + uuid.uuid4().hex[:10], "object": "chat.completion",
                                "model": body["model"], "choices": [{"index": 0, "finish_reason": "stop",
                                "message": {"role": "assistant", "content": out}}],
                                "usage": {"prompt_tokens": len(text) // 4, "completion_tokens": len(out) // 4},
                                "billing": self._charge("chat", PAISE["chat"])})

    def _image(self, body):
        if self.st.has("block"):
            return self._err(400, "content_blocked", "the safety filter blocked this prompt")
        w, h = SIZES.get(body.get("aspect_ratio", "9:16"), SIZES["9:16"])
        url = self._file_url(png(w, h), "image/png", ".png")
        return self._send(200, {"created": int(time.time()), "data": [{"url": url}],
                                "billing": self._charge("image", PAISE["image"])})

    def _new_job(self, kind, body, output):
        jid = ("vid_" if kind == "videos" else "mus_") + uuid.uuid4().hex[:10]
        seconds = float(body.get("seconds") or (4 if kind == "videos" else 10))
        paise = PAISE["video"] * seconds if kind == "videos" else PAISE["music"]
        with self.st.lock:
            self.st.jobs[jid] = {"id": jid, "kind": kind, "polls": 3 if self.st.has("slow_job") else 0,
                                 "blocked": self.st.has("block"), "output": output, "seconds": seconds,
                                 "paise": paise, "charged": False}
        return self._send(200, {"id": jid, "object": kind[:-1] if kind == "videos" else "music", "status": "queued"})

    def _video(self, body):
        if not body.get("prompt"):
            return self._err(400, "bad_request", "prompt is required")
        w, h = {"9:16": (144, 256), "16:9": (256, 144), "1:1": (192, 192), "4:5": (192, 240)}.get(
            body.get("aspect_ratio", "9:16"), (144, 256))
        seconds = min(4.0, float(body.get("seconds") or 4))
        return self._new_job("videos", body, (mp4(seconds, w, h), "video/mp4", ".mp4"))

    def _music(self, body):
        return self._new_job("music", body, (wav(min(3.0, float(body.get("seconds") or 3)), 220.0), "audio/wav",
                                             ".wav"))

    def _job(self, jid):
        q = self.path.split("?", 1)[1] if "?" in self.path else ""
        m = re.search(r"wait=(\d+)", q)
        with self.st.lock:
            j = self.st.jobs.get(jid)
        if not j:
            return self._err(404, "not_found", "no such job")
        if j["polls"] > 0:
            with self.st.lock:
                j["polls"] -= 1
            time.sleep(min(0.05, float(m.group(1)) if m else 0))
            return self._send(200, {"id": jid, "status": "running"})
        if j["blocked"]:
            return self._send(200, {"id": jid, "status": "blocked",
                                    "error": {"code": "content_blocked", "message": "blocked by the safety filter"},
                                    "billing": {"charged_paise": 0, "units_billed": 0}})
        if not j["charged"]:
            with self.st.lock:
                j["charged"] = True
                j["url"] = None
            self._charge("video" if j["kind"] == "videos" else "music", j["paise"])
        if not j.get("url"):
            j["url"] = self._file_url(*j["output"])
        return self._send(200, {"id": jid, "status": "succeeded",
                                "output": [{"url": j["url"], "mime": j["output"][1]}],
                                "billing": {"units_billed": j["seconds"], "charged_paise": j["paise"]}})

    def _speech(self, body):
        if self.st.has("block"):
            return self._err(400, "content_blocked", "the safety filter blocked this text")
        if not body.get("input"):
            return self._err(400, "bad_request", "input is required")
        secs = max(0.5, min(5.0, len(body["input"]) / 15.0))
        self._charge("voice", PAISE["voice"])
        return self._send(200, wav(secs), "audio/wav", {"X-Hidrogen-Charged-Paise": str(PAISE["voice"])})

    def _judge(self, body):
        texts = [c.get("text", "") for c in body.get("content", []) if c.get("type") == "text"]
        text = "\n".join(texts)
        billing = self._charge("judge", PAISE["judge"])
        if "<questions>" in text:
            if self.st.has("judge_bad_json_once"):
                with self.st.lock:
                    self.st.behaviours.discard("judge_bad_json_once")
                return self._send(200, {"text": "looks good to me", "billing": billing})
            return self._send(200, {"result": judge_answers(self.st, text), "billing": billing})
        n_media = len(body.get("content", [])) - len(texts)
        return self._send(200, {"result": {"ok": True, "media": n_media}, "billing": billing})

    def _quote(self, body):
        kind = body.get("kind", "chat")
        paise = PAISE.get(kind, 100)
        if kind == "video":
            paise = PAISE["video"] * float(body.get("seconds") or 4)
        return self._send(200, {"currency": "INR", "kind": kind, "estimate_paise": paise})


# ---------------------------------------------------------------- server
class MockHidrogen(object):
    """In-process mock server. start() returns the URL; use as a context manager in tests."""

    def __init__(self, behaviours=(), port=0, host="127.0.0.1"):
        unknown = [b for b in behaviours if b not in BEHAVIOURS]
        if unknown:
            raise ValueError("unknown mock behaviour(s): %s" % ", ".join(unknown))
        self.state = State(behaviours)
        self.httpd = ThreadingHTTPServer((host, port), Handler)
        self.httpd.daemon_threads = True
        self.httpd.state = self.state
        self.thread = None

    @property
    def url(self):
        h, p = self.httpd.server_address[:2]
        return "http://%s:%d" % (h, p)

    @property
    def requests(self):
        return list(self.state.requests)

    @property
    def charges(self):
        return list(self.state.charges)

    def set_behaviours(self, behaviours):
        with self.state.lock:
            self.state.behaviours = set(behaviours)

    def start(self):
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()
        return self.url

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()


def serve_forever(port=0, behaviours=()):
    m = MockHidrogen(behaviours, port=port)
    print(m.url, flush=True)
    sys.stderr.write("mock Hidrogen at %s (behaviours: %s). Use HIDROGEN_API_URL=%s "
                     "HIDROGEN_API_KEY=hi_test_0000000000000000fake. Ctrl-C stops.\n"
                     % (m.url, ",".join(sorted(behaviours)) or "none", m.url))
    try:
        m.httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        m.httpd.server_close()


def main(argv=None):
    ap = argparse.ArgumentParser(description="offline mock Hidrogen server")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--behaviour", default=os.environ.get("BB_MOCK_BEHAVIOUR", ""),
                    help="comma list: " + ", ".join(sorted(BEHAVIOURS)))
    a = ap.parse_args(argv)
    serve_forever(a.port, [b for b in a.behaviour.split(",") if b])


if __name__ == "__main__":
    main()
