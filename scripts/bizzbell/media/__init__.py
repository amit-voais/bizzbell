"""The media pipeline (spec section 5, stages 5-8A): characters, keyframes, voice, music, mix, clips, Version A.

Modules:
  ff          ffmpeg/ffprobe helpers (probe, black/freeze/silence detection, loudness, two-pass loudnorm)
  screenplay  reads screenplay.json into shots, lines, bibles and captions (tolerant of a few shapes)
  store       per-stage registries, prompts.json files, idempotency keys, consent
  paid        every paid call: dry-run preview, quote -> reserve -> call -> settle through the ledger
  judging     the per-take judge (the stage's own rubric questions, asked about one item)
  takes       the generic take loop (generate -> local checks -> judge -> accept / reject, max_takes)
  characters, keyframes, clips, voice, music, mix, version_a   one module per layer

Every paid call goes through ledger.Ledger(root).call(); every command has --dry-run, which prints what would be
sent and the ledger check and sends nothing. Model speech is always discarded; every word on screen is an overlay."""
