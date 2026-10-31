# Example: a Diwali reel for a bakery

A text-only worked project: the layers from the brief to the screenplay, as they look when they pass their gates.
No media and no spend. Gulmohar Bakery, its people and its offer are made up; every web source in `research.md` is
**illustrative** (example.org links stand in for the pages a real run reads with the agent's web search).

| File | Stage | Rubric |
|---|---|---|
| `brief.md` | 0 Brief | (the user's yes to a budget) |
| `research.md` | 1 Research | `rubrics/research.json` |
| `story.md` | 2 Story | `rubrics/story.json` |
| `story_humanized.md` | 3 Humanize | `rubrics/humanize.json` |
| `screenplay.md`, `screenplay.json` | 4 Screenplay, every second | `rubrics/screenplay.json` |
| `characters/bible.md` | 5 Characters (the text part; the sheets are made from it) | `rubrics/characters.json` |

Try the gates on a copy, against the offline mock (no real key, no money). The mock wants a key that starts with
`hi_`, so give it the fake test key in the same shell as the commands:

```
python3 scripts/bb.py mock --port 0      # in another terminal; it prints its URL
export HIDROGEN_API_URL=<the URL the mock printed>
export HIDROGEN_API_KEY=hi_test_0000000000000000fake     # the mock's fake key, never a real one
python3 scripts/bb.py init .tmp/bakery --brief "A 20 s Hinglish reel for a bakery's Diwali box" --lang hinglish \
    --slug bakery-diwali
cp examples/bakery-diwali/*.md examples/bakery-diwali/screenplay.json .tmp/bakery/
python3 scripts/bb.py doctor -p .tmp/bakery
python3 scripts/bb.py budget set 50 -p .tmp/bakery --note "mock run"
python3 scripts/bb.py gate screenplay -p .tmp/bakery
```

Every local check of the research, story, humanize and screenplay rubrics answers yes on these files (the test
suite checks that).

`python3 scripts/bb.py demo --mock` copies this folder into a new project and runs every stage on it against the
mock, including the media stages, both versions and `bb final`.
