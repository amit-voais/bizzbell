"""Plan + brand -> one HyperFrames project per ratio: <project>/hf/<ratio>/index.html + assets/.

Each ratio is laid out again (type sizes, caption width, card panels, image fit), never cropped from another.
The template lives in <skill>/hyperframes/ (composition.html, style.css, motion.js); this module fills it.
Motion is the Web Animations API, one animation per element, timed in absolute composition seconds, so frames
depend only on their time. Fonts: the brand fonts and Noto Sans Devanagari (when the text has Devanagari) are
named in a Google Fonts link; HyperFrames downloads, caches and inlines them at render time, and the font stack
falls back to the system's Devanagari fonts when offline."""
import hashlib
import html
import json
import math
import os
import re
import shutil
import struct

from .. import project, util
from ..errors import UsageError
from . import formats, icons, screenplay

TEMPLATE_DIR = os.path.join(util.ROOT_DIR, "hyperframes")
DEVANAGARI = re.compile(u"[ऀ-ॿ]")
EASE_OUT = "cubic-bezier(0.2, 0.7, 0.2, 1)"
EASE_CAM = "cubic-bezier(0.37, 0, 0.63, 1)"
SYSTEM_FONTS = {"system-ui", "sans-serif", "serif", "helvetica", "arial", "georgia", "-apple-system"}

DEFAULT_BRAND = {"name": "", "cta": "", "logo": "",
                 "colors": {"ink": "#101318", "paper": "#F7F4EE", "accent": "#F2B53A"},
                 "fonts": {"display": "Inter", "text": "Inter"}}


# ---------------------------------------------------------------- brand + colour
def _hex(c, default):
    c = str(c or "").strip()
    if re.match(r"^#[0-9a-fA-F]{6}$", c):
        return c.upper()
    if re.match(r"^#[0-9a-fA-F]{3}$", c):
        return ("#" + "".join(ch * 2 for ch in c[1:])).upper()
    return default


def _rgb(c):
    return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))


def luminance(c):
    def ch(v):
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = _rgb(c)
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _mix(c, other, t):
    a, b = _rgb(c), _rgb(other)
    return "#%02X%02X%02X" % tuple(int(round(x + (y - x) * t)) for x, y in zip(a, b))


def _rgba(c, alpha):
    return "rgba(%d, %d, %d, %.2f)" % (_rgb(c) + (alpha,))


def brand(settings):
    """bizzbell.json "brand" merged over the defaults, with derived colours that keep text readable."""
    b = util.deep_merge(DEFAULT_BRAND, settings.get("brand") or {})
    col = b.get("colors") or {}
    ink = _hex(col.get("ink") or col.get("dark") or col.get("text"), DEFAULT_BRAND["colors"]["ink"])
    paper = _hex(col.get("paper") or col.get("light") or col.get("background"), DEFAULT_BRAND["colors"]["paper"])
    accent = _hex(col.get("accent") or col.get("primary"), DEFAULT_BRAND["colors"]["accent"])
    if contrast(ink, paper) < 7:                      # keep body text readable whatever the brand says
        ink, paper = "#101318", "#F7F4EE"
    on_accent = ink if contrast(accent, ink) >= contrast(accent, "#FFFFFF") else "#FFFFFF"
    accent_ink = accent
    t = 0.0
    while contrast(accent_ink, paper) < 3.2 and t < 1.0:   # accent used as text on paper (large type)
        t += 0.1
        accent_ink = _mix(accent, ink, t)
    cap_hl, t = accent, 0.0
    while contrast(cap_hl, ink) < 4.5 and t < 1.0:          # the spoken word's colour on the caption pill
        t += 0.1
        cap_hl = _mix(accent, "#FFFFFF", t)
    fonts = b.get("fonts") or {}
    b["c"] = {"cap_hl": cap_hl, "ink": ink, "paper": paper, "accent": accent, "on_accent": on_accent,
              "accent_ink": accent_ink,
              "ink2": _mix(ink, accent, 0.12), "accent_soft": _rgba(accent, 0.24), "cap_bg": _rgba(ink, 0.9)}
    b["display"] = str(fonts.get("display") or "Inter")
    b["text"] = str(fonts.get("text") or fonts.get("body") or b["display"])
    return b


