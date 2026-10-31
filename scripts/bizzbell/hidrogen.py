"""Hidrogen API client (the only API Bizzbell calls).

- Key: $HIDROGEN_API_KEY, else HIDROGEN_API_KEY=hi_... in ~/.config/hidrogen/key.env (~ follows $HOME).
  The key is never printed: every error text passes through redact().
- URL: $HIDROGEN_API_URL (default https://api.hidrogen.in), read on every call.
- Every POST carries an Idempotency-Key; transient failures (429/5xx/network) are retried with the SAME key,
  so a retry never pays twice.
- The gateway drops `role: system` messages: chat() moves instructions into the top-level "system_prompt".
- 402 -> PaymentRequired (wallet empty, nothing sent), 404 -> NotAvailable (endpoint not live),
  safety block -> Blocked (charged 0).
- Billing is INR. charged_inr(resp) reads what a response says it cost (None when it does not say)."""
import base64
import json
import os
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from .errors import BBError

DEFAULT_API = "https://api.hidrogen.in"
USER_AGENT = "bizzbell/0.1"
RETRY_CODES = (429, 500, 502, 503, 504)
RETRY_BASE = 2.0          # seconds; retry i waits RETRY_BASE * (i + 1). Tests set it to 0.
_SEEN_KEYS = set()        # keys read in this process, so redact() can remove them anywhere


class HidrogenError(BBError):
    """Any failed Hidrogen call. `status` is the HTTP status (None for network errors)."""

    exit_code = 1

    def __init__(self, message, status=None, body=None):
        BBError.__init__(self, redact(message))
        self.status = status
        self.body = redact(body or "")


class KeyMissing(HidrogenError):
    """No key in the environment or the key file."""

    exit_code = 2


class PaymentRequired(HidrogenError):
    """HTTP 402: the wallet cannot cover the call. Nothing was sent or charged."""

    exit_code = 5


class NotAvailable(HidrogenError):
    """HTTP 404: this endpoint is not live on the gateway (yet)."""

    exit_code = 6


class Blocked(HidrogenError):
    """The safety filter blocked the request. Charged 0: rephrase as visible behaviour and retry once."""

    exit_code = 8


# ---------------------------------------------------------------- key, url, redaction

_SSL = None
# Python from python.org on macOS ships without CA certificates until "Install Certificates" is run;
# fall back to the system bundle so a fresh install still reaches the gateway.
_CA_BUNDLES = ("/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt", "/etc/pki/tls/certs/ca-bundle.crt",
               "/opt/homebrew/etc/openssl@3/cert.pem", "/usr/local/etc/openssl@3/cert.pem")


def _ssl_ctx():
    """A verifying SSL context that has CA certificates, from Python's defaults or the system bundle."""
    global _SSL
    if _SSL is None:
        ctx = ssl.create_default_context()
        if not ctx.cert_store_stats().get("x509_ca"):
            for path in _CA_BUNDLES:
                if os.path.exists(path):
                    ctx = ssl.create_default_context(cafile=path)
                    break
        _SSL = ctx
    return _SSL


def api_url():
    """The gateway base URL, without a trailing slash."""
    return (os.environ.get("HIDROGEN_API_URL") or DEFAULT_API).rstrip("/")


def key_file():
    """Path of the key file (follows $HOME, so tests can redirect it)."""
    return os.path.join(os.path.expanduser("~"), ".config", "hidrogen", "key.env")


def key(quiet=False):
    """The API key from $HIDROGEN_API_KEY or the key file. Raises KeyMissing (or returns '' when quiet)."""
    k = os.environ.get("HIDROGEN_API_KEY", "").strip()
    path = key_file()
    if not k and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                m = re.match(r"\s*(?:export\s+)?HIDROGEN_API_KEY\s*=\s*[\"']?([^\"'\s]+)", line)
                if m:
                    k = m.group(1)
    if not k:
        if quiet:
            return ""
        raise KeyMissing("no Hidrogen API key found. Run: python3 scripts/bb.py key "
                         "(or set HIDROGEN_API_KEY). Get a key at hidrogen.in.")
    _SEEN_KEYS.add(k)
    return k


