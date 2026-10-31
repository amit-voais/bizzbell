# Stage 9: Final

**Made by:** `bb final`. **Output:** every made version in 9:16, 1:1 and 16:9 (and 4:5 where its text fits), a
phone share copy (`_share.mp4`: H.264 + AAC, at most 720 px on the short side, under 25 MB) and `out/report.md`.
**Rubric:** `rubrics/final.json`, judged against `screenplay.json` and `research.md`. `bb final` runs it once per
version (gate ids `final_a` and `final_b`; it writes the per-version copies into `<folder>/rubrics/` on every
run), so each version gets its own final score.

## Do

```
python3 scripts/bb.py final -p <folder>          # exit 0 both passed, 3 a final gate failed, 7 no budget
python3 scripts/bb.py status -p <folder>
```

What `bb final` does, in order:

1. Version A: builds every missing size from the same shots (`bb version_a build --aspect 1:1` does one by
   hand). Pictures far from a size's shape are shown whole over a blurred copy, never cropped to a sliver.
2. Version B: HyperFrames has rendered every size in stage 8B; if a required size is missing it builds, checks
   and renders all sizes again (then gate `video_b` again).
3. The share copy of each made version, from its master.
4. A draft `out/report.md`, the final gate of each version (paid: media judge), then the report again with the
   final scores.
5. Prints each version's final score, every file path and the report path.

`--no-gate` makes the files and the report without the paid gate. A failed `final_a` / `final_b` is fixed like any
layer: `bb restructure final_a` rewrites the report only, then `bb gate final_a` scores it again (running
`bb final` again rebuilds the report from the project, so do that before a restructure, not after). A flaw in
the film itself goes back to its stage.
`bb gate final` still scores both versions together if you want one number.

`out/report.md` (template `templates/report.md`) holds:

- **Scores:** every layer's gate runs, restructure rounds and final score; each version's score against the
  screenplay;
- **Flaws:** the honest list, shot by shot, of what remains and why it was kept;
- **Claims:** every claim on screen or in the voice with its research.md id and source;
- **Spend:** from the ledger (`bb budget show`), against the cap;
- **AI label:** tell the user to switch on the platform's AI label when they upload.

## Rules

- **Never publish.** Bizzbell does not upload, post or send anything. A render is not a publish.
- Every claim is in research.md (hard); no text inside AI images (hard).

## End of the run

Show the user both versions' scores and the paths of the files (masters, other sizes, share copies, the report).
If Version A was skipped, say why.

## Done when

`out/report.md` exists, the final gate of every made version passes (`bb final` exits 0), and `bb status` says
all stages are done.
