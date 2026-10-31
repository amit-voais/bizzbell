"""out/report.md (spec section 10): files, every gate score and round, each version's final score against the
screenplay, the honest flaw list, claims and their sources, spend from the ledger, and the AI-label note.

Everything comes from what is in the project: gates/*.json, project.json, the media registries, out/A/version_a.json,
out/B/qa.json, screenplay.json, research.md and ledger.json. Nothing here calls a model."""
import glob
import os
import re

from . import gate, ledger, project, util

ORDER = ["research", "story", "humanize", "screenplay", "characters", "keyframes", "voice", "music", "mix", "audio",
         "clips", "version_a", "video_a", "video_b", "final", "final_a", "final_b"]
VERSION_OF = {"clips": "A", "version_a": "A", "video_a": "A", "final_a": "A", "video_b": "B", "final_b": "B"}
REGISTRIES = (("characters", "both"), ("keyframes", "both"), ("clips", "A"), ("audio/voice", "both"),
              ("audio/music", "both"))
BAD_ITEM = {"flagged": "no take passed its checks within max_takes; the best take is used",
            "rejected": "rejected", "blocked": "blocked by the safety filter", "skipped": "skipped"}


def _cell(text, n=220):
    t = " ".join(str(text or "").split()).replace("|", "/")
    return t if len(t) <= n else t[:n - 3] + "..."


def _runs(root, layer):
    """[record] of every saved gate run of a layer, oldest first."""
    out = []
    for p in glob.glob(os.path.join(root, "gates", "%s.*.json" % layer)):
        m = re.match(r"^%s\.(\d+)\.json$" % re.escape(layer), os.path.basename(p))
        if m:
            rec = util.read_json(p)
            if isinstance(rec, dict):
                out.append(rec)
    return sorted(out, key=lambda r: r.get("run", 0))


def layers(root):
    """Gate ids with at least one run, in process order."""
    ids = set()
    for p in glob.glob(os.path.join(root, "gates", "*.json")):
        name, _, n = os.path.basename(p)[:-5].rpartition(".")
        if name and n.isdigit():
            ids.add(name)
    return [x for x in ORDER if x in ids] + sorted(ids - set(ORDER))


# ---------------------------------------------------------------- sections
def files_section(root):
    from . import final
    rows = ["| Version | 9:16 | 1:1 | 16:9 | 4:5 | Share copy |", "|---|---|---|---|---|---|"]
    notes = []
    for v in final.VERSIONS:
        have = final.sizes_present(root, v)
        share = final.video_path(root, v, "share")
        name = "A (Hidrogen video)" if v == "A" else "B (HyperFrames)"
        if final.skipped(root, v):
            notes.append("Version %s was skipped: %s" % (v, final.skipped(root, v)))
        if not have:
            rows.append("| %s | not made | | | | |" % name)
            continue
        cells = [have.get(a, "-") for a in ("9:16", "1:1", "16:9", "4:5")]
        sh = "-"
        if os.path.isfile(share):
            sh = "%s (%.1f MB)" % (os.path.relpath(share, root), os.path.getsize(share) / 1048576.0)
        rows.append("| %s | %s | %s |" % (name, " | ".join(cells), sh))
    qa = util.read_json(os.path.join(root, "out", "B", "qa.json"), {}) or {}
    why = ((qa.get("ratios") or {}).get("4x5") or {}).get("skipped")
    if why:
        notes.append("Version B 4:5 was not made: %s" % why)
    return "\n".join(rows + ([""] + notes if notes else []))