def has_key():
    return bool(key(quiet=True))


def save_key(value):
    """Save the key to the key file with mode 600 (folder 700). Returns the path. Never echoes the key."""
    value = (value or "").strip()
    if not value:
        raise BBError("no key entered; nothing saved")
    if not re.match(r"^hi_[A-Za-z0-9_\-]{8,}$", value):
        raise BBError("that does not look like a Hidrogen key (it should start with hi_); nothing saved")
    _SEEN_KEYS.add(value)
    path = key_file()
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    fd = os.open(path + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write("HIDROGEN_API_KEY=%s\n" % value)
    os.chmod(path + ".tmp", 0o600)
    os.replace(path + ".tmp", path)
    return path


_KEY_RE = re.compile(r"\b(hi|sk)_[A-Za-z0-9_\-]{16,}")
_BEARER_RE = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9_\-\.]{8,}")


def redact(text):
    """`text` with every API key (known or key-shaped) replaced by [redacted]."""
    t = str(text)
    for k in list(_SEEN_KEYS) + [os.environ.get("HIDROGEN_API_KEY", "").strip()]:
        if k and len(k) >= 6:
            t = t.replace(k, "[redacted]")
    t = _BEARER_RE.sub(r"\1[redacted]", t)
    return _KEY_RE.sub("[redacted]", t)


# ---------------------------------------------------------------- transport
def _blocked_text(txt):
    low = (txt or "").lower()
    return "content_blocked" in low or "safety_block" in low


def _error_for(code, txt, path):
    if code == 402:
        return PaymentRequired("your Hidrogen wallet does not have enough balance for this call. Nothing was sent "
                               "or charged. Recharge the wallet at hidrogen.in, then run the step again.", code, txt)
    if code == 404:
        return NotAvailable("%s is not live on this Hidrogen gateway (HTTP 404)." % path.split("?")[0], code, txt)
    if code == 401:
        return HidrogenError("Hidrogen did not accept the key (HTTP 401). Check it with: python3 scripts/bb.py "
                             "doctor, or save a new one with: python3 scripts/bb.py key", code, txt)
    if _blocked_text(txt):
        return Blocked("the safety filter blocked this request (charged 0). Rephrase it as plain visible "
                       "behaviour and try once more.", code, txt)
    return HidrogenError("HTTP %d from %s: %s" % (code, path.split("?")[0], txt[:400]), code, txt)


def request(method, path, body=None, timeout=300, raw=False, idem=None, tries=4, auth=True):
    """Call the gateway. Returns parsed JSON, or (bytes, headers) when raw=True.

    POSTs carry one Idempotency-Key across all retries (pass `idem` to set it yourself)."""
    url = path if path.startswith("http") else api_url() + path
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    if auth:
        headers["Authorization"] = "Bearer " + key()
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if method.upper() == "POST":
        headers["Idempotency-Key"] = idem or ("bb-" + uuid.uuid4().hex)
    last = ""
    for i in range(max(1, tries)):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
            with urllib.request.urlopen(req, timeout=timeout,
                                        context=_ssl_ctx() if url.startswith("https:") else None) as r:
                payload = r.read()
                if raw:
                    return payload, dict(r.headers)
                if not payload:
                    return {}
                return json.loads(payload.decode("utf-8"))
        except urllib.error.HTTPError as e:
            txt = e.read().decode("utf-8", errors="replace")[:2000]
            if e.code in RETRY_CODES and i < tries - 1:
                last = "HTTP %d" % e.code
                time.sleep(RETRY_BASE * (i + 1))
                continue
            raise _error_for(e.code, txt, path)
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            last = "%s: %s" % (type(e).__name__, e)
            if i < tries - 1:
                time.sleep(RETRY_BASE * (i + 1))
                continue
        except ValueError as e:
            raise HidrogenError("the gateway sent a reply that is not JSON (%s)" % e)
    raise HidrogenError("could not reach the Hidrogen gateway at %s (%s)" % (api_url(), last[:300]))


LOOPBACK = ("127.0.0.1", "localhost", "::1")


