# Stage 6: Keyframes

**Made by:** Hidrogen image, with references. **Output:** `keyframes/<shot>.png`, one per live shot (also
`keyframes/prompts.json` and `keyframes/registry.json`). **Rubric:** `rubrics/keyframes.json`, judged against
`screenplay.json` and `characters/bible.md`.

## Inputs

`screenplay.json`, `characters/sheets/`, `characters/plates/` (passed).

## Do

```
python3 scripts/bb.py keyframes make -p <folder> --dry-run
python3 scripts/bb.py keyframes make -p <folder>
python3 scripts/bb.py gate keyframes -p <folder>
```

The references for each shot are its characters' sheets, its location's plate and the previous approved keyframe
(continuity), plus any `refs` the shot lists. The prompt is the shot's `keyframe_prompt` and camera, its bibles
verbatim, and the continuity rules. Each take is checked locally and judged with this rubric's per-item questions;
a failed take is made again with the judge's fix, up to `max_takes`, then the best one is kept and flagged.

## Rules

- References first; never a text-only frame. Bibles pasted verbatim.
- No text, letters, logos, emblems, insignia or number plates in any keyframe (hard), and no prompt asking for them.
- Five fingers and a real grip; phone screens away from the lens; nobody cut off at the frame edge.
- The same light and screen direction across shots in the same place.

## Gate

```
python3 scripts/bb.py gate keyframes -p <folder>
python3 scripts/bb.py restructure keyframes -p <folder>   # rewrites keyframes/prompts.json; changed shots are made again
python3 scripts/bb.py keyframes make -p <folder>
python3 scripts/bb.py gate keyframes -p <folder>
```

## Done when

`bb gate keyframes` passes.
