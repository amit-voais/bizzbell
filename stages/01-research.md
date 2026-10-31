# Stage 1: Research

**Made by:** you, with the host agent's own web search (and fetch, where the host has it). **Output:**
`research.md`. **Rubric:** `rubrics/research.json`, judged against `brief.md`.

## Inputs

`brief.md`.

## Do

1. Search the web for: the audience and how they talk about the problem; two or more competitors or alternatives and
   the angle each sells on; facts that could become claims (product facts, market facts). Read the pages you cite.
2. Write `research.md` from `templates/research.md` with the sections **Audience, Problem in their words,
   Competitors' angles, Claims allowed, Sources, Angle**.
3. Under **Sources**, one item per page: `S<n>: <URL> read <YYYY-MM-DD>: <what the page says, one line>`.
4. Under **Claims allowed**, one item per claim, `C<n>: <claim> [S<n>]`. Facts the user gave in the brief (product,
   price, offer) are claims too, cited `[brief]`, copied without changes.
5. Gate it (loop below).

## Rules

- Every fact carries a URL and the date it was read. A fact you cannot source is not a claim.
- Nothing later in the film may claim anything that is not in **Claims allowed** (a hard question in every later
  rubric). Example numbers that are not facts are marked "Sample" on screen.
- No superlatives (best, number one, cheapest) without a source that says so. Never knock a named competitor.
- Quote the audience in their own language where you found it (Hinglish stays Hinglish).

## Gate

```
python3 scripts/bb.py gate research -p <folder>
python3 scripts/bb.py restructure research -p <folder>     # only after a fail; then gate again
```

Local checks answer RS1-RS3 (sources dated, claims cited, sections) without a model.

## Done when

`bb gate research` passes (95 or more, no hard question at no).
