"""Cut-off text check (spec section 9.2): every text element inside the frame and inside the safe zone.

Two parts, both local and free:
  hf_check(folder)  HyperFrames' own `check --json`: lint errors, runtime errors and its layout audit (text outside
                    the canvas or its container, text clipped by its own box). It has no safe-zone test.
  bounds(folder)    so a headless DOM bounds check fills that gap: the composition is loaded in HyperFrames'
                    chrome-headless-shell (`--dump-dom`, no window), every element marked data-bb-text is measured
                    at settled moments of its clip, and its box is compared with the frame and the safe zone.
Fonts in the DOM check come from the same Google Fonts link HyperFrames inlines at render time; offline, both
fall back to the same system fonts, and the result records whether the named fonts loaded."""
import html
import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile

from .. import util
from ..errors import BBError
from . import formats, runner

TOLERANCE_PX = 4
LINT_NOISE = {"nested_structure_needs_subcomposition", "timeline_track_too_dense"}

AUDIT_JS = r"""
(function () {
  var CFG = %(cfg)s;
  function win(el) {
    var s = 0, e = 1e9, n = el;
    while (n && n.getAttribute) {
      if (n.hasAttribute("data-start") && n.id !== "root") {
        var a = parseFloat(n.getAttribute("data-start")) || 0;
        var d = parseFloat(n.getAttribute("data-duration")) || 0;
        s = Math.max(s, a); e = Math.min(e, a + d);
      }
      n = n.parentNode;
    }
    return [s, Math.min(e, CFG.duration)];
  }
  function seek(t) {
    var clips = document.querySelectorAll("[data-start]");
    for (var i = 0; i < clips.length; i++) {
      var c = clips[i];
      if (c.id === "root" || c.tagName === "AUDIO" || c.tagName === "VIDEO") { continue; }
      var a = parseFloat(c.getAttribute("data-start")) || 0, d = parseFloat(c.getAttribute("data-duration")) || 0;
      c.style.visibility = (t >= a && t < a + d) ? "visible" : "hidden";
    }
    document.getAnimations().forEach(function (an) { an.pause(); an.currentTime = t * 1000; });
  }
  function label(el) {
    return (el.id ? "#" + el.id : el.className) + " \"" + (el.textContent || "").trim().slice(0, 60) + "\"";
  }
  function run() {
    var issues = [], checked = 0, tol = CFG.tol, s = CFG.safe;
    var els = document.querySelectorAll("[data-bb-text]");
    for (var i = 0; i < els.length; i++) {
      var el = els[i], w = win(el);
      if (w[1] <= w[0]) { continue; }
      var times = [w[0] + (w[1] - w[0]) * 0.75, Math.max(w[0], w[1] - 0.04)];
      for (var k = 0; k < times.length; k++) {
        var t = Math.round(times[k] * 1000) / 1000;
        seek(t);
        var r = el.getBoundingClientRect();
        if (r.width < 1 || r.height < 1) { continue; }
        checked++;
        var box = {left: Math.round(r.left), top: Math.round(r.top), right: Math.round(r.right),
                   bottom: Math.round(r.bottom)};
        if (r.left < -tol || r.top < -tol || r.right > CFG.w + tol || r.bottom > CFG.h + tol) {
          issues.push({code: "outside_frame", el: label(el), t: t, box: box});
        } else if (r.left < s[0] - tol || r.top < s[1] - tol || r.right > s[2] + tol || r.bottom > s[3] + tol) {
          issues.push({code: "outside_safe_zone", el: label(el), t: t, box: box});
        }
        var cs = getComputedStyle(el);
        if ((cs.overflowX !== "visible" && el.scrollWidth > el.clientWidth + tol) ||
            (cs.overflowY !== "visible" && el.scrollHeight > el.clientHeight + tol)) {
          issues.push({code: "clipped_by_own_box", el: label(el), t: t, box: box,
                       scroll: [el.scrollWidth, el.scrollHeight], client: [el.clientWidth, el.clientHeight]});
        }
        for (var p = el.parentNode; p && p.id !== "root" && p.getAttribute; p = p.parentNode) {
          var ps = getComputedStyle(p);
          if (ps.overflowX === "visible" && ps.overflowY === "visible") { continue; }
          var pr = p.getBoundingClientRect();
          if (r.left < pr.left - tol || r.top < pr.top - tol || r.right > pr.right + tol ||
              r.bottom > pr.bottom + tol) {
            issues.push({code: "clipped_by_container", el: label(el), t: t, box: box,
                         container: (p.id ? "#" + p.id : p.className)});
            break;
          }
        }
      }
    }
    var fonts = {};
    CFG.fonts.forEach(function (f) {
      var q = "800 40px \"" + f + "\"";
      fonts[f] = document.fonts.check(q, "Aa") || document.fonts.check(q, "\u0915");
    });
    var out = document.createElement("pre");
    out.id = "bb-audit-out";
    out.textContent = JSON.stringify({checked: checked, elements: els.length, issues: issues, fonts: fonts});
    document.body.appendChild(out);
  }
  window.addEventListener("load", function () { document.fonts.ready.then(function () { setTimeout(run, 30); }); });
})();
"""