def scores_section(root, final_gates=None):
    rows = ["| Layer | Gate runs (score each run) | Restructure rounds | Final score | Passed |",
            "|---|---|---|---|---|"]
    state = project.load_state(root).get("stages", {})
    for layer in layers(root):
        runs = _runs(root, layer)
        if not runs:
            continue
        last = runs[-1]
        st = state.get(layer, {})
        passed = "yes" if last.get("passed") else "no"
        if not last.get("passed") and st.get("status") == "passed":
            passed = "accepted by the user (%s)" % _cell(st.get("note") or "after the rounds ran out", 80)
        rows.append("| %s | %d (%s) | %d | %.1f | %s |"
                    % (layer, len(runs), " -> ".join("%.1f" % r.get("score", 0) for r in runs),
                       int(st.get("restructure_rounds", 0)), last.get("score", 0), passed))
    if len(rows) == 2:
        rows.append("| (no gate has run yet) | | | | |")
    lines = rows + [""]
    for v, layer in (("A", "version_a"), ("B", "video_b")):
        runs = _runs(root, layer)
        fg = (final_gates or {}).get(v) or (_runs(root, "final_%s" % v.lower()) or [None])[-1]
        bits = []
        if runs:
            bits.append("%.1f (gate %s #%d, judged against screenplay.json)" % (runs[-1]["score"], layer,
                                                                                runs[-1]["run"]))
        if fg and "score" in fg:
            bits.append("final gate %.1f %s (%s #%d)" % (fg["score"], "passed" if fg["passed"] else "failed",
                                                        fg["stage"], fg["run"]))
        elif fg and fg.get("error"):
            bits.append("final gate not run: %s" % _cell(fg["error"], 160))
        lines.append("Version %s against the screenplay: %s." % (v, "; ".join(bits) if bits else "not scored"))
    return "\n".join(lines)


def _flaws(root):
    """[(item, version, flaw, where)]."""
    out = []
    va = util.read_json(os.path.join(root, "out", "A", "version_a.json"), {}) or {}
    for s in va.get("shots", []):
        if s.get("flaw"):
            out.append((s["id"], "A", s["flaw"], "Version A assembly"))
    for d, ver in REGISTRIES:
        reg = util.read_json(os.path.join(root, d, "registry.json"), {}) or {}
        for iid, it in sorted((reg.get("items") or {}).items()):
            if iid.startswith("audition:"):
                continue
            why = BAD_ITEM.get(it.get("status"))
            if why:
                note = it.get("note") or ""
                out.append((iid, ver, why + (": " + note if note else ""), "%s/registry.json" % d))
    for layer in layers(root):
        runs = _runs(root, layer)
        if not runs:
            continue
        last = runs[-1]
        for q in gate.failed_questions(last):
            ev = next((e for e in reversed(q.get("evidence") or []) if e), "")
            out.append((layer, VERSION_OF.get(layer, "both"),
                        "%s%s (%s): %s -- %s" % (q["id"], " (hard)" if q.get("hard") else "",
                                                 "/".join(q.get("answers") or []), q["text"], ev),
                        "gate %s #%d" % (layer, last["run"])))
    qa = util.read_json(os.path.join(root, "out", "B", "qa.json"), {}) or {}
    for ratio, rec in sorted((qa.get("ratios") or {}).items()):
        for i in ((rec.get("bounds") or {}).get("issues") or [])[:6]:
            out.append(("%s at %ss" % (i.get("el") or "text", i.get("t", "?")), "B",
                        "%s in %s" % (i.get("code", "text outside the safe zone"), ratio), "out/B/qa.json"))
        rep = rec.get("repeat") or {}
        if rep.get("differing"):
            out.append(("frames %s" % ", ".join("%gs" % t for t in rep["differing"][:6]), "B",
                        "%s: frames differ between two renders" % ratio, "out/B/qa.json"))
    return out


def flaws_section(root):
    rows = ["| Shot / item | Version | Flaw that remains | Found by |", "|---|---|---|---|"]
    found = _flaws(root)
    for item, ver, flaw, where in found:
        rows.append("| %s | %s | %s | %s |" % (_cell(item, 40), ver, _cell(flaw), _cell(where, 40)))
    if not found:
        rows.append("| - | both | No flaw was found by the gates or the local checks. | all gates |")
    rows += ["", "The gates check what their questions ask and nothing else. Watch every size once on a phone "
                 "before you upload."]
    return "\n".join(rows)


