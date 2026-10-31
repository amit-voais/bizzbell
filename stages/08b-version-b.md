# Stage 8B: Version B (HyperFrames)

**Made by:** a HyperFrames composition filled from `screenplay.json`: keyframes and sheets as stills with motion,
kinetic captions, graphic cards and the end card, with the same stage 7 mix. Rendered locally and headless.
**Output:** `out/B/<slug>_B_<ratio>.mp4` and `out/B/qa.json`. **Rubric:** `rubrics/video_b.json`, judged against
`screenplay.json`.

Version B costs no video seconds and no Hidrogen call, so it is always made, even when Version A is skipped.

## Inputs

`screenplay.json`, `keyframes/`, `audio/mix.wav`, and the optional `brand` block in `bizzbell.json` (colours, fonts,
name, call to action).

## Do

```
python3 scripts/bb.py version_b -p <folder>          # build, check, render (the default)
python3 scripts/bb.py gate video_b -p <folder>
```

`version_b build`, `version_b check` and `version_b render` run the steps one at a time. HyperFrames runs through
`npx` at the version pinned in `bizzbell.json` (`hyperframes.version`); it is not copied into this package.

## Checks it runs

- **Cut-off text:** every text box inside the frame and inside the safe zone of each size (HyperFrames' own check,
  then a headless bounds check).
- **Repeatability:** frames rendered twice, the second time in shuffled order, and compared. A frame that differs
  depends on the clock or the render order; it is reported.
- Each size is laid out again, never just cropped; 4:5 is made only where the text fits.

## Rules

- Every word is an overlay in the composition, never inside an AI image. Icons are drawn as SVG, never emoji.
- No frame frozen for more than 3 s: every still moves.
- Captions follow the voice word for word, in Roman script.

## Gate loop

`bb restructure video_b` rewrites `screenplay.json` (captions, graphic text, camera notes); build again and gate
again. Then re-run `bb gate screenplay`, since the screenplay changed.

## Done when

`bb gate video_b` passes.