def safe_result_url(url):
    """Raise HidrogenError unless `url` is https (or http to this machine, for the mock). A result URL from a reply
    must never make Bizzbell read a local file (file://) or speak another protocol."""
    u = urllib.parse.urlsplit(str(url or ""))
    host = (u.hostname or "").lower()
    if not host or not (u.scheme == "https" or (u.scheme == "http" and host in LOOPBACK)):
        raise HidrogenError("refused a result URL that is not https (scheme %r)" % (u.scheme or "none"))
    return url


class _SafeRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        safe_result_url(newurl)
        return urllib.request.HTTPRedirectHandler.redirect_request(self, req, fp, code, msg, headers, newurl)


def download(url, timeout=600):
    """Bytes at a signed result URL (no key needed). Only https (http to 127.0.0.1 for the mock), redirects too."""
    safe_result_url(url)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.build_opener(_SafeRedirects).open(req, timeout=timeout) as r:
            return r.read()
    except HidrogenError:
        raise
    except Exception as e:
        raise HidrogenError("download failed: %s" % redact(e))


def data_url(b64, mime):
    return "data:%s;base64,%s" % (mime, b64)


MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
        ".wav": "audio/wav", ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".mp4": "video/mp4",
        ".mov": "video/quicktime", ".webm": "video/webm"}


def file_data_url(path):
    """A data: URL of a local media file."""
    mime = MIME.get(os.path.splitext(path)[1].lower())
    if not mime:
        raise BBError("unsupported media type: %s" % os.path.basename(path))
    with open(path, "rb") as f:
        return data_url(base64.b64encode(f.read()).decode("ascii"), mime)


def as_url(ref):
    """A file path, http(s) URL or data: URL -> something the gateway accepts."""
    if ref.startswith(("data:", "http://", "https://")):
        return ref
    return file_data_url(ref)


def charged_inr(resp, headers=None):
    """INR charged according to a response (billing.charged_paise / charged_inr, or a header). None if unknown."""
    try:
        b = (resp or {}).get("billing") or {}
        if "charged_paise" in b:
            return round(float(b["charged_paise"]) / 100.0, 2)
        if "charged_inr" in b:
            return round(float(b["charged_inr"]), 2)
    except (AttributeError, TypeError, ValueError):
        pass
    for k, v in (headers or {}).items():
        if k.lower() == "x-hidrogen-charged-paise":
            try:
                return round(float(v) / 100.0, 2)
            except ValueError:
                return None
    return None


def _raise_if_blocked(resp):
    err = (resp or {}).get("error") or {}
    if (resp or {}).get("status") == "blocked" or err.get("code") == "content_blocked":
        raise Blocked("the safety filter blocked this request (charged 0): %s. Rephrase it as plain visible "
                      "behaviour and try once more." % err.get("message", "blocked"))


# ---------------------------------------------------------------- text
def _split_system(messages, system_prompt):
    parts = [system_prompt] if system_prompt else []
    kept = []
    for m in messages:
        if m.get("role") == "system":
            c = m.get("content")
            parts.append(c if isinstance(c, str) else json.dumps(c))
        else:
            kept.append(m)
    return "\n\n".join(p for p in parts if p), kept