def _families(page):
    fams = re.findall(r"family=([A-Za-z0-9+]+)", page)
    return sorted(set(f.replace("+", " ") for f in fams))


def file_url(path):
    """A percent-encoded file:// URL, so '#', '?', spaces and non-ASCII letters in a folder name stay part of the
    path instead of starting a fragment or a query."""
    return pathlib.Path(os.path.abspath(path)).as_uri()


def bounds(folder, ratio, timeout=120):
    """Headless DOM bounds check of one ratio's composition. Returns {ok, checked, elements, issues, fonts}."""
    ratio = formats.name(ratio)
    f = formats.FORMATS[ratio]
    page = util.read_text(os.path.join(folder, "index.html"))
    if not page:
        raise BBError("no composition at %s (run: bb version_b build)" % folder)
    m = re.search(r'data-duration="([0-9.]+)"', page)
    cfg = {"w": f["w"], "h": f["h"], "safe": list(formats.safe_box(ratio)), "tol": TOLERANCE_PX,
           "duration": float(m.group(1)) if m else 1e9, "fonts": _families(page)}
    base = '<base href="%s/">' % file_url(folder)
    page = page.replace("<head>", "<head>\n" + base, 1)
    page = page.replace("</body>", "<script>%s</script>\n</body>" % (AUDIT_JS % {"cfg": json.dumps(cfg)}), 1)
    chrome = runner.browser_path()
    work = tempfile.mkdtemp(prefix="bb-audit-", dir=os.path.dirname(os.path.abspath(folder)))
    try:
        audit_html = os.path.join(work, "audit.html")
        util.write_text(audit_html, page)
        cmd = [chrome, "--headless", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
               "--no-default-browser-check", "--mute-audio", "--allow-file-access-from-files",
               "--user-data-dir=%s" % os.path.join(work, "profile"), "--force-device-scale-factor=1",
               "--window-size=%d,%d" % (f["w"], f["h"]), "--virtual-time-budget=20000",
               "--dump-dom", file_url(audit_html)]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL,
                               env=runner.env())
        except subprocess.TimeoutExpired:
            hint = "" if runner.headless_shell(chrome) else (
                " with the full Chrome at %s; it needs chrome-headless-shell: run npx -y hyperframes@%s browser "
                "ensure --force, or set HYPERFRAMES_BROWSER_PATH to a chrome-headless-shell" % (chrome, runner.pin()))
            raise BBError("the DOM bounds check timed out after %d s%s" % (timeout, hint))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    m = re.search(r'<pre id="bb-audit-out">(.*?)</pre>', r.stdout or "", re.S)
    if not m:
        raise BBError("the DOM bounds check gave no result (chrome exit %d): %s"
                      % (r.returncode, " ".join((r.stderr or "").strip().splitlines()[-2:])[:300]))
    res = json.loads(html.unescape(m.group(1)))
    res["ok"] = not res["issues"] and res["checked"] > 0
    res["safe"] = cfg["safe"]
    return res


def _findings(section):
    return [f for f in (section or {}).get("findings", []) if isinstance(f, dict)]


def hf_check(folder, root=None, samples=12, timeout=600):
    """HyperFrames' own check. Returns {ok, browser_skipped, errors:[...], text:[...], contrast:[...], warnings:n}.

    errors: lint/runtime errors; text: layout errors or warnings (overflow, clipped, out of canvas);
    contrast: WCAG findings (reported, not part of the cut-off text verdict)."""
    d = runner.run_json(["check", os.path.abspath(folder), "--samples", str(samples)], root=root, timeout=timeout)

    def short(sec, f):
        return {"section": sec, "severity": f.get("severity"), "code": f.get("code"),
                "selector": f.get("selector") or f.get("elementId") or "", "time": f.get("time"),
                "message": str(f.get("message", ""))[:200]}
    errors, text, contrast, warnings = [], [], [], 0
    for sec in ("lint", "runtime"):
        for f in _findings(d.get(sec)):
            if f.get("severity") == "error":
                errors.append(short(sec, f))
            elif f.get("severity") == "warning" and f.get("code") not in LINT_NOISE:
                warnings += 1
    for f in _findings(d.get("layout")):
        if f.get("severity") in ("error", "warning"):
            text.append(short("layout", f))
    for f in _findings(d.get("contrast")):
        if f.get("severity") in ("error", "warning"):
            contrast.append(short("contrast", f))
    skipped = bool(d.get("browserSkipped"))
    return {"ok": bool(d.get("ok")) and not skipped and not errors and not text, "hf_ok": bool(d.get("ok")),
            "browser_skipped": skipped, "errors": errors, "text": text, "contrast": contrast,
            "warnings": warnings, "version": (d.get("_meta") or {}).get("version")}
