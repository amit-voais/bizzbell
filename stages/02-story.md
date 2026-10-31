# Stage 2: Story

**Made by:** you (or the writer model). **Output:** `story.md`. **Rubric:** `rubrics/story.json`, judged against
`brief.md` and `research.md`.

## Inputs

`brief.md`, `research.md` (passed).

## Do

1. Write 2-3 genuinely different directions, 1-3 sentences each.
2. Choose one and say why, in terms of the brief's audience and goal and a research finding.
3. Write the beats of the chosen story with time ranges that add up to the brief's length: a hook understood with
   the sound off in the first 3 s, the problem, the turn (the product does something visible), proof, and the
   brief's call to action.
4. List the claims used (C1, C2, ...). Use `templates/story.md`.
5. Gate it.

## Rules

- One main character with a problem the audience recognises from the research.
- Every beat must be filmable as 1-3 s shots of one small action each: no crowds, stunts or anyone leaving frame.
- No real brands, logos, celebrities or competitors, named or shown.
- Claims only from research.md (hard).

## Gate

```
python3 scripts/bb.py gate story -p <folder>
python3 scripts/bb.py restructure story -p <folder>        # only after a fail; then gate again
```

## Done when

`bb gate story` passes.
