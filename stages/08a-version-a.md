# Stage 8A: Version A (Hidrogen video)

**Made by:** Hidrogen image-to-video per live shot (the keyframe as first frame), ffmpeg cut, the stage 7 mix,
captions. **Output:** `clips/cut/<shot>.mp4` per live shot, then `out/A/<slug>_A_<ratio>.mp4`. **Rubrics:**
`rubrics/clips.json` (the clips) and `rubrics/version_a.json` (the whole video), judged against `screenplay.json`.
Stage `video_a` passes when both have passed.

## First: is the video endpoint live?

`bb doctor` probes `/v1/videos`. If it is not live (HTTP 404), skip Version A with a clear note and go on to
Version B, which is always made:

```
python3 scripts/bb.py mark video_a skipped -p <folder> --note "/v1/videos not live on the gateway"
```

## Do

```
python3 scripts/bb.py clips make -p <folder> --dry-run     # shows the seconds to be generated and the ledger check
python3 scripts/bb.py clips make -p <folder>
python3 scripts/bb.py gate clips -p <folder>
python3 scripts/bb.py version_a -p <folder>
python3 scripts/bb.py gate version_a -p <folder>
```

- Each clip is generated longer than its shot (4-10 s) and the cut uses the **early window**: the model adds actions
  later in a take. A take that drifts is made again with the judge's fix, up to `max_takes`.
- Video seconds are the most expensive part. The ledger reserves every take before it is sent and refuses to pass
  the cap; if the cap is not enough, stop and ask the user (permission point 4). Never raise it yourself.
- Model audio is discarded. Captions and every word on screen are overlays.

## Rules

- One small action in the used window; nobody enters or leaves frame; faces and hands stable.
- No text, logos, emblems or number plates in any clip (hard).
- Every claim shown or said is in research.md (hard).

## Gate loop

`bb restructure clips` (or `version_a`) rewrites `clips/prompts.json`; make the changed clips again, rebuild,
gate again.

## Done when

`bb gate clips` and `bb gate version_a` have passed, or video_a is marked skipped with the reason.
