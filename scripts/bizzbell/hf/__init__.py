"""Version B (spec stage 8B): a HyperFrames composition filled from screenplay.json, rendered locally.

Modules:
  formats     output sizes and safe zones per ratio (9x16, 1x1, 16x9, 4x5)
  runner      the pinned `npx hyperframes@<version>` and its headless Chrome
  screenplay  screenplay.json (+ audio/words.json) -> a normalised plan: shots, caption words, audio
  icons       the built-in SVG icons (never emoji)
  compose     plan + brand -> <project>/hf/<ratio>/index.html (+ assets), laid out again per ratio
  audit       cut-off text: HyperFrames' own `check` plus a headless DOM bounds check against the safe zone
  repeat      repeatability: frames rendered twice, the second time in shuffled order, compared
  qa          both checks per ratio, saved to out/B/qa.json, tied to a hash of the composition
  render      the MP4s: out/B/<slug>_B_<ratio>.mp4

HyperFrames runs through npx, never vendored. Nothing here makes a paid call."""