def font_stack(family):
    fams = ['"%s"' % family.replace('"', "")]
    fams += ['"Noto Sans Devanagari"', '"Kohinoor Devanagari"', '"Devanagari Sangam MN"', '"Nirmala UI"',
             "system-ui", "sans-serif"]
    return ", ".join(fams)


def font_link(b, needs_devanagari):
    fams = []
    for f in (b["display"], b["text"]):
        if f.lower() not in SYSTEM_FONTS and f not in fams:
            fams.append(f)
    if needs_devanagari:
        fams.append("Noto Sans Devanagari")
    if not fams:
        return ""
    q = "&".join("family=%s:wght@500;700;800" % f.replace(" ", "+") for f in fams)
    return '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?%s&display=block" />' % html.escape(q)


# ---------------------------------------------------------------- text fitting (estimate; the audit verifies)
def _char_em(ch):
    if DEVANAGARI.match(ch):
        return 0.6
    if ch == " ":
        return 0.27
    if ch.isupper() or ch in "MWmw@%":
        return 0.7
    if ch.isdigit():
        return 0.62
    if ch in "iljtf.,:;'!|":
        return 0.3
    return 0.56


def text_em(text):
    return sum(_char_em(c) for c in text)


def fit(text, base, max_w, max_h, line_h=1.1, min_px=22):
    """Largest font size <= base (px) at which `text` should fit max_w x max_h when wrapped at word breaks."""
    words = text.split() or [""]
    fs = float(base)
    while fs > min_px:
        longest = max(text_em(w) for w in words) * fs
        lines = 0
        cur = 0.0
        for w in words:
            ww = text_em(w) * fs
            if cur and cur + 0.27 * fs + ww > max_w * 0.94:
                lines += 1
                cur = ww
            else:
                cur += (0.27 * fs if cur else 0) + ww
        lines += 1
        if longest <= max_w * 0.94 and lines * fs * line_h <= max_h:
            break
        fs *= 0.93
    return int(max(min_px, round(fs)))