def chat(messages, model, system_prompt=None, temperature=0.2, max_tokens=4096, json_mode=False, idem=None,
         timeout=300, extra=None):
    """POST /v1/chat/completions. `messages` is a list of {role, content} or a plain user string.

    role:system messages are removed and joined into the top-level "system_prompt" (the gateway drops them).
    Returns {"text", "model", "usage", "charged_inr", "raw"}."""
    if isinstance(messages, str):
        messages = [{"role": "user", "content": messages}]
    system, kept = _split_system(list(messages), system_prompt)
    body = {"model": model, "messages": kept, "temperature": temperature, "max_tokens": max_tokens}
    if system:
        body["system_prompt"] = system
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    body.update(extra or {})
    r = request("POST", "/v1/chat/completions", body, timeout=timeout, idem=idem)
    try:
        text = r["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        raise HidrogenError("the chat reply had no message content")
    if isinstance(text, list):
        text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
    return {"text": text, "model": r.get("model", model), "usage": r.get("usage", {}),
            "charged_inr": charged_inr(r), "raw": r}


def parse_json_text(text):
    """JSON from a model reply: strips ``` fences and surrounding prose. Raises ValueError."""
    t = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if m:
        t = m.group(1).strip()
    try:
        return json.loads(t)
    except ValueError:
        start = min([i for i in (t.find("{"), t.find("[")) if i >= 0] or [-1])
        if start < 0:
            raise
        end = max(t.rfind("}"), t.rfind("]"))
        return json.loads(t[start:end + 1])


def chat_json(messages, model, system_prompt=None, temperature=0.2, max_tokens=4096, idem=None, timeout=300):
    """chat() that parses the reply as JSON. Returns (obj, reply). Raises HidrogenError when it is not JSON."""
    reply = chat(messages, model, system_prompt=system_prompt, temperature=temperature, max_tokens=max_tokens,
                 json_mode=True, idem=idem, timeout=timeout)
    try:
        return parse_json_text(reply["text"]), reply
    except ValueError:
        raise HidrogenError("the model did not reply with JSON: %s" % reply["text"][:200])


def models():
    """GET /v1/models -> list of model dicts (each has "id")."""
    r = request("GET", "/v1/models", timeout=60)
    data = r.get("data", r.get("models", [])) if isinstance(r, dict) else r
    out = []
    for m in data or []:
        out.append(m if isinstance(m, dict) else {"id": str(m)})
    return out


def balance():
    """GET /v1/balance -> the raw dict."""
    return request("GET", "/v1/balance", timeout=30)


def balance_inr():
    """Wallet balance in INR, or None if the reply does not say."""
    b = balance()
    for k, div in (("balance_paise", 100.0), ("paise", 100.0), ("balance_inr", 1.0), ("inr", 1.0), ("balance", 1.0)):
        if k in b:
            try:
                return round(float(b[k]) / div, 2)
            except (TypeError, ValueError):
                return None
    return None


def quote(kind, model=None, **params):
    """POST /v1/media/quote (free): price of one call before paying. Returns INR (float) or None if unknown.

    kind: image | video | voice | music | judge | chat. params: seconds, count, chars, ... as the call would use."""
    body = dict(params, kind=kind)
    if model:
        body["model"] = model
    r = request("POST", "/v1/media/quote", body, timeout=60)
    for k, div in (("estimate_paise", 100.0), ("quote_paise", 100.0), ("price_paise", 100.0), ("paise", 100.0),
                   ("estimate_inr", 1.0), ("price_inr", 1.0), ("inr", 1.0), ("amount", 1.0)):
        if k in r:
            try:
                return round(float(r[k]) / div, 2)
            except (TypeError, ValueError):
                return None
    return None


# ---------------------------------------------------------------- media
def image(prompt, refs=(), aspect="9:16", size="2K", model="image-pro", idem=None):
    """POST /v1/images/generations. refs: file paths or data URLs. Returns (png bytes, resp). Raises Blocked."""
    body = {"model": model, "prompt": prompt, "references": [as_url(r) for r in refs], "aspect_ratio": aspect,
            "image_size": size or "2K", "response_format": "url"}
    r = request("POST", "/v1/images/generations", body, timeout=420, idem=idem)
    _raise_if_blocked(r)
    try:
        url = r["data"][-1]["url"]
    except (KeyError, IndexError, TypeError):
        raise HidrogenError("the image reply had no image URL")
    return download(url), r


def wait_job(kind, job_id, max_wait=1800, poll_wait=50):
    """Poll GET /v1/<kind>/<id>?wait=N until succeeded/failed/blocked. Raises HidrogenError on timeout."""
    t0 = time.time()
    while True:
        j = request("GET", "/v1/%s/%s?wait=%d" % (kind, job_id, poll_wait), timeout=poll_wait + 40)
        if j.get("status") in ("succeeded", "failed", "blocked", "cancelled"):
            return j
        if time.time() - t0 > max_wait:
            raise HidrogenError("%s: still %s after %ds (the job keeps running; check it later)"
                                % (job_id, j.get("status"), max_wait))


def _finish_job(j):
    _raise_if_blocked(j)
    if j.get("status") != "succeeded":
        raise HidrogenError("%s: %s" % (j.get("id"), (j.get("error") or {}).get("message", j.get("status"))))
    return j


def video(prompt, first_frame=None, last_frame=None, aspect="9:16", resolution="720p", seconds=None,
          model="video", refs=(), idem=None, max_wait=1800, poll_wait=50):
    """POST /v1/videos then wait. Frames/refs: paths or data URLs. Returns (mp4 bytes, job). Raises Blocked."""
    body = {"model": model, "prompt": prompt, "aspect_ratio": aspect, "resolution": resolution}
    if seconds:
        body["seconds"] = seconds
    if first_frame:
        body["first_frame"] = as_url(first_frame)
    if last_frame:
        body["last_frame"] = as_url(last_frame)
    if refs:
        body["references"] = [as_url(r) for r in refs]
    j = request("POST", "/v1/videos", body, timeout=180, idem=idem)
    _raise_if_blocked(j)
    j = _finish_job(wait_job("videos", j["id"], max_wait=max_wait, poll_wait=poll_wait))
    return download(j["output"][0]["url"]), j


def tts(text, voice="priya", model="voice-studio", style="", fmt="wav", idem=None):
    """POST /v1/audio/speech. Returns (audio bytes, {"headers", "charged_inr"}). Raises Blocked."""
    body = {"model": model, "input": text, "voice": voice, "response_format": fmt}
    if style:
        body["style"] = style
    audio, headers = request("POST", "/v1/audio/speech", body, timeout=200, raw=True, idem=idem)
    ctype = ""
    for k, v in headers.items():
        if k.lower() == "content-type":
            ctype = v
    if ctype.startswith("application/json"):
        _raise_if_blocked(json.loads(audio.decode("utf-8") or "{}"))
        raise HidrogenError("the voice reply had no audio")
    return audio, {"headers": headers, "charged_inr": charged_inr(None, headers)}


def music(prompt, seconds=30, instrumental=True, model="music", idem=None, max_wait=1800, poll_wait=50):
    """POST /v1/music then wait. Returns ([(bytes, mime)], job). Raises Blocked."""
    j = request("POST", "/v1/music", {"model": model, "prompt": prompt, "seconds": seconds,
                                      "instrumental": instrumental}, timeout=120, idem=idem)
    _raise_if_blocked(j)
    j = _finish_job(wait_job("music", j["id"], max_wait=max_wait, poll_wait=poll_wait))
    return [(download(o["url"]), o.get("mime", "audio/wav")) for o in j["output"]], j


def media_judge(text, files=(), system_prompt=None, json_out=True, temperature=0.2, max_tokens=8192, model=None,
                idem=None, timeout=600):
    """POST /v1/media/judge with a text prompt and media files (paths or data URLs).

    Returns {"result" (parsed JSON or None), "text", "charged_inr", "raw"}."""
    content = [{"type": "text", "text": text}]
    for f in files:
        url = as_url(f)
        kind = url[5:].split("/")[0] if url.startswith("data:") else "image"
        key_name = {"image": "image_url", "audio": "audio_url", "video": "video_url"}.get(kind, "image_url")
        content.append({"type": key_name, key_name: {"url": url}})
    body = {"content": content, "output": "json" if json_out else "text", "temperature": temperature,
            "max_tokens": max_tokens}
    if system_prompt:
        body["system_prompt"] = system_prompt
    if model:
        body["model"] = model
    r = request("POST", "/v1/media/judge", body, timeout=timeout, idem=idem)
    _raise_if_blocked(r)
    result = r.get("result")
    txt = r.get("text", "")
    if json_out and result is None and txt:
        try:
            result = parse_json_text(txt)
        except ValueError:
            result = None
    return {"result": result, "text": txt or json.dumps(result), "charged_inr": charged_inr(r), "raw": r}


def probe(path):
    """Free existence check of an endpoint (OPTIONS, no body, no charge): 'live', 'missing' or 'unknown'."""
    try:
        request("OPTIONS", path, timeout=20, tries=1)
        return "live"
    except NotAvailable:
        return "missing"
    except HidrogenError as e:
        return "live" if e.status in (400, 401, 405, 422) else "unknown"