def _research(root):
    """({claim id: (text, [source tags])}, {source id: line})."""
    text = util.read_text(os.path.join(root, "research.md"))
    claims, sources = {}, {}
    for m in re.finditer(r"(?m)^\s*[-*]\s*\**(C\d+)\**\s*[:.)-]\s*(.+?)\s*$", text):
        tags = re.findall(r"\[([^\]]+)\]", m.group(2))
        claims[m.group(1)] = (re.sub(r"\s*\[[^\]]+\]\s*$", "", m.group(2)).strip(), tags)
    for m in re.finditer(r"(?m)^\s*[-*]\s*\**(S\d+)\**\s*[:.)-]\s*(.+?)\s*$", text):
        sources[m.group(1)] = m.group(2)
    return claims, sources


def _source_text(tags, sources):
    out = []
    for t in tags:
        for part in re.split(r"[,;]\s*", t):
            part = part.strip()
            if part in sources:
                url = re.search(r"https?://\S+", sources[part])
                out.append("%s %s" % (part, url.group(0) if url else _cell(sources[part], 80)))
            elif part:
                out.append(part)
    return "; ".join(out) or "-"


def claims_section(root):
    claims, sources = _research(root)
    sp = util.read_json(os.path.join(root, "screenplay.json"), {}) or {}
    rows = ["| Claim on screen or in the voice | research.md | Source |", "|---|---|---|"]
    listed = [c for c in sp.get("claims") or [] if isinstance(c, dict) and c.get("text")]
    for c in listed:
        m = re.search(r"\bC\d+\b", str(c.get("source") or ""))
        cid = m.group(0) if m else None
        if cid and cid in claims:
            rows.append("| %s | %s: %s | %s |" % (_cell(c["text"], 80), cid, _cell(claims[cid][0], 90),
                                                  _source_text(claims[cid][1], sources)))
        else:
            rows.append("| %s | NOT FOUND (%s) | - |" % (_cell(c["text"], 80), _cell(c.get("source") or "no source",
                                                                                     60)))
    if not listed:
        for cid, (text, tags) in sorted(claims.items(), key=lambda kv: int(kv[0][1:])):
            rows.append("| (allowed, the screenplay lists no claims) %s | %s | %s |"
                        % (_cell(text, 80), cid, _source_text(tags, sources)))
    if len(rows) == 2:
        rows.append("| (no claims) | | |")
    return "\n".join(rows)


def spend_section(root):
    s = ledger.Ledger(root).summary()
    lines = ["From the ledger (python3 scripts/bb.py budget show): INR %.2f spent of a cap of INR %.2f "
             "(INR %.2f reserved, INR %.2f left), %d paid calls."
             % (s["spent_inr"], s["cap_inr"], s["reserved_inr"], s["remaining_inr"], s["calls"])]
    if s["by_kind"]:
        lines += ["", "| Kind | INR |", "|---|---|"]
        lines += ["| %s | %.2f |" % (k, v) for k, v in sorted(s["by_kind"].items())]
    return "\n".join(lines)


AI_LABEL = ("This film contains AI-generated people and pictures and a synthetic voice. Switch on the platform's "
            "AI label (for example \"Made with AI\" or \"AI info\") when you upload it. Bizzbell did not upload, post "
            "or send anything: nothing was published.")


def build(root, final_gates=None):
    st = project.load_state(root)
    parts = ["# %s: report" % (st.get("slug") or "film"), "",
             "Made with Bizzbell on %s (%s, %s). Nothing was published, uploaded or sent."
             % (util.now()[:10], st.get("lang", "en"), st.get("aspect", "9:16")), "",
             "## Files", "", files_section(root), "",
             "## Scores", "", scores_section(root, final_gates), "",
             "## Flaws", "", flaws_section(root), "",
             "## Claims", "", claims_section(root), "",
             "## Spend", "", spend_section(root), "",
             "## AI label", "", AI_LABEL, ""]
    return "\n".join(parts)


def write(root, final_gates=None):
    path = os.path.join(root, "out", "report.md")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    util.write_text(path, build(root, final_gates))
    return path