# ---------------------------------------------------------------- images
def image_size(path):
    """(width, height) of a PNG/JPEG/WebP from its header, or None."""
    try:
        with open(path, "rb") as f:
            head = f.read(64 * 1024)
    except OSError:
        return None
    if head[:8] == b"\x89PNG\r\n\x1a\n" and len(head) >= 24:
        return struct.unpack(">II", head[16:24])
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        if head[12:16] == b"VP8X":
            return (1 + int.from_bytes(head[24:27], "little"), 1 + int.from_bytes(head[27:30], "little"))
        if head[12:16] == b"VP8 ":
            w, h = struct.unpack("<HH", head[26:30])
            return (w & 0x3FFF, h & 0x3FFF)
        return None
    if head[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(head):
            if head[i] != 0xFF:
                i += 1
                continue
            marker = head[i + 1]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                h, w = struct.unpack(">HH", head[i + 5:i + 9])
                return (w, h)
            i += 2 + struct.unpack(">H", head[i + 2:i + 4])[0]
    return None


def _link_or_copy(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst):
        os.remove(dst)
    try:
        os.link(src, dst)
    except OSError:
        shutil.copyfile(src, dst)


# ---------------------------------------------------------------- animations
def _anim(sel, kf, start, dur, ease="linear"):
    return {"sel": sel, "kf": kf, "start": round(start, 3), "dur": round(max(dur, 0.01), 3), "ease": ease}


CAMERA_KF = {
    "push": ("scale(1.03)", "scale(1.11)"),
    "pull": ("scale(1.11)", "scale(1.03)"),
    "pan_left": ("scale(1.1) translateX(2.4%)", "scale(1.1) translateX(-2.4%)"),
    "pan_right": ("scale(1.1) translateX(-2.4%)", "scale(1.1) translateX(2.4%)"),
    "tilt_up": ("scale(1.1) translateY(-2.4%)", "scale(1.1) translateY(2.4%)"),
    "tilt_down": ("scale(1.1) translateY(2.4%)", "scale(1.1) translateY(-2.4%)"),
    "still": ("scale(1.02)", "scale(1.045)"),
}


def _rise(sel, at, u, dist=26, dur=0.5):
    return _anim(sel, [{"opacity": 0, "transform": "translateY(%dpx)" % round(dist * u)},
                       {"opacity": 1, "transform": "translateY(0px)"}], at, dur, EASE_OUT)


def _word_anim(sel, w, cs, ce, accent, white="#FFFFFF"):
    """One animation per caption word over its chunk: appears as it is spoken, accent while spoken."""
    span = max(ce - cs, 0.05)

    def off(t):
        return round(min(1.0, max(0.0, (t - cs) / span)), 4)
    ws = max(cs, w["start"])
    we = max(ws + 0.14, min(w["end"], ce))
    kf = [{"offset": 0.0, "opacity": 0, "transform": "translateY(0.22em)", "color": accent},
          {"offset": off(ws), "opacity": 0, "transform": "translateY(0.22em)", "color": accent},
          {"offset": off(ws + 0.12), "opacity": 1, "transform": "translateY(0em)", "color": accent},
          {"offset": off(we), "opacity": 1, "transform": "translateY(0em)", "color": accent},
          {"offset": off(we + 0.1), "opacity": 1, "transform": "translateY(0em)", "color": white},
          {"offset": 1.0, "opacity": 1, "transform": "translateY(0em)", "color": white}]
    return _anim(sel, kf, cs, span)


# ---------------------------------------------------------------- building blocks
def _attr(s):
    return html.escape(str(s), quote=True)


def _caption_layout(ratio):
    f = formats.FORMATS[ratio]
    landscape = f["w"] > f["h"]
    return {"max_words": 4 if landscape else 3, "max_chars": 28 if landscape else 18,
            "fs": 58 if landscape else 66}


def _graphic_html(shot, b, ratio, panel_h, u, anims, assets):
    g = shot["graphic"]
    sid = shot["id"]
    l, t, r, _ = formats.safe_box(ratio)
    pw = r - l
    dark = g["type"] == "endcard" or bool(shot["image"])
    parts, order = [], []
    if g["type"] == "endcard":
        logo = assets.get("logo")
        if logo:
            parts.append('<img id="%s-logo" class="bb-logo" src="%s" alt="" />' % (sid, _attr(logo)))
            order.append("#%s-logo" % sid)
        name = g["title"] or b.get("name") or ""          # the end card's big line is the brand name
        if name:
            fs = fit(name, 128 * u, pw, panel_h * 0.32, 1.02)
            parts.append('<div id="%s-brand" class="bb-brand" data-bb-text style="font-size:%dpx">%s</div>'
                         % (sid, fs, html.escape(name)))
            order.append("#%s-brand" % sid)
        if g["subtitle"]:
            fs = fit(g["subtitle"], 54 * u, pw, panel_h * 0.22, 1.3)
            parts.append('<div id="%s-sub" class="bb-sub" data-bb-text style="font-size:%dpx">%s</div>'
                         % (sid, fs, html.escape(g["subtitle"])))
            order.append("#%s-sub" % sid)
        cta = g["cta"] or b.get("cta") or ""
        if cta:
            fs = fit(cta, 50 * u, pw * 0.8, 70 * u, 1.1)
            parts.append('<div id="%s-cta" class="bb-cta" data-bb-text style="--cta-fs:%dpx;font-size:%dpx">'
                         '<span>%s</span>%s</div>' % (sid, fs, fs, html.escape(cta),
                                                      icons.svg("arrow", int(fs * 0.9), 2.4)))
            order.append("#%s-cta" % sid)
    elif g["type"] == "number":
        if g["number"]:
            fs = fit(g["number"], 300 * u, pw, panel_h * 0.45, 0.95)
            parts.append('<div id="%s-num" class="bb-number" data-bb-text style="font-size:%dpx">%s</div>'
                         % (sid, fs, html.escape(g["number"])))
            order.append("#%s-num" % sid)
        for key, cls, base, frac in (("label", "bb-title", 64, 0.24), ("title", "bb-title", 64, 0.24),
                                     ("subtitle", "bb-sub", 40, 0.18)):
            if g[key] and not (key == "title" and g["label"] == g["title"]):
                fs = fit(g[key], base * u, pw, panel_h * frac, 1.12)
                parts.append('<div id="%s-%s" class="%s" data-bb-text style="font-size:%dpx">%s</div>'
                             % (sid, key, cls, fs, html.escape(g[key])))
                order.append("#%s-%s" % (sid, key))
    else:
        icon = icons.svg(g["icon"], 64)
        if icon:
            parts.append('<div id="%s-badge" class="bb-badge">%s</div>' % (sid, icon))
            order.append("#%s-badge" % sid)
        if g["title"]:
            fs = fit(g["title"], 96 * u, pw, panel_h * (0.34 if g["number"] else 0.5), 1.06)
            parts.append('<div id="%s-title" class="bb-title" data-bb-text style="font-size:%dpx">%s</div>'
                         % (sid, fs, html.escape(g["title"])))
            order.append("#%s-title" % sid)
        if g["number"]:
            fs = fit(g["number"], 132 * u, pw, panel_h * 0.22, 0.95)
            parts.append('<div id="%s-num" class="bb-number" data-bb-text style="font-size:%dpx">%s</div>'
                         % (sid, fs, html.escape(g["number"])))
            order.append("#%s-num" % sid)
        if g["subtitle"]:
            fs = fit(g["subtitle"], 44 * u, pw, panel_h * 0.25, 1.3)
            parts.append('<div id="%s-sub" class="bb-sub" data-bb-text style="font-size:%dpx">%s</div>'
                         % (sid, fs, html.escape(g["subtitle"])))
            order.append("#%s-sub" % sid)
    if g["sample"] or shot.get("sample"):
        parts.append('<div id="%s-sample" class="bb-sample" data-bb-text>Sample</div>' % sid)
        order.append("#%s-sample" % sid)
    for i, sel in enumerate(order):
        anims.append(_rise(sel, shot["start"] + 0.08 + 0.09 * i, u))
    anims.append(_anim("#%s-glow" % sid, [{"transform": "scale(1)"}, {"transform": "scale(1.08)"}],
                       shot["start"], shot["end"] - shot["start"], EASE_CAM))
    bg = ""
    if shot["image"]:
        bg = ('<div class="bb-cam" id="%s-cam"><img class="bb-still" src="%s" alt="" data-layout-allow-overflow />'
              '</div><div class="bb-backdrop" style="opacity:0.78"></div>' % (sid, _attr(assets[shot["image"]])))
        anims.append(_anim("#%s-cam" % sid, [{"transform": "scale(1.03)"}, {"transform": "scale(1.09)"}],
                           shot["start"], shot["end"] - shot["start"], EASE_CAM))
    return ('<div id="shot-%s" class="clip bb-shot bb-graphic%s" data-start="%s" data-duration="%s" '
            'data-track-index="0">%s<div class="bb-glow" id="%s-glow" data-layout-ignore></div>'
            '<div class="bb-panel" style="--panel-b:%dpx">%s</div></div>'
            % (sid, " bb-dark" if dark else "", shot["start"], round(shot["end"] - shot["start"], 3), bg, sid,
               t + panel_h, "".join(parts)))


def _image_html(shot, ratio, u, anims, assets):
    sid = shot["id"]
    f = formats.FORMATS[ratio]
    dur = round(shot["end"] - shot["start"], 3)
    inner = []
    if shot["image"]:
        src = _attr(assets[shot["image"]])
        size = image_size(shot["image"])
        contain = False
        if size and size[1]:
            contain = abs(math.log((size[0] / float(size[1])) / (f["w"] / float(f["h"])))) > math.log(2.0)
        if contain:
            inner.append('<img class="bb-blur" src="%s" alt="" data-layout-ignore />' % src)
            inner.append('<div class="bb-cam" id="%s-cam"><img class="bb-still bb-contain" src="%s" alt="" '
                         'data-layout-allow-overflow /></div>' % (sid, src))
        else:
            inner.append('<div class="bb-cam" id="%s-cam"><img class="bb-still" src="%s" alt="" '
                         'style="object-position:50%% 40%%" data-layout-allow-overflow /></div>' % (sid, src))
    else:
        inner.append('<div class="bb-cam bb-backdrop" id="%s-cam" data-layout-allow-overflow></div>' % sid)
    a, b = CAMERA_KF.get(shot["camera"], CAMERA_KF["push"])
    anims.append(_anim("#%s-cam" % sid, [{"transform": a}, {"transform": b}], shot["start"], dur, EASE_CAM))
    inner.append('<div class="bb-shade" data-layout-ignore></div>')
    if shot["overlay"]:
        fs = fit(shot["overlay"], 40 * u, (formats.safe_box(ratio)[2] - formats.safe_box(ratio)[0]) * 0.8,
                 140 * u, 1.15)
        inner.append('<div class="bb-chip-row"><div id="%s-chip" class="bb-chip" data-bb-text '
                     'style="--chip-fs:%dpx;font-size:%dpx">%s<span>%s</span></div></div>'
                     % (sid, fs, fs, icons.svg("spark", int(fs * 1.1), 2.0), html.escape(shot["overlay"])))
        anims.append(_rise("#%s-chip" % sid, shot["start"] + 0.2, u, 18))
    return ('<div id="shot-%s" class="clip bb-shot" data-start="%s" data-duration="%s" data-track-index="0">'
            '%s</div>' % (sid, shot["start"], dur, "".join(inner)))


def _overlay_html(o, ratio, u, anims):
    l, _, r, _ = formats.safe_box(ratio)
    fs = fit(o["text"], 40 * u, (r - l) * 0.8, 140 * u, 1.15)
    anims.append(_rise("#%s-chip" % o["id"], o["start"] + 0.05, u, 18))
    return ('<div id="%s" class="clip bb-cap" data-start="%s" data-duration="%s" data-track-index="1">'
            '<div class="bb-chip-row"><div id="%s-chip" class="bb-chip" data-bb-text '
            'style="--chip-fs:%dpx;font-size:%dpx">%s<span>%s</span></div></div></div>'
            % (o["id"], o["start"], round(o["end"] - o["start"], 3), o["id"], fs, fs,
               icons.svg("spark", int(fs * 1.1), 2.0), html.escape(o["text"])))


def _captions_html(chunks, ratio, b, duration, u, cap_fs, anims):
    out = []
    accent = b["c"]["cap_hl"]
    for k, c in enumerate(chunks):
        cs = c["start"]
        ce = min(c["end"], duration)
        if ce - cs < 0.05:
            continue
        cid = "cap-%03d" % k
        spans = []
        for j, w in enumerate(c["words"]):
            wid = "w-%03d-%d" % (k, j)
            spans.append('<span class="bb-w" id="%s">%s</span>' % (wid, html.escape(w["text"])))
            anims.append(_word_anim("#" + wid, w, cs, ce, accent))
        anims.append(_anim("#%s-box" % cid, [{"opacity": 0, "transform": "scale(0.96)"},
                                             {"opacity": 1, "transform": "scale(1)"}], cs, 0.12, EASE_OUT))
        out.append('<div id="%s" class="clip bb-cap" data-start="%s" data-duration="%s" data-track-index="2">'
                   '<div class="bb-cap-row"><div id="%s-box" class="bb-cap-box" data-bb-text '
                   'style="--cap-fs:%dpx;font-size:%dpx">%s</div></div></div>'
                   % (cid, cs, round(ce - cs, 3), cid, cap_fs, cap_fs, " ".join(spans)))
    return out


def _vars(ratio, b, cap_fs):
    f = formats.FORMATS[ratio]
    l, t, r, bot = formats.safe_box(ratio)
    c = b["c"]
    return (":root { --W: %dpx; --H: %dpx; --u: %.4f; --sl: %dpx; --st: %dpx; --sr: %dpx; --sb: %dpx; "
            "--panel-b: %dpx; --ink: %s; --ink-2: %s; --paper: %s; --accent: %s; --on-accent: %s; "
            "--accent-ink: %s; --accent-soft: %s; --cap-bg: %s; --cap-fs: %dpx; --chip-fs: 40px; --cta-fs: 50px; "
            "--font-display: %s; --font-text: %s; }"
            % (f["w"], f["h"], formats.unit(ratio), l, t, r, bot, bot, c["ink"], c["ink2"], c["paper"], c["accent"],
               c["on_accent"], c["accent_ink"], c["accent_soft"], c["cap_bg"], cap_fs, font_stack(b["display"]),
               font_stack(b["text"])))


# ---------------------------------------------------------------- build
def _template(name):
    text = util.read_text(os.path.join(TEMPLATE_DIR, name))
    if not text:
        raise UsageError("the HyperFrames template file hyperframes/%s is missing from the skill" % name)
    return text


def composition_hash(folder):
    """sha256 (16 hex) over index.html and every asset of one ratio's HyperFrames project."""
    h = hashlib.sha256()
    for rel in ["index.html"] + sorted(os.path.join("assets", n) for n in
                                       (os.listdir(os.path.join(folder, "assets"))
                                        if os.path.isdir(os.path.join(folder, "assets")) else [])):
        p = os.path.join(folder, rel)
        if os.path.isfile(p):
            h.update(rel.encode())
            with open(p, "rb") as fh:
                h.update(hashlib.sha256(fh.read()).digest())
    return h.hexdigest()[:16]


def build_ratio(root, plan, ratio, b, lang="en"):
    """Write <root>/hf/<ratio>/ (index.html + assets/). Returns {ratio, dir, hash, chunks, text_items}."""
    ratio = formats.name(ratio)
    f = formats.FORMATS[ratio]
    u = formats.unit(ratio)
    folder = os.path.join(root, "hf", ratio)
    if os.path.isdir(os.path.join(folder, "assets")):
        shutil.rmtree(os.path.join(folder, "assets"))
    os.makedirs(os.path.join(folder, "assets"), exist_ok=True)

    assets = {}
    for shot in plan["shots"]:
        if shot["image"] and shot["image"] not in assets:
            ext = os.path.splitext(shot["image"])[1].lower()
            rel = "assets/%s%s" % (shot["id"], ext)
            _link_or_copy(shot["image"], os.path.join(folder, rel))
            assets[shot["image"]] = rel
    logo = str(b.get("logo") or "")
    if logo:
        lp = logo if os.path.isabs(logo) else os.path.join(root, logo)
        if os.path.isfile(lp) and lp.lower().endswith(screenplay.IMAGE_EXT + (".svg",)):
            rel = "assets/logo%s" % os.path.splitext(lp)[1].lower()
            _link_or_copy(lp, os.path.join(folder, rel))
            assets["logo"] = rel

    cl = _caption_layout(ratio)
    chunks = screenplay.chunk(plan["words"], cl["max_words"], cl["max_chars"])
    l, t, r, bot = formats.safe_box(ratio)
    longest = max([max(text_em(w["text"]) for w in c["words"]) for c in chunks] or [1.0])
    cap_fs = int(min(cl["fs"] * u, (r - l) * 0.86 / max(longest, 1.0)))
    cap_band = int(cap_fs * 1.14 * 2 + cap_fs * 0.5 + 44 * u)

    anims, body = [], []
    duration = plan["duration"]
    for shot in plan["shots"]:
        if shot["kind"] == "graphic":
            capped = any(c["start"] < shot["end"] and c["end"] > shot["start"] for c in chunks)
            panel_h = (bot - t) - (cap_band if capped else 0)
            body.append(_graphic_html(shot, b, ratio, panel_h, u, anims, assets))
        else:
            body.append(_image_html(shot, ratio, u, anims, assets))
    for o in plan.get("overlays", []):
        body.append(_overlay_html(o, ratio, u, anims))
    body += _captions_html(chunks, ratio, b, duration, u, cap_fs, anims)

    audio = plan["audio"]
    tracks = [("bb-mix", audio.get("mix"), 1.0)] if audio.get("mix") else \
        [("bb-vo", audio.get("vo"), 1.0), ("bb-music", audio.get("music"), 0.32 if audio.get("vo") else 0.8)]
    for i, (aid, src, vol) in enumerate(tracks):
        if src:
            rel = "assets/%s%s" % (aid[3:], os.path.splitext(src)[1].lower())
            _link_or_copy(src, os.path.join(folder, rel))
            body.append('<audio id="%s" src="%s" data-start="0" data-duration="%s" data-track-index="%d" '
                        'data-volume="%s"></audio>' % (aid, rel, duration, 8 + i, vol))

    all_text = " ".join([w["text"] for w in plan["words"]] + [s["overlay"] for s in plan["shots"]] +
                        [o["text"] for o in plan.get("overlays", [])] +
                        [" ".join(v for v in (s["graphic"] or {}).values() if isinstance(v, str))
                         for s in plan["shots"]] + [b.get("name") or "", b.get("cta") or ""])
    plan_json = json.dumps({"anims": anims}, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    page = _template("composition.html")
    for key, val in (("{{lang}}", _attr(lang or "en")), ("{{width}}", str(f["w"])), ("{{height}}", str(f["h"])),
                     ("{{title}}", html.escape(plan.get("title") or "Version B")),
                     ("{{duration}}", str(duration)),
                     ("{{font_link}}", font_link(b, bool(DEVANAGARI.search(all_text)))),
                     ("{{vars}}", _vars(ratio, b, cap_fs)), ("{{style}}", _template("style.css")),
                     ("{{body}}", "\n".join(body)), ("{{plan}}", plan_json),
                     ("{{motion}}", _template("motion.js"))):
        page = page.replace(key, val)
    util.write_text(os.path.join(folder, "index.html"), page)
    return {"ratio": ratio, "dir": folder, "hash": composition_hash(folder), "chunks": len(chunks),
            "cap_fs": cap_fs, "width": f["w"], "height": f["h"], "safe": list(formats.safe_box(ratio))}


def _ass_time(t):
    cs = int(round(t * 100))
    return "%d:%02d:%02d.%02d" % (cs // 360000, cs // 6000 % 60, cs // 100 % 60, cs % 100)


def write_captions_ass(root, plan, ratio):
    """out/B/captions.ass: Version B's caption chunks as a subtitle sidecar (what the captions say, and when)."""
    f = formats.FORMATS[ratio]
    cl = _caption_layout(ratio)
    lines = ["[Script Info]", "ScriptType: v4.00+", "PlayResX: %d" % f["w"], "PlayResY: %d" % f["h"], "",
             "[V4+ Styles]",
             "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Alignment, MarginV",
             "Style: Default,Inter,%d,&H00FFFFFF,&H00101318,&H80101318,1,2,%d"
             % (cl["fs"], f["h"] - formats.safe_box(ratio)[3]), "",
             "[Events]", "Format: Layer, Start, End, Style, Text"]
    for c in screenplay.chunk(plan["words"], cl["max_words"], cl["max_chars"]):
        end = min(c["end"], plan["duration"])
        if end > c["start"]:
            text = " ".join(w["text"] for w in c["words"]).replace("\n", " ")
            lines.append("Dialogue: 0,%s,%s,Default,%s" % (_ass_time(c["start"]), _ass_time(end), text))
    util.write_text(os.path.join(root, "out", "B", "captions.ass"), "\n".join(lines) + "\n")


def build(root, ratios=None):
    """Build every ratio's HyperFrames project from screenplay.json. Writes hf/build.json; returns it."""
    plan = screenplay.load(root)
    settings = project.load_settings(root)
    state = project.load_state(root)
    b = brand(settings)
    lang = {"hinglish": "hi-Latn", "hi": "hi"}.get(str(state.get("lang", "en")).lower(), state.get("lang") or "en")
    out = {"time": util.now(), "duration": plan["duration"], "fps": plan["fps"],
           "caption_source": plan["caption_source"], "warnings": plan["warnings"],
           "shots": len(plan["shots"]), "words": len(plan["words"]),
           "shot_times": [[x["start"], x["end"]] for x in plan["shots"]],
           "audio": {k: (os.path.relpath(v, root) if v else None) for k, v in plan["audio"].items()},
           "ratios": {}}
    plan_hash = hashlib.sha256(json.dumps([plan, b, lang, util.read_text(os.path.join(TEMPLATE_DIR, "style.css"))],
                                          sort_keys=True, default=str).encode()).hexdigest()[:16]
    out["plan"] = plan_hash
    for r in formats.parse_list(ratios) if not isinstance(ratios, list) else ratios:
        res = build_ratio(root, plan, r, b, lang)
        res["dir"] = os.path.relpath(res["dir"], root)
        res["plan"] = plan_hash
        out["ratios"][res["ratio"]] = res
    master = formats.name(state.get("aspect") or "9:16")
    write_captions_ass(root, plan, master)
    prev = util.read_json(os.path.join(root, "hf", "build.json"), {}) or {}
    merged = dict(prev.get("ratios") or {})
    merged.update(out["ratios"])
    out["ratios"] = merged
    util.write_json(os.path.join(root, "hf", "build.json"), out)
    return out
